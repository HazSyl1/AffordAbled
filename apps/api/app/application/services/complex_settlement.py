"""Deterministic, paise-based allocation for bills paid by several people."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_SAFE_PAISE = 9_007_199_254_740_991
OWNER_ALIASES = frozenset({
    'you', 'me', 'myself', 'i', 'self', 'owner', 'my share', 'my card', 'the user', 'wallet owner',
})


def _owner_label(value: object) -> object:
    if isinstance(value, str) and value.strip().casefold() in OWNER_ALIASES:
        return 'You'
    return value


class ChargeInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=255)
    amount_paise: int = Field(gt=0, le=MAX_SAFE_PAISE)
    shared_by: list[str] = Field(min_length=1, max_length=21)
    paid_by: str | None = Field(default=None, min_length=1, max_length=100)
    source_quote: str | None = Field(
        default=None, max_length=240,
        description='For AI drafts, an exact short excerpt of the user message supporting this amount.',
    )


class DiscountInput(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    charge_ids: list[str] = Field(min_length=1)
    amount_paise: int | None = Field(default=None, gt=0, le=MAX_SAFE_PAISE)
    rate_bps: int | None = Field(default=None, gt=0, le=10000)
    include_extras: bool = False
    source_quote: str | None = Field(default=None, max_length=240)

    @model_validator(mode='after')
    def one_amount(self):
        if (self.amount_paise is None) == (self.rate_bps is None):
            raise ValueError('Provide exactly one discount amount or rate.')
        return self


class ExtraChargeInput(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=255)
    kind: Literal['fee', 'tip']
    shared_by: list[str] = Field(min_length=1, max_length=21)
    paid_by: str | None = Field(default=None, min_length=1, max_length=100)
    amount_paise: int | None = Field(default=None, gt=0, le=MAX_SAFE_PAISE)
    rate_bps: int | None = Field(default=None, gt=0, le=100000)
    base_charge_ids: list[str] | None = None
    base_paise: int | None = Field(default=None, gt=0, le=MAX_SAFE_PAISE)
    source_quote: str | None = Field(default=None, max_length=240)

    @model_validator(mode='after')
    def one_amount_and_base(self):
        if (self.amount_paise is None) == (self.rate_bps is None):
            raise ValueError('Provide exactly one fee/tip amount or rate.')
        if self.rate_bps is not None and (self.base_charge_ids is None) == (self.base_paise is None):
            raise ValueError('A percentage fee/tip needs exactly one charge list or explicit base.')
        return self


class PaymentInput(BaseModel):
    person: str = Field(min_length=1, max_length=100)
    amount_paise: int | None = Field(default=None, gt=0, le=MAX_SAFE_PAISE)
    covered_charge_ids: list[str] = Field(default_factory=list, max_length=100)
    covered_extra_ids: list[str] = Field(default_factory=list, max_length=30)
    transaction_id: str | None = None
    account_id: str | None = None
    category_id: str | None = None
    occurred_at: str | None = None

    @model_validator(mode='after')
    def one_payment_source(self):
        if self.amount_paise is not None and (self.covered_charge_ids or self.covered_extra_ids):
            raise ValueError('Use either an explicit payment amount or covered bill rows.')
        return self


class BillInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    merchant: str = Field(min_length=1, max_length=255)
    charges: list[ChargeInput] = Field(min_length=1, max_length=100)
    discounts: list[DiscountInput] = Field(default_factory=list, max_length=20)
    extras: list[ExtraChargeInput] = Field(default_factory=list, max_length=30)
    payments: list[PaymentInput] = Field(default_factory=list, max_length=30)
    stated_total_paise: int | None = Field(default=None, gt=0, le=MAX_SAFE_PAISE)

    @model_validator(mode='before')
    @classmethod
    def move_misplaced_extras(cls, value):
        """Accept a fee/tip placed in charges before nested charge validation runs."""
        if not isinstance(value, dict):
            return value
        charges = value.get('charges')
        if not isinstance(charges, list):
            return value
        moved = [row for row in charges if isinstance(row, dict) and row.get('kind') in {'fee', 'tip'}]
        if not moved:
            return value
        value = dict(value)
        value['charges'] = [row for row in charges if row not in moved]
        value['extras'] = [*(value.get('extras') or []), *moved]
        moved_ids = {row.get('id') for row in moved if row.get('id')}
        payments = []
        for payment in value.get('payments') or []:
            if not isinstance(payment, dict):
                payments.append(payment)
                continue
            payment = dict(payment)
            covered = payment.get('covered_charge_ids') or []
            payment['covered_charge_ids'] = [row_id for row_id in covered if row_id not in moved_ids]
            payment['covered_extra_ids'] = [
                *(payment.get('covered_extra_ids') or []),
                *(row_id for row_id in covered if row_id in moved_ids),
            ]
            payments.append(payment)
        value['payments'] = payments
        discounts = []
        for discount in value.get('discounts') or []:
            if not isinstance(discount, dict):
                discounts.append(discount)
                continue
            discount = dict(discount)
            ids = discount.get('charge_ids') or []
            if any(row_id in moved_ids for row_id in ids):
                if not any(row_id not in moved_ids for row_id in ids) or value['extras'] != moved:
                    raise ValueError('Specify which priced items and fees the coupon covers.')
                discount['charge_ids'] = [row_id for row_id in ids if row_id not in moved_ids]
                discount['include_extras'] = True
            discounts.append(discount)
        value['discounts'] = discounts
        return value

    @model_validator(mode='after')
    def resolve_row_payers(self):
        rows = [*self.charges, *self.extras]
        assigned = [row for row in rows if row.paid_by]
        if not assigned:
            if not self.payments:
                raise ValueError('Name who paid the bill or each item and fee.')
            return self
        if len(assigned) != len(rows):
            raise ValueError('When assigning payers by row, name who paid every item, fee, and tip.')
        if any(extra.id is None for extra in self.extras):
            raise ValueError('Fees and tips need IDs when assigning payers by row.')

        payer_names: dict[str, str] = {}
        for row in rows:
            name = row.paid_by.strip()
            payer_names.setdefault(name.casefold(), name)
        existing = {payment.person.strip().casefold(): payment for payment in self.payments}
        if len(existing) != len(self.payments):
            raise ValueError('List each bill payer only once.')
        if any(name not in payer_names for name in existing):
            raise ValueError('A bill payment names someone who paid none of its rows.')
        if len(payer_names) > 1 and self.discounts and (
            len(self.payments) != len(payer_names)
            or not all(payment.amount_paise is not None for payment in self.payments)
        ):
            raise ValueError('With multiple payers and a coupon, enter each actual payment amount.')
        if not self.payments:
            self.payments = [PaymentInput(person=name) for name in payer_names.values()]
            existing = {payment.person.strip().casefold(): payment for payment in self.payments}
        for key, name in payer_names.items():
            payment = existing.get(key)
            if payment is None:
                payment = PaymentInput(person=name)
                self.payments.append(payment)
            if payment.amount_paise is not None:
                continue
            if payment.covered_charge_ids or payment.covered_extra_ids:
                expected_charges = {row.id for row in self.charges if row.paid_by.casefold() == key}
                expected_extras = {row.id for row in self.extras if row.paid_by.casefold() == key}
                if (
                    set(payment.covered_charge_ids) != expected_charges
                    or set(payment.covered_extra_ids) != expected_extras
                ):
                    raise ValueError('Payment row coverage must match the item-level payers.')
                continue
            if len(payer_names) > 1:
                payment.covered_charge_ids = [row.id for row in self.charges if row.paid_by.casefold() == key]
                payment.covered_extra_ids = [row.id for row in self.extras if row.paid_by.casefold() == key]
        return self


class DirectedDebtInput(BaseModel):
    debtor: str
    creditor: str
    amount_paise: int = Field(gt=0, le=MAX_SAFE_PAISE)


class SettlementInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    participants: list[str] = Field(min_length=2, max_length=21)
    bills: list[BillInput] = Field(min_length=1, max_length=20)
    debts: list[DirectedDebtInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode='before')
    @classmethod
    def normalize_owner_labels(cls, value):
        """Use the authenticated wallet owner's fixed label throughout the draft."""
        if not isinstance(value, dict) or not isinstance(value.get('participants'), list):
            return value
        value = dict(value)
        participants = [_owner_label(person) for person in value['participants']]
        value['participants'] = ['You', *(person for person in participants if person != 'You')]
        bills = []
        for original_bill in value.get('bills') or []:
            if not isinstance(original_bill, dict):
                bills.append(original_bill)
                continue
            bill = dict(original_bill)
            for field in ('charges', 'extras'):
                rows = []
                for original_row in bill.get(field) or []:
                    if not isinstance(original_row, dict):
                        rows.append(original_row)
                        continue
                    row = dict(original_row)
                    if isinstance(row.get('shared_by'), list):
                        row['shared_by'] = [_owner_label(person) for person in row['shared_by']]
                    if 'paid_by' in row:
                        row['paid_by'] = _owner_label(row['paid_by'])
                    rows.append(row)
                if field in bill:
                    bill[field] = rows
            payments = []
            for original_payment in bill.get('payments') or []:
                if isinstance(original_payment, dict):
                    payment = dict(original_payment)
                    payment['person'] = _owner_label(payment.get('person'))
                    payments.append(payment)
                else:
                    payments.append(original_payment)
            if 'payments' in bill:
                bill['payments'] = payments
            bills.append(bill)
        if 'bills' in value:
            value['bills'] = bills
        debts = []
        for original_debt in value.get('debts') or []:
            if isinstance(original_debt, dict):
                debt = dict(original_debt)
                debt['debtor'] = _owner_label(debt.get('debtor'))
                debt['creditor'] = _owner_label(debt.get('creditor'))
                debts.append(debt)
            else:
                debts.append(original_debt)
        if 'debts' in value:
            value['debts'] = debts
        return value


