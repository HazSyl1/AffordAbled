from __future__ import annotations

import re
import uuid
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any

from langgraph.types import interrupt

from app.application.services.complex_settlement import ExtraChargeInput, SettlementInput
from app.application.services.complex_settlement_service import ComplexSettlementService
from app.application.services.itemized_split import ItemAllocation, calculate_itemized_split
from app.application.services.quantity_split import QuantityAllocation
from app.application.services.settlement_split import (
    SettlementDebt,
    SplitContribution,
    calculate_settlement_split,
)
from app.application.services.split_service import ParticipantShare, SplitService, is_owner_participant_label
from app.application.services.transaction_service import TransactionService
from app.infrastructure.ai.agents.contracts import HandoffContext, VerifiedTransactionReference


class SplitToolset:
    """Scoped chat tools for creating and inspecting expense splits."""

    def __init__(self, split_service: SplitService, transaction_service: TransactionService,
                 complex_settlement_service: ComplexSettlementService | None = None) -> None:
        self._splits = split_service
        self._transactions = transaction_service
        self._complex_settlements = complex_settlement_service

    @staticmethod
    def _stated_split_group_size(source_text: str) -> int | None:
        """Return an explicit inclusive group size such as "all eight of us" when present."""
        number_words = {
            'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
            'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14,
            'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19,
            'twenty': 20,
        }
        match = re.search(
            r'\b(?:among|between|across|for|split among|divided among)\s+(?:all\s+)?'
            r'(\d{1,2}|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|'
            r'fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\s+(?:of\s+us|people|persons)\b',
            source_text,
            re.IGNORECASE,
        )
        if match is None:
            return None
        token = match.group(1).casefold()
        return int(token) if token.isdigit() else number_words[token]

    @staticmethod
    def _trusted_followup_transaction_id(context: HandoffContext) -> str | None:
        """Resolve a reference such as 'split this' from successful transaction tool evidence."""
        latest_reply = str(context.constraints.get('latest_user_reply') or context.request).strip()
        explicit_ids = re.findall(
            r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
            latest_reply, re.I,
        )
        if len(set(explicit_ids)) > 1:
            raise ValueError('Please choose one expense transaction ID to split.')
        if explicit_ids:
            return str(uuid.UUID(explicit_ids[0]))
        created_ids = context.constraints.get('created_transaction_ids') or []
        if created_ids:
            distinct_ids = list(dict.fromkeys(str(value) for value in created_ids if value))
            if len(distinct_ids) > 1:
                raise ValueError('Several expenses were recorded. Please choose which one to split.')
            if distinct_ids:
                return distinct_ids[0]
        references: list[VerifiedTransactionReference] = []
        for raw in context.constraints.get('verified_transaction_references') or []:
            try:
                references.append(VerifiedTransactionReference.model_validate(raw))
            except (TypeError, ValueError):
                continue
        pending_id = context.constraints.get('pending_split_transaction_id')
        if pending_id and any(str(reference.id) == str(pending_id) for reference in references):
            return str(pending_id)
        if not re.search(r'\b(?:this|that|these|those|them|it)\b', latest_reply, re.I):
            return None
        prior_user_messages = [
            str(message.get('content') or '')
            for message in context.history
            if isinstance(message, dict) and message.get('role') == 'user'
        ]
        if prior_user_messages and prior_user_messages[-1] == latest_reply:
            prior_user_messages.pop()
        for message in reversed(prior_user_messages):
            matching = [reference for reference in references if reference.source_request == message]
            if len(matching) > 1:
                raise ValueError('Several expenses were recorded. Please choose which one to split.')
            if matching:
                return str(matching[0].id)
        for result in reversed(context.constraints.get('prior_specialist_results') or []):
            if not isinstance(result, dict) or result.get('specialist') != 'transaction':
                continue
            if result.get('status') not in (None, 'success'):
                continue
            transactions = (result.get('data') or {}).get('created_transactions') or []
            if len(transactions) == 1 and isinstance(transactions[0], dict) and transactions[0].get('id'):
                return str(transactions[0]['id'])
        for event in reversed(context.constraints.get('recent_tool_observations') or []):
            if not isinstance(event, dict) or event.get('tool') != 'create_transaction' or event.get('ok') is not True:
                continue
            if event.get('request') not in prior_user_messages:
                continue
            transaction = (event.get('data') or {}).get('transaction') or {}
            if transaction.get('id'):
                return str(transaction['id'])
        return None

    @staticmethod
    def _validate_requested_people(people: list[ParticipantShare], context: HandoffContext) -> None:
        """Contacts can resolve requested names, but must not introduce new split participants."""
        source_text = ' '.join(
            str(value)
            for value in (
                context.request,
                context.constraints.get('original_request'),
                context.constraints.get('latest_user_reply'),
                *(message.get('content') for message in context.history if isinstance(message, dict)),
            )
            if value
        )
        saved_contacts = [
            str(name) for name in context.constraints.get('available_split_contacts', []) if name
        ]
        source_tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", source_text)
        unrequested = [
            person.name
            for person in people
            if not re.search(
                rf'(?<!\w){re.escape(person.name).replace(r"\ ", r"\s+")}(?!\w)',
                source_text,
                re.IGNORECASE,
            )
            and not any(
                saved_name.casefold() == person.name.casefold()
                and any(
                    SequenceMatcher(None, saved_name.casefold(), token.casefold()).ratio() >= 0.82
                    for token in source_tokens
                )
                for saved_name in saved_contacts
            )
        ]
        if unrequested:
            raise ValueError(
                f"Do not add split contacts the user did not name: {', '.join(unrequested)}. "
                "Use only people explicitly requested in the user's message."
            )

    @staticmethod
    def _receipt_amount_evidence(context: HandoffContext) -> set[int] | None:
        """Return printed two-decimal amounts from user supplied receipt/OCR text, when present."""
        user_messages = [
            str(message.get('content') or '')
            for message in context.history
            if str(message.get('role') or '').casefold() == 'user'
        ]
        source = '\n'.join([*user_messages, context.request])
        if not re.search(r'(?:uploaded\s+(?:a\s+)?receipt|extracted\s+text|ocr\s+data)', source, re.I):
            return None
        amounts: set[int] = set()
        for match in re.finditer(r'(?<!\d)(\d[\d,]*\.\d{2})(?!\d)', source):
            try:
                amount_paise = int(Decimal(match.group(1).replace(',', '')) * 100)
            except (ValueError, ArithmeticError):
                continue
            amounts.add(amount_paise)
        return amounts

    @staticmethod
    def _receipt_grand_total(context: HandoffContext) -> int | None:
        source = '\n'.join(
            str(message.get('content') or '')
            for message in context.history
            if str(message.get('role') or '').casefold() == 'user'
        )
        if not re.search(r'(?:uploaded\s+(?:a\s+)?receipt|extracted\s+text|ocr\s+data)', source, re.I):
            return None
        match = re.search(r'grand\s*total\s*(?:₹\s*)?([\d,]+\.\d{2})', source, re.I)
        if not match:
            return None
        return int(Decimal(match.group(1).replace(',', '')) * 100)

    @staticmethod
    def _settlement_user_text(context: HandoffContext) -> str:
        user_text = '\n'.join([
            *(str(message.get('content') or '') for message in context.history
              if str(message.get('role') or '').casefold() == 'user'),
            str(context.constraints.get('original_request') or ''),
            context.request,
        ])
        return ' '.join(user_text.split()).casefold()

    @classmethod
    def _normalize_percentage_charges(cls, data: SettlementInput, context: HandoffContext) -> None:
        """Represent an unambiguous AI-proposed percentage fee as a calculated extra."""
        user_text = cls._settlement_user_text(context)
        for bill in data.bills:
            for charge in list(bill.charges):
                quote = (charge.source_quote or '').strip()
                if not re.search(r'\b(?:fee|tip|surcharge|service charge)\b', charge.label, re.IGNORECASE):
                    continue
                rate_match = re.search(r'(?<!\d)(\d+(?:\.\d{1,2})?)\s*%', quote)
                if rate_match is None:
                    continue
                if not quote or ' '.join(quote.split()).casefold() not in user_text:
                    raise ValueError(f'{bill.merchant}: {charge.label} needs an exact percentage source quote.')
                rate_bps = int(Decimal(rate_match.group(1)) * 100)
                remaining = [row for row in bill.charges if row.id != charge.id]
                if not remaining or len(remaining) > 8:
                    raise ValueError(f'{bill.merchant}: specify which priced items the percentage fee uses.')
                possible_bases = [group for count in range(1, len(remaining) + 1)
                                  for group in combinations(remaining, count)]
                quoted_bases = [
                    group for group in possible_bases
                    if any(
                        int(Decimal(match.group(1).replace(',', '')) * 100 *
                            (1000 if (match.group(2) or '').casefold() == 'k' else 1))
                        == sum(row.amount_paise for row in group)
                        for match in re.finditer(r'(?<!\d)(\d[\d,]*(?:\.\d{1,2})?)\s*(k)?\b', quote, re.I)
                        if not quote[match.end():].lstrip().startswith('%')
                    )
                ]
                if len(quoted_bases) == 1:
                    base = quoted_bases[0]
                elif len(remaining) == 1:
                    base = tuple(remaining)
                elif re.search(r'\b(?:whole|full|subtotal|all items)\b', quote, re.I):
                    base = tuple(remaining)
                else:
                    raise ValueError(
                        f'{bill.merchant}: {charge.label} needs the priced items used as its percentage base; '
                        'use extras with rate_bps and base_charge_ids. Do not ask the user to calculate the fee.'
                    )
                affected_discounts = [discount for discount in bill.discounts
                                      if charge.id in discount.charge_ids]
                if affected_discounts and bill.extras:
                    raise ValueError(
                        f'{bill.merchant}: move {charge.label} to extras and specify which fees the coupon covers.'
                    )
                if any(len(discount.charge_ids) == 1 for discount in affected_discounts):
                    raise ValueError(f'{bill.merchant}: a coupon needs at least one priced item.')
                if any(extra.id == charge.id for extra in bill.extras):
                    raise ValueError(f'{bill.merchant}: fee and item IDs must be distinct.')
                for discount in affected_discounts:
                    discount.charge_ids.remove(charge.id)
                    discount.include_extras = True
                for payment in bill.payments:
                    if charge.id in payment.covered_charge_ids:
                        payment.covered_charge_ids.remove(charge.id)
                        payment.covered_extra_ids.append(charge.id)
                bill.extras.append(ExtraChargeInput(
                    id=charge.id, label=charge.label,
                    kind='tip' if re.search(r'\btip\b', charge.label, re.IGNORECASE) else 'fee',
                    shared_by=charge.shared_by, paid_by=charge.paid_by, rate_bps=rate_bps,
                    base_charge_ids=[row.id for row in base], source_quote=quote,
                ))
                bill.charges.remove(charge)

    @classmethod
    def _validate_settlement_amount_evidence(cls, data: SettlementInput, context: HandoffContext) -> None:
        """Reject AI draft charges whose rupee values cannot be traced to the user's words."""
        normalized_user_text = cls._settlement_user_text(context)
        for bill in data.bills:
            for row in [*bill.discounts, *bill.extras]:
                if row.rate_bps is None:
                    continue
                quote = (row.source_quote or '').strip()
                if not quote or ' '.join(quote.split()).casefold() not in normalized_user_text:
                    raise ValueError(f'{bill.merchant}: {row.label} needs an exact percentage source_quote.')
                rates = [Decimal(match.group(1)) * 100 for match in re.finditer(
                    r'(?<!\d)(\d+(?:\.\d{1,2})?)\s*%', quote
                )]
                if len(rates) != 1 or rates[0] != row.rate_bps:
                    raise ValueError(
                        f'{bill.merchant}: {row.label} rate must match the quoted percentage; '
                        '2% is rate_bps=200. Do not ask the user to calculate it.'
                    )
            for charge in bill.charges:
                quote = (charge.source_quote or '').strip()
                if not quote or ' '.join(quote.split()).casefold() not in normalized_user_text:
                    raise ValueError(
                        f'{bill.merchant}: {charge.label} needs a short, exact source_quote from the user request.'
                    )
                amount_pattern = re.compile(
                    r'(?<![\w,.])(?P<currency>₹\s*)?(?P<number>\d[\d,]*(?:\.\d{1,2})?)'
                    r'(?:\s*(?P<scale>k|thousand|lakh|lac|crore|million))?'
                    r'(?:\s*(?P<unit>rs\.?|inr|rupees?))?(?![\w,.]|\s*%)',
                    re.IGNORECASE,
                )
                scales = {'k': 1000, 'thousand': 1000, 'lakh': 100000,
                          'lac': 100000, 'crore': 10000000, 'million': 1000000}
                parsed_amounts = [
                    (Decimal(match.group('number').replace(',', ''))
                     * scales.get((match.group('scale') or '').casefold(), 1),
                     bool(match.group('currency') or match.group('scale') or match.group('unit')))
                    for match in amount_pattern.finditer(quote)
                ]
                monetary_amounts = [amount for amount, marked in parsed_amounts if marked]
                quoted_amounts = [int(amount * 100) for amount in (monetary_amounts or [
                    amount for amount, _ in parsed_amounts
                ])]
                directly_supported = any(
                    sum(group) == charge.amount_paise
                    for count in range(1, min(len(quoted_amounts), 4) + 1)
                    for group in combinations(quoted_amounts, count)
                )
                remainder_supported = any(
                    total - sum(group) == charge.amount_paise
                    for index, total in enumerate(quoted_amounts)
                    for count in range(1, min(len(quoted_amounts) - 1, 3) + 1)
                    for group in combinations(quoted_amounts[:index] + quoted_amounts[index + 1:], count)
                )
                quantity_values = [amount for amount, _ in parsed_amounts]
                quantity_supported = (
                    bool(re.search(r'\beach\b', quote, re.IGNORECASE))
                    and len(quantity_values) in {2, 3}
                    and charge.amount_paise == 100 * (
                        quantity_values[0] * quantity_values[1]
                        if len(quantity_values) == 2
                        else quantity_values[0] * quantity_values[1] * quantity_values[2]
                    )
                )
                if not (directly_supported or remainder_supported or quantity_supported):
                    raise ValueError(
                        f'{bill.merchant}: {charge.label} amount ₹{Decimal(charge.amount_paise) / 100:,.2f} '
                        f'does not match its quoted source: {quote}'
                    )

    def registry(self) -> dict[str, Any]:
        tools = {
            "list_split_contacts": self.list_split_contacts,
            "set_split_contact_preference": self.set_split_contact_preference,
            "create_split": self.create_split,
            "create_owed": self.create_owed,
            "create_owed_batch": self.create_owed_batch,
            "record_owed_payment": self.record_owed_payment,
            "list_person_split_balances": self.list_person_split_balances,
            "settle_person_balance": self.settle_person_balance,
        }
        if self._complex_settlements is not None:
            tools['create_settlement_draft'] = self.create_settlement_draft
        return tools

    async def list_person_split_balances(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        """Return current receivable/payable totals by person, including partial repayments."""
        return {'balances': await self._splits.balances_by_person(context.user_id)}

    async def settle_person_balance(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        """Review mutual debts, require explicit confirmation, and settle against the underlying split records."""
        person_name = str(args.get('person_name') or '').strip()
        if not person_name or is_owner_participant_label(person_name):
            raise ValueError('Name the other person whose balance should be settled.')
        balances = await self._splits.balances_by_person(context.user_id)
        matches = [balance for balance in balances if balance['person'].casefold() == person_name.casefold()]
        if len(matches) != 1:
            if not matches:
                raise LookupError(f'No outstanding split or IOU balance was found for {person_name}.')
            raise ValueError('That name matches multiple saved people. Use the exact saved contact name.')
        balance = matches[0]
        offset_paise = min(balance['owed_to_you_paise'], balance['you_owe_paise'])
        net_paise = balance['net_paise']
        amount_paise: int | None = None
        if args.get('amount_rupees') is not None:
            try:
                amount_rupees = Decimal(str(args['amount_rupees']))
                amount_value = amount_rupees * 100
                if not amount_rupees.is_finite() or amount_value != amount_value.to_integral_value():
                    raise ValueError
                amount_paise = int(amount_value)
            except (ArithmeticError, TypeError, ValueError):
                raise ValueError('Use an amount with no more than two decimal places.') from None
            if amount_paise <= 100:
                raise ValueError('Enter a partial cash payment greater than one rupee.')
            if amount_paise > abs(net_paise):
                raise ValueError('Cash settlement cannot exceed the net amount after offsetting mutual debts.')
        cash_paise = abs(net_paise) if amount_paise is None else amount_paise
        direction = 'to_you' if net_paise > 0 else 'by_you'

        def money(amount: int) -> str:
            return f'₹{Decimal(amount) / 100:,.2f}'

        account = None
        if cash_paise:
            accounts = context.constraints.get('available_accounts') or []
            requested_account = str(args.get('account_name') or '').strip().casefold()
            if requested_account:
                account = next((item for item in accounts if str(item.get('name', '')).casefold() == requested_account
                                and item.get('is_active', True)), None)
                if account is None:
                    raise LookupError(f'Active wallet account "{args.get("account_name")}" was not found.')
            else:
                account = next(
                    (item for item in accounts if item.get('is_active', True) and item.get('is_default')), None,
                )
                if account is None:
                    active_accounts = [item for item in accounts if item.get('is_active', True)]
                    account = active_accounts[0] if len(active_accounts) == 1 else None
            if account is None:
                raise ValueError('Choose an active wallet account for the cash settlement.')

        def entry_key(entry: dict[str, Any]) -> tuple[str, str, int | None]:
            return (entry['split_id'], entry['participant_id'], entry.get('transfer_index'))

        offset_allocations: dict[str, list[tuple[tuple[str, str, int | None], int]]] = {
            'to_you': [], 'by_you': [],
        }
        for entry_direction in ('to_you', 'by_you'):
            remaining_offset = offset_paise
            for entry in balance['entries']:
                if entry['direction'] != entry_direction or remaining_offset <= 0:
                    continue
                applied = min(entry['remaining_paise'], remaining_offset)
                offset_allocations[entry_direction].append((entry_key(entry), applied))
                remaining_offset -= applied

        payment_allocations: list[tuple[str, int]] = []
        remaining_cash = cash_paise
        for entry in balance['entries']:
            if entry['direction'] != direction or remaining_cash <= 0:
                continue
            already_offset = sum(amount for key, amount in offset_allocations[direction]
                                 if key == entry_key(entry))
            available = max(0, entry['remaining_paise'] - already_offset)
            applied = min(available, remaining_cash)
            if applied:
                payment_allocations.append((entry['title'], applied))
                remaining_cash -= applied

        detail = (
            f'Balance with {balance["person"]}: they owe you {money(balance["owed_to_you_paise"])}; '
            f'you owe them {money(balance["you_owe_paise"])}. Offset {money(offset_paise)} across both sides. '
        )
        if cash_paise:
            cash_action = 'receive from them' if direction == 'to_you' else 'pay them'
            allocation_text = '; '.join(f'{title}: {money(amount)}' for title, amount in payment_allocations)
            detail += (
                f'After offset, {cash_action} {money(cash_paise)}'
                f'{" (partial)" if cash_paise < abs(net_paise) else ""}. '
                f'Apply the cash amount to the smallest open split entries first: {allocation_text}. '
                f'Wallet account: {account.get("name")}. This creates Split-category wallet transaction(s).'
            )
        else:
            detail += 'The balances cancel exactly, so no cash transaction is created.'
        answer = interrupt({
            'agent': 'split',
            'question': f'{detail} Confirm this settlement?'
        })
        if str(answer).strip().casefold() not in {'yes', 'y', 'confirm', 'confirmed', 'proceed'}:
            return {'settlement': {
                'status': 'cancelled', 'person': balance['person'], 'offset_paise': offset_paise,
                'cash_paise': cash_paise,
            }}

        result = await self._splits.settle_balance(
            context.user_id, balance['person'],
            uuid.UUID(str(account['id'])) if account else None,
            amount_paise, balance['owed_to_you_paise'], balance['you_owe_paise'],
        )
        return {'settlement': {'status': 'settled', **result}}

    async def create_settlement_draft(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        """Save only a preview; the user confirms and commits the wallet changes in the planner."""
        if self._complex_settlements is None:
            raise ValueError('Settlement planner is unavailable.')
        data = SettlementInput.model_validate(args['data'])
        self._normalize_percentage_charges(data, context)
        self._validate_settlement_amount_evidence(data, context)
        requested = [person for person in data.participants if person.casefold() != 'you']
        self._validate_requested_people([ParticipantShare(name, 0) for name in requested], context)
        draft = await self._complex_settlements.create_draft(
            context.user_id, str(uuid.uuid4()), data,
        )
        return {'settlement_draft': {
            'id': str(draft.id), 'title': data.title, 'total_paise': draft.preview_json['total_paise'],
            'bill_count': len(data.bills),
        }}

    async def create_owed(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        """Track a standalone IOU without creating a purchase or expense split."""
        raw_amount = args.get('amount_paise')
        if isinstance(raw_amount, bool) or not isinstance(raw_amount, int) or raw_amount <= 0:
            raise ValueError('amount_paise must be a positive integer amount in paise.')
        name = str(args.get('name') or '').strip()
        if not name or is_owner_participant_label(name):
            raise ValueError('Name the other person who owes you.')
        self._validate_requested_people([ParticipantShare(name, raw_amount)], context)
        title = str(args.get('title') or 'Money owed').strip()
        direction = str(args.get('direction') or 'to_you')
        if direction not in {'to_you', 'by_you'}:
            raise ValueError('direction must be to_you or by_you.')
        split = await self._splits.create_owed(
            context.user_id, title, name, raw_amount, direction, owner_name=context.owner_name,
        )
        result = {
            'id': str(split.id), 'kind': 'money_owed', 'direction': direction,
            'title': split.title, 'amount_paise': raw_amount, 'person': split.participants[0].name,
        }
        return {'receivable' if direction == 'to_you' else 'payable': result}

    async def create_owed_batch(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        entries = args.get('entries') or []
        people: list[ParticipantShare] = []
        for entry in entries:
            try:
                rupees = Decimal(str(entry.get('amount_rupees')))
                divisor = entry.get('divided_by')
                if divisor is not None:
                    if isinstance(divisor, bool) or not isinstance(divisor, int) or divisor <= 0:
                        raise ValueError
                    rupees /= divisor
                paise = rupees * 100
                if not rupees.is_finite() or paise != paise.to_integral_value() or paise <= 0:
                    raise ValueError
            except (ArithmeticError, TypeError, ValueError):
                raise ValueError('Each IOU amount must resolve to a positive exact number of paise.') from None
            people.append(ParticipantShare(str(entry.get('name') or '').strip(), int(paise)))
        direction = str(args.get('direction') or 'by_you')
        title = str(args.get('title') or 'Money owed').strip()
        splits = await self._splits.create_owed_batch(
            context.user_id, title, people, direction, owner_name=context.owner_name,
        )
        key = 'receivables' if direction == 'to_you' else 'payables'
        return {key: [
            {
                'id': str(split.id), 'kind': 'money_owed', 'direction': direction,
                'title': split.title, 'amount_paise': person.share_paise, 'person': person.name,
            }
            for split in splits for person in split.participants
        ]}

    async def record_owed_payment(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        person_name = str(args.get('person_name') or '').strip()
        if not person_name:
            raise ValueError('Name the person whose IOU you paid or received.')
        direction = str(args.get('direction') or '')
        if direction not in {'to_you', 'by_you'}:
            raise ValueError('Choose whether you paid the person or they paid you.')
        if is_owner_participant_label(person_name):
            raise ValueError('Name the other person in the IOU, not yourself.')

        splits = await self._splits.list_for_user(context.user_id)
        matches = []
        title = str(args.get('title') or '').strip().casefold()
        for split in splits:
            split_direction = 'to_you' if split.transaction_id is not None else split.direction
            if split_direction != direction or (title and title not in split.title.casefold()):
                continue
            for participant in split.participants:
                if participant.name.casefold() != person_name.casefold():
                    continue
                remaining = participant.share_paise - participant.settled_paise
                if remaining > 0:
                    matches.append((split, participant, remaining))
        if not matches:
            raise LookupError(f'No outstanding {direction} split or IOU was found for {person_name}.')
        if len(matches) > 1:
            options = '; '.join(
                f'"{split.title}" ({remaining} paise remaining)' for split, _, remaining in matches[:5]
            )
            raise ValueError(
                f'Multiple open IOUs match {person_name}: {options}. Ask which one before recording payment.'
            )

        accounts = context.constraints.get('available_accounts') or []
        requested_account = str(args.get('account_name') or '').strip().casefold()
        if requested_account:
            account = next((item for item in accounts if str(item.get('name', '')).casefold() == requested_account
                            and item.get('is_active', True)), None)
        else:
            account = next((item for item in accounts if item.get('is_active', True) and item.get('is_default')), None)
            if account is None:
                active_accounts = [item for item in accounts if item.get('is_active', True)]
                account = active_accounts[0] if len(active_accounts) == 1 else None
        if account is None:
            if requested_account:
                raise LookupError(f'Active wallet account "{args.get("account_name")}" was not found.')
            raise ValueError('Choose which wallet account was used for this payment.')

        amount_paise = None
        if args.get('amount_rupees') is not None:
            try:
                amount_rupees = Decimal(str(args['amount_rupees']))
                amount_paise_decimal = amount_rupees * 100
                if not amount_rupees.is_finite() or amount_paise_decimal != amount_paise_decimal.to_integral_value():
                    raise ValueError
                amount_paise = int(amount_paise_decimal)
            except (ArithmeticError, TypeError, ValueError):
                raise ValueError('Enter a payment amount with no more than two decimal places.') from None

        split, participant, _ = matches[0]
        previous_payment_ids = {payment.id for payment in participant.payments}
        updated = await self._splits.record_payment(
            context.user_id, split.id, participant.id, uuid.UUID(str(account['id'])), amount_paise,
        )
        if updated is None:
            raise LookupError('The IOU changed while recording payment. Refresh the splits list and retry.')
        updated_participant = next(item for item in updated.participants if item.id == participant.id)
        payment = next(item for item in updated_participant.payments if item.id not in previous_payment_ids)
        return {'payment': {
            'split_id': str(updated.id), 'title': updated.title, 'person': participant.name,
            'direction': direction, 'amount_paise': payment.amount_paise,
            'remaining_paise': updated_participant.share_paise - updated_participant.settled_paise,
            'fully_settled': updated_participant.settled_paise == updated_participant.share_paise,
            'transaction_id': str(payment.transaction_id) if payment.transaction_id else None,
            'account_name': account.get('name'),
        }}

    async def list_split_contacts(self, context: HandoffContext, _args: dict[str, Any]) -> dict[str, Any]:
        preferences = await self._splits.list_contact_preferences(context.user_id)
        return {
            "contacts": await self._splits.contact_names(context.user_id),
            "confirmed_preferences": [
                {"name": contact.name, "dietary_preference": contact.dietary_preference}
                for contact in preferences if contact.dietary_preference
            ],
            "preference_suggestions": await self._splits.contact_preference_suggestions(context.user_id),
        }

    async def set_split_contact_preference(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get('name') or '').strip()
        preference = args.get('dietary_preference')
        if preference is not None:
            preference = str(preference).strip().casefold()
            preference = {
                'veg': 'vegetarian', 'nonveg': 'omnivore', 'non-veg': 'omnivore',
                'eats meat': 'omnivore',
            }.get(preference, preference)
        contact = await self._splits.set_contact_preference(context.user_id, name, preference)
        return {
            'contact': {'id': str(contact.id), 'name': contact.name,
                        'dietary_preference': contact.dietary_preference},
        }

    async def create_split(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        if (
            'itemized split' in context.request.casefold()
            and args.get('items') is None
            and args.get('quantity_allocations') is None
        ):
            raise ValueError('An itemized split needs priced items and the people who shared each item.')
        source_request = ' '.join(str(value or '') for value in (
            context.request, context.constraints.get('original_request'),
        ))
        quantity_rule = bool(
            re.search(r'\b\d+\b.{0,80}\beach\b', source_request, re.I)
            and re.search(r'\b(?:rest|remainder|remaining)\b', source_request, re.I)
        )
        if quantity_rule and not args.get('quantity_allocations'):
            raise ValueError(
                'This request specifies quantities per person and divides the rest equally. '
                'Use quantity_allocations with people, quantity_per_person, and unit_price_rupees; '
                'the tool calculates the remainder from the transaction.'
            )
        if args.get('quantity_allocations') is not None and args.get('items') is not None:
            raise ValueError('Use quantity_allocations or itemized rows, not both.')
        trusted_transaction_id = self._trusted_followup_transaction_id(context)
        latest_reply = str(context.constraints.get('latest_user_reply') or context.request)
        if (trusted_transaction_id is None
                and re.search(r'\b(?:this|that|these|those|them|it)\b', latest_reply, re.I)
                and not re.search(
                    r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
                    latest_reply, re.I,
                )):
            raise ValueError(
                'I cannot identify the saved expense from this chat. Select it in Splits or provide its ID.'
            )
        transaction_id = trusted_transaction_id or args.get("transaction_id")
        if not transaction_id:
            created = context.constraints.get("created_transaction_ids") or []
            transaction_id = created[-1] if created else None
        if not transaction_id:
            transaction_id = context.constraints.get('pending_split_transaction_id')
        if not transaction_id:
            handoff = context.constraints.get('supervisor_handoff') or {}
            transaction_id = handoff.get('transaction_id')
        if not transaction_id and 'split' in context.request.casefold() and re.search(
            r'\b(?:that|this|receipt|it)\b', context.request.casefold()
        ):
            prior_results = context.constraints.get('prior_specialist_results') or []
            prior_transactions = [
                transaction
                for result in prior_results[-5:]
                if result.get('specialist') == 'transaction'
                for transaction in (result.get('data') or {}).get('created_transactions', [])
                if isinstance(transaction, dict) and transaction.get('id')
            ]
            if len(prior_transactions) == 1:
                transaction_id = prior_transactions[0]['id']
        if not transaction_id:
            raise ValueError("The expense transaction must be recorded before creating its split.")
        transaction = await self._transactions.get_transaction(context.user_id, uuid.UUID(str(transaction_id)))
        if transaction.type.value != "expense":
            raise ValueError("Only expense transactions can have a split.")
        receipt_total = self._receipt_grand_total(context)
        if args.get('items') is not None and receipt_total is not None and transaction.amount_paise != receipt_total:
            receipt_total_rupees = Decimal(receipt_total) / 100
            transaction_total_rupees = Decimal(transaction.amount_paise) / 100
            raise ValueError(
                f'The receipt grand total is ₹{receipt_total_rupees:.2f}, but the linked transaction is '
                f'₹{transaction_total_rupees:.2f}. Correct the transaction amount before creating an itemized split.'
            )
        raw_people = args.get("participants") or args.get("people")
        if args.get('quantity_allocations') is not None and not raw_people:
            raise ValueError(
                'Quantity remainder splits require participants with every external person sharing the remainder, '
                'including people who received no priced item. Do not infer the full group only from '
                'quantity_allocations.'
            )
        if raw_people is None:
            # The tool schema already contains the names on item/allocation
            # rows. Recover their ordered union instead of failing because the
            # model did not duplicate those names at the top level.
            inferred_people: list[str] = []
            for allocation in args.get('quantity_allocations') or []:
                if isinstance(allocation, dict):
                    inferred_people.extend(str(name) for name in allocation.get('people') or [])
            for item in args.get('items') or []:
                if isinstance(item, dict):
                    inferred_people.extend(str(name) for name in item.get('shared_by') or [])
            raw_people = list(dict.fromkeys(
                name.strip() for name in inferred_people
                if name.strip() and not is_owner_participant_label(name)
            ))
        if not isinstance(raw_people, list):
            raise ValueError("participants must be a list of person names.")
        people: list[ParticipantShare] = []
        for item in raw_people:
            if isinstance(item, str):
                name, share = item, 0
            elif isinstance(item, dict):
                name, share = item.get("name"), item.get("share_paise", item.get("share", 0))
            else:
                raise ValueError("Each participant must include a name.")
            if not name:
                raise ValueError("Each participant must include a name.")
            if isinstance(share, float):
                share = round(share * 100)
            participant_name = str(name).strip()
            # The model can copy the item's owner marker into the external
            # participant list. The owner share is tracked separately.
            if is_owner_participant_label(participant_name):
                continue
            people.append(ParticipantShare(participant_name, int(share)))
        if not people:
            raise ValueError('Name at least one other person; your own share is tracked separately.')
        self._validate_requested_people(people, context)
        if args.get('quantity_allocations') is not None:
            stated_group_size = self._stated_split_group_size(source_request)
            actual_group_size = len(people) + 1
            if stated_group_size is not None and actual_group_size != stated_group_size:
                raise ValueError(
                    f'The request says the remainder is shared by {stated_group_size} people including the owner, '
                    f'but participants contains only {len(people)} external people. Include every named remainder '
                    'participant before calculating the split.'
                )
        mode = str(args.get("mode") or "equal").lower()
        owner_share = args.get("owner_share_paise")
        if owner_share is None and args.get("owner_share_rupees") is not None:
            owner_share = round(float(args["owner_share_rupees"]) * 100)
        item_breakdown = None
        settlement_breakdown = None
        has_quantity_allocations = args.get('quantity_allocations') is not None
        has_settlement_adjustments = bool(args.get('debts') or args.get('contributions'))
        if has_quantity_allocations and not quantity_rule:
            raise ValueError(
                'quantity_allocations require an explicit quantity per person and per-unit price in the request. '
                'For a total amount shared by named people, use an item row with amount_paise and shared_by.'
            )
        if has_quantity_allocations or has_settlement_adjustments:
            source_numbers = {
                Decimal(value.replace(',', ''))
                for value in re.findall(r'(?<!\d)\d[\d,]*(?:\.\d+)?(?!\d)', source_request)
            }
            allocations: list[QuantityAllocation] = []
            allocation_details: list[dict[str, Any]] = []
            for raw in args.get('quantity_allocations') or []:
                if not isinstance(raw, dict):
                    raise ValueError('Each quantity allocation needs people, quantity, and unit price.')
                quantity = raw.get('quantity_per_person')
                price = Decimal(str(raw.get('unit_price_rupees')))
                price_paise = price * 100
                if (
                    isinstance(quantity, bool) or not isinstance(quantity, int)
                    or Decimal(quantity) not in source_numbers or price not in source_numbers
                    or price_paise != price_paise.to_integral_value()
                ):
                    raise ValueError('Quantity and unit price must match numbers in the user request.')
                allocations.append(QuantityAllocation(
                    people=list(raw.get('people') or []),
                    quantity_per_person=quantity,
                    unit_price_paise=int(price_paise),
                ))
                allocation_details.append({
                    'item_name': str(raw.get('item_name') or 'Priced item').strip(),
                    'people': list(raw.get('people') or []),
                    'quantity_per_person': quantity,
                    'unit_price_paise': int(price_paise),
                    'total_paise': len(raw.get('people') or []) * quantity * int(price_paise),
                })
            debts: list[SettlementDebt] = []
            for raw in args.get('debts') or []:
                amount_rupees = Decimal(str(raw.get('amount_rupees')))
                amount_paise = amount_rupees * 100
                if amount_rupees not in source_numbers or amount_paise != amount_paise.to_integral_value():
                    raise ValueError('Every debt amount must match an amount stated in the user request.')
                debts.append(SettlementDebt(
                    debtor=str(raw.get('debtor') or '').strip(),
                    creditor=str(raw.get('creditor') or '').strip(),
                    amount_paise=int(amount_paise),
                ))
            contributions: list[SplitContribution] = []
            for raw in args.get('contributions') or []:
                amount_rupees = Decimal(str(raw.get('amount_rupees')))
                amount_paise = amount_rupees * 100
                if amount_rupees not in source_numbers or amount_paise != amount_paise.to_integral_value():
                    raise ValueError('Every contribution amount must match an amount stated in the user request.')
                contributions.append(SplitContribution(
                    person=str(raw.get('person') or '').strip(), amount_paise=int(amount_paise),
                ))

            calculation = calculate_settlement_split(
                transaction.amount_paise,
                [person.name for person in people],
                allocations,
                contributions,
                debts,
            )
            owner_share = calculation.owner_share_paise
            calculated_shares = calculation.participant_shares
            remaining_paise = calculation.remainder_paise

            def amount(paise: int) -> str:
                return f'₹{Decimal(paise) / 100:,.2f}'

            summary = ', '.join(
                [f'you: {amount(owner_share)}', *[
                    f'{name}: {amount(share)}' for name, share in calculated_shares.items()
                ]]
            )
            allocation_summary = (
                f'Priced items total {amount(calculation.priced_items_paise)}; '
                if allocation_details else ''
            )
            remainder_summary = (
                f'{amount(remaining_paise)} is divided equally among you and {len(people)} other people. '
                if allocation_details else ''
            )
            settlement_summary = ''
            if has_settlement_adjustments:
                transfer_summary = '; '.join(
                    f"{transfer.debtor} pays {transfer.creditor} {amount(transfer.amount_paise)}"
                    for transfer in calculation.transfers
                ) or 'No transfers are needed after netting the listed payments and debts.'
                settlement_summary = f' Settlement plan: {transfer_summary}.'
                settlement_breakdown = {
                    'priced_items_paise': calculation.priced_items_paise,
                    'remainder_paise': calculation.remainder_paise,
                    'contributions': [
                        {'person': item.person, 'amount_paise': item.amount_paise}
                        for item in calculation.contributions
                    ],
                    'debts': [
                        {
                            'debtor': item.debtor,
                            'creditor': item.creditor,
                            'amount_paise': item.amount_paise,
                        }
                        for item in calculation.debts
                    ],
                    'transfers': [
                        {
                            'debtor': item.debtor,
                            'creditor': item.creditor,
                            'amount_paise': item.amount_paise,
                        }
                        for item in calculation.transfers
                    ],
                    'quantity_allocations': allocation_details,
                }
            answer = interrupt({
                'agent': 'split',
                'question': (
                    f'{allocation_summary}{remainder_summary}Expense shares: {summary}.'
                    f'{settlement_summary} Confirm this split?'
                ),
            })
            if str(answer).strip().casefold() not in {'yes', 'y', 'confirm', 'confirmed', 'proceed'}:
                raise ValueError(f'Split was not saved. User correction or refusal: {str(answer).strip()[:400]}')
            mode = 'custom'
            people = [ParticipantShare(name, share) for name, share in calculated_shares.items()]
        if args.get('items') is not None:
            raw_items = args['items']
            if not isinstance(raw_items, list):
                raise ValueError('items must be a list of receipt line items.')
            if len(raw_items) > 20:
                raise ValueError('Review at most 20 receipt items in chat at once.')
            for item in raw_items:
                if not isinstance(item, dict) or isinstance(item.get('amount_paise'), (bool, float)):
                    raise ValueError('Each receipt item needs an integer amount_paise.')
                if 'owner_excluded' in item and not isinstance(item['owner_excluded'], bool):
                    raise ValueError('owner_excluded must be true or false.')
                if not str(item.get('amount_paise') or '').isascii() or not str(
                    item.get('amount_paise') or ''
                ).isdecimal():
                    raise ValueError('Each receipt item needs an integer amount_paise.')
            items = [
                ItemAllocation(
                    name=str(item['name']), amount_paise=int(item['amount_paise']),
                    shared_by=list(item.get('shared_by') or []),
                    food_type=str(item.get('food_type') or 'unknown'),
                    owner_excluded=bool(item.get('owner_excluded', False)),
                )
                for item in raw_items
            ]
            receipt_amounts = self._receipt_amount_evidence(context)
            if receipt_amounts is not None:
                unsupported = [item.name for item in items if item.amount_paise not in receipt_amounts]
                if unsupported:
                    raise ValueError(
                        'These itemized amounts do not appear in the uploaded receipt: '
                        f'{", ".join(unsupported)}. Use only printed item and tax amounts. Do not invent a '
                        '"Remaining Bill" or estimated tax/fee row to force the total to match. If printed rows '
                        'do not add up to the transaction total, ask the user to clarify the missing charge.'
                    )
            contacts = await self._splits.list_contact_preferences(context.user_id)
            calculation = calculate_itemized_split(
                transaction.amount_paise, [person.name for person in people], items,
                {contact.normalized_name: contact.dietary_preference for contact in contacts},
            )
            summary = ', '.join(
                [f'you: ₹{Decimal(calculation.owner_share_paise) / 100:.2f}', *[
                    f'{name}: ₹{Decimal(amount) / 100:.2f}'
                    for name, amount in calculation.participant_shares.items()
                ]]
            )
            item_summary = '; '.join(
                f"{item['name']} ₹{Decimal(item['amount_paise']) / 100:.2f} shared by "
                f"{', '.join(share['person'] for share in item['allocations'])}"
                for item in calculation.items
            )
            warnings = f" Warnings: {' '.join(calculation.warnings)}" if calculation.warnings else ''
            answer = interrupt({
                'agent': 'split',
                'question': f'Review the items: {item_summary}. Shares: {summary}.{warnings} Confirm this split?'
            })
            if str(answer).strip().casefold() not in {'yes', 'y', 'confirm', 'confirmed', 'proceed'}:
                feedback = str(answer).strip()[:400]
                raise ValueError(
                    f'Itemized split was not saved. User correction or refusal: {feedback}. '
                    'Revise the items if specific changes were given; otherwise ask what to change.'
                )
            mode = 'custom'
            owner_share = calculation.owner_share_paise
            people = [ParticipantShare(name, amount) for name, amount in calculation.participant_shares.items()]
            item_breakdown = calculation.items
        split = await self._splits.create(
            context.user_id,
            transaction.id,
            str(args.get("title") or transaction.merchant or transaction.note or "Shared expense"),
            transaction.amount_paise,
            mode,
            people,
            int(owner_share) if owner_share is not None else None,
            item_breakdown,
            settlement_breakdown,
        )
        return {
            "split": {
                "id": str(split.id),
                "transaction_id": str(split.transaction_id),
                "title": split.title,
                "owner_share_paise": split.owner_share_paise,
                "total_paise": split.owner_share_paise + sum(person.share_paise for person in split.participants),
                "participants": [
                    {"name": person.name, "share_paise": person.share_paise}
                    for person in split.participants
                ],
                "settlement_breakdown": settlement_breakdown,
            }
        }
