from __future__ import annotations

import re
import uuid
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from langgraph.types import interrupt

from app.application.services.itemized_split import ItemAllocation, calculate_itemized_split
from app.application.services.quantity_split import QuantityAllocation, calculate_quantity_split
from app.application.services.split_service import ParticipantShare, SplitService, is_owner_participant_label
from app.application.services.transaction_service import TransactionService
from app.infrastructure.ai.agents.contracts import HandoffContext


class SplitToolset:
    """Scoped chat tools for creating and inspecting expense splits."""

    def __init__(self, split_service: SplitService, transaction_service: TransactionService) -> None:
        self._splits = split_service
        self._transactions = transaction_service

    @staticmethod
    def _validate_requested_people(people: list[ParticipantShare], context: HandoffContext) -> None:
        """Contacts can resolve requested names, but must not introduce new split participants."""
        source_text = ' '.join(
            str(value)
            for value in (
                context.request,
                context.constraints.get('original_request'),
                context.constraints.get('latest_user_reply'),
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

    def registry(self) -> dict[str, Any]:
        return {
            "list_split_contacts": self.list_split_contacts,
            "set_split_contact_preference": self.set_split_contact_preference,
            "create_split": self.create_split,
            "create_owed": self.create_owed,
        }

    async def create_owed(self, context: HandoffContext, args: dict[str, Any]) -> dict[str, Any]:
        """Track an explicit receivable without fabricating a transaction or expense split."""
        raw_amount = args.get('amount_paise')
        if isinstance(raw_amount, bool) or not isinstance(raw_amount, int) or raw_amount <= 0:
            raise ValueError('amount_paise must be a positive integer amount in paise.')
        name = str(args.get('name') or '').strip()
        if not name or is_owner_participant_label(name):
            raise ValueError('Name the other person who owes you.')
        self._validate_requested_people([ParticipantShare(name, raw_amount)], context)
        title = str(args.get('title') or 'Money owed').strip()
        split = await self._splits.create_owed(context.user_id, title, name, raw_amount)
        return {'receivable': {
            'id': str(split.id), 'kind': 'money_owed', 'title': split.title,
            'amount_paise': raw_amount,
            'person': split.participants[0].name,
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
        transaction_id = args.get("transaction_id")
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
        mode = str(args.get("mode") or "equal").lower()
        owner_share = args.get("owner_share_paise")
        if owner_share is None and args.get("owner_share_rupees") is not None:
            owner_share = round(float(args["owner_share_rupees"]) * 100)
        item_breakdown = None
        if args.get('quantity_allocations') is not None:
            source_numbers = {
                Decimal(value.replace(',', ''))
                for value in re.findall(r'(?<!\d)\d[\d,]*(?:\.\d+)?(?!\d)', source_request)
            }
            allocations: list[QuantityAllocation] = []
            for raw in args['quantity_allocations']:
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
            owner_share, calculated_shares, remaining_paise = calculate_quantity_split(
                transaction.amount_paise, [person.name for person in people], allocations,
            )
            def amount(paise: int) -> str:
                return f'₹{Decimal(paise) / 100:,.2f}'
            summary = ', '.join(
                [f'you: {amount(owner_share)}', *[
                    f'{name}: {amount(share)}' for name, share in calculated_shares.items()
                ]]
            )
            answer = interrupt({
                'agent': 'split',
                'question': (
                    f'Priced items total {amount(transaction.amount_paise - remaining_paise)}; '
                    f'{amount(remaining_paise)} is divided equally among you and {len(people)} other people. '
                    f'Shares: {summary}. Confirm this split?'
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
            }
        }