@dataclass(frozen=True)
class SettlementResult:
    bills: list[dict]
    shares_paise: dict[str, int]
    paid_paise: dict[str, int]
    balances_paise: dict[str, int]
    transfers: list[dict]
    total_paise: int


def _round_rate(amount: int, basis_points: int) -> int:
    return int((Decimal(amount) * Decimal(basis_points) / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _allocate(amount: int, weights: dict[str, int], order: list[str]) -> dict[str, int]:
    if amount < 0 or not weights or sum(weights.values()) <= 0:
        raise ValueError('A charge needs a positive amount and at least one eligible person.')
    denominator = sum(weights.values())
    result = {name: amount * weights[name] // denominator for name in weights}
    remaining = amount - sum(result.values())
    # Largest fractional remainder first; stable participant order breaks ties.
    ordered = sorted(weights, key=lambda name: (-(amount * weights[name] % denominator), order.index(name)))
    for name in ordered[:remaining]:
        result[name] += 1
    return result


def net_transfers(balances: dict[str, int]) -> list[dict]:
    """Settle integer-paise net balances in stable participant order."""
    if sum(balances.values()):
        raise ValueError('Settlement does not balance.')
    people = list(balances)
    debtors = [[name, -amount] for name, amount in balances.items() if amount < 0]
    creditors = [[name, amount] for name, amount in balances.items() if amount > 0]
    debtors.sort(key=lambda row: (-row[1], people.index(row[0])))
    creditors.sort(key=lambda row: (-row[1], people.index(row[0])))
    transfers: list[dict] = []
    d_index = c_index = 0
    while d_index < len(debtors) and c_index < len(creditors):
        amount = min(debtors[d_index][1], creditors[c_index][1])
        transfers.append({'debtor': debtors[d_index][0], 'creditor': creditors[c_index][0],
                          'amount_paise': amount})
        debtors[d_index][1] -= amount
        creditors[c_index][1] -= amount
        if debtors[d_index][1] == 0:
            d_index += 1
        if creditors[c_index][1] == 0:
            c_index += 1
    return transfers


def _apply_discount(
    discount: DiscountInput, bill: BillInput, by_id: dict[str, ChargeInput],
    charge_shares: dict[str, dict[str, int]], discounts_by_charge: dict[str, int],
    bill_shares: dict[str, int], rows: list[dict], people: list[str],
    extra_rows: list[dict] | None = None,
) -> None:
    ids = list(dict.fromkeys(discount.charge_ids))
    if any(charge_id not in by_id for charge_id in ids):
        raise ValueError(f'{bill.merchant}: a discount refers to an unknown charge.')
    included_extras = extra_rows or []
    weights = {person: sum(charge_shares[charge_id].get(person, 0) for charge_id in ids)
               + sum(row['allocations'].get(person, 0) for row in included_extras)
               for person in people}
    weights = {person: amount for person, amount in weights.items() if amount}
    charge_base = sum(by_id[charge_id].amount_paise - discounts_by_charge[charge_id] for charge_id in ids)
    base = charge_base + sum(row['amount_paise'] for row in included_extras)
    amount = discount.amount_paise if discount.amount_paise is not None else _round_rate(base, discount.rate_bps)
    if amount > base:
        raise ValueError(f'{bill.merchant}: discount exceeds its eligible charges and fees.')
    allocations = _allocate(amount, weights, people)
    charge_discount = amount * charge_base // base
    charge_discounts = _allocate(charge_discount, {
        charge_id: by_id[charge_id].amount_paise - discounts_by_charge[charge_id]
        for charge_id in ids if by_id[charge_id].amount_paise > discounts_by_charge[charge_id]
    }, ids) if charge_discount else {}
    for charge_id, discounted in charge_discounts.items():
        discounts_by_charge[charge_id] += discounted
        if discounts_by_charge[charge_id] > by_id[charge_id].amount_paise:
            raise ValueError(f'{bill.merchant}: discounts exceed a charge.')
    for person, share in allocations.items():
        bill_shares[person] -= share
    rows.append({'label': discount.label, 'kind': 'discount', 'amount_paise': -amount,
                 'allocations': {name: -share for name, share in allocations.items()}})


def calculate_complex_settlement(data: SettlementInput) -> SettlementResult:
    """Compute shares and net transfers; never create a transaction or mutate a bill."""
    people = [person.strip() for person in data.participants]
    if not people or people[0].casefold() != 'you':
        raise ValueError('The first participant must be You, the wallet owner.')
    if any(not person or len(person) > 100 for person in people):
        raise ValueError('Every participant needs a name of at most 100 characters.')
    lookup = {person.casefold(): person for person in people}
    if len(lookup) != len(people):
        raise ValueError('Participant names must be distinct.')
    if len({bill.id for bill in data.bills}) != len(data.bills):
        raise ValueError('Bill IDs must be distinct.')

    def members(names: list[str]) -> list[str]:
        resolved = [lookup.get(name.strip().casefold()) for name in names]
        if not resolved or any(name is None for name in resolved) or len(set(resolved)) != len(resolved):
            raise ValueError('Allocate a charge to distinct, named participants.')
        return resolved

    total_shares = dict.fromkeys(people, 0)
    total_paid = dict.fromkeys(people, 0)
    bill_results: list[dict] = []
    for bill in data.bills:
        if len({charge.id for charge in bill.charges}) != len(bill.charges):
            raise ValueError(f'{bill.merchant}: charge IDs must be distinct.')
        extra_ids = [extra.id for extra in bill.extras if extra.id is not None]
        if len(set(extra_ids)) != len(extra_ids):
            raise ValueError(f'{bill.merchant}: fee and tip IDs must be distinct.')
        by_id = {charge.id: charge for charge in bill.charges}
        extra_amounts: dict[str, int] = {}
        charge_shares: dict[str, dict[str, int]] = {}
        discounts_by_charge = dict.fromkeys(by_id, 0)
        bill_shares = dict.fromkeys(people, 0)
        rows: list[dict] = []
        for charge in bill.charges:
            allocated = _allocate(charge.amount_paise, dict.fromkeys(members(charge.shared_by), 1), people)
            charge_shares[charge.id] = allocated
            for person, amount in allocated.items():
                bill_shares[person] += amount
            rows.append({'label': charge.label, 'kind': 'charge', 'amount_paise': charge.amount_paise,
                         'allocations': allocated})
        for discount in bill.discounts:
            if not discount.include_extras:
                _apply_discount(discount, bill, by_id, charge_shares, discounts_by_charge,
                                bill_shares, rows, people)
        for extra in bill.extras:
            if extra.rate_bps is None:
                amount = extra.amount_paise
            elif extra.base_paise is not None:
                amount = _round_rate(extra.base_paise, extra.rate_bps)
            else:
                ids = list(dict.fromkeys(extra.base_charge_ids or []))
                if not ids or any(charge_id not in by_id for charge_id in ids):
                    raise ValueError(f'{bill.merchant}: a percentage fee/tip needs valid base charges.')
                # Coupon savings on the selected charges reduce the fee base.
                gross = sum(by_id[charge_id].amount_paise for charge_id in ids)
                discount_amount = sum(discounts_by_charge[charge_id] for charge_id in ids)
                amount = _round_rate(gross - discount_amount, extra.rate_bps)
            if amount <= 0:
                raise ValueError(f'{bill.merchant}: a fee/tip must be positive after rounding.')
            allocations = _allocate(amount, dict.fromkeys(members(extra.shared_by), 1), people)
            for person, share in allocations.items():
                bill_shares[person] += share
            rows.append({'label': extra.label, 'kind': extra.kind, 'amount_paise': amount,
                         'allocations': allocations})
            if extra.id is not None:
                extra_amounts[extra.id] = amount
        extra_rows = [row for row in rows if row['kind'] in {'fee', 'tip'}]
        for discount in bill.discounts:
            if discount.include_extras:
                _apply_discount(discount, bill, by_id, charge_shares, discounts_by_charge,
                                bill_shares, rows, people, extra_rows)
        bill_total = sum(row['amount_paise'] for row in rows)
        if bill_total > MAX_SAFE_PAISE:
            raise ValueError(f'{bill.merchant}: bill total exceeds the supported amount.')
        if bill.stated_total_paise is not None and bill_total != bill.stated_total_paise:
            raise ValueError(f'{bill.merchant}: calculated charge does not match the stated total.')
        paid = dict.fromkeys(people, 0)
        payment_amounts: list[int] = []
        covered_rows: set[tuple[str, str]] = set()
        for payment in bill.payments:
            person = lookup.get(payment.person.strip().casefold())
            if person is None:
                raise ValueError(f'{bill.merchant}: a payment names an unknown person.')
            charge_ids = payment.covered_charge_ids
            selected_extra_ids = payment.covered_extra_ids
            row_keys = [('charge', row_id) for row_id in charge_ids]
            row_keys.extend(('extra', row_id) for row_id in selected_extra_ids)
            if len(set(row_keys)) != len(row_keys) or covered_rows.intersection(row_keys):
                raise ValueError(f'{bill.merchant}: a payment covers the same row more than once.')
            covered_rows.update(row_keys)
            if any(row_id not in by_id for row_id in charge_ids) or any(
                row_id not in extra_amounts for row_id in selected_extra_ids
            ):
                raise ValueError(f'{bill.merchant}: a payment refers to an unknown item, fee, or tip.')
            if row_keys:
                if any(set(charge_ids).intersection(discount.charge_ids) or (
                    discount.include_extras and selected_extra_ids
                ) for discount in bill.discounts):
                    raise ValueError(f'{bill.merchant}: enter the actual payment when a coupon affects covered rows.')
                amount_paid = sum(by_id[row_id].amount_paise for row_id in charge_ids)
                amount_paid += sum(extra_amounts[row_id] for row_id in selected_extra_ids)
            elif payment.amount_paise is not None:
                amount_paid = payment.amount_paise
            elif len(bill.payments) == 1:
                amount_paid = bill_total
            else:
                raise ValueError(
                    f'{bill.merchant}: specify what {person} paid or the item and tip rows they covered.'
                )
            if amount_paid <= 0:
                raise ValueError(f'{bill.merchant}: a payment must be positive.')
            paid[person] += amount_paid
            payment_amounts.append(amount_paid)
        if sum(paid.values()) != bill_total:
            difference = bill_total - sum(paid.values())
            if difference > 0:
                known = ', '.join(
                    f'{payment.person} ₹{Decimal(amount) / 100:,.2f}'
                    for payment, amount in zip(bill.payments, payment_amounts, strict=True)
                )
                raise ValueError(f'{bill.merchant}: payments must equal the final charge; '
                                 f'known payments are {known}; '
                                 f'₹{Decimal(difference) / 100:,.2f} remains without a payer.')
            raise ValueError(f'{bill.merchant}: payments exceed the final charge by '
                             f'₹{Decimal(-difference) / 100:,.2f}.')
        if any(value < 0 for value in bill_shares.values()):
            raise ValueError(f'{bill.merchant}: a discount gives someone a negative share.')
        for person in people:
            total_shares[person] += bill_shares[person]
            total_paid[person] += paid[person]
        bill_results.append({'id': bill.id, 'merchant': bill.merchant, 'total_paise': bill_total,
                             'shares_paise': bill_shares, 'paid_paise': paid, 'rows': rows,
                             'payment_amounts_paise': payment_amounts})

    balances = {person: total_paid[person] - total_shares[person] for person in people}
    for debt in data.debts:
        debtor = lookup.get(debt.debtor.strip().casefold())
        creditor = lookup.get(debt.creditor.strip().casefold())
        if debtor is None or creditor is None or debtor == creditor:
            raise ValueError('A debt needs two distinct, named people.')
        balances[debtor] -= debt.amount_paise
        balances[creditor] += debt.amount_paise
    if sum(balances.values()) or sum(total_shares.values()) != sum(bill['total_paise'] for bill in bill_results):
        raise ValueError('Settlement does not balance.')
    if sum(bill['total_paise'] for bill in bill_results) > MAX_SAFE_PAISE or any(
        abs(balance) > MAX_SAFE_PAISE for balance in balances.values()
    ):
        raise ValueError('Settlement total exceeds the supported amount.')
    transfers = net_transfers(balances)
    return SettlementResult(bill_results, total_shares, total_paid, balances, transfers,
                            sum(bill['total_paise'] for bill in bill_results))
