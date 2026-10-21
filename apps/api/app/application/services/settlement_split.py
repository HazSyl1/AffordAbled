from __future__ import annotations

from dataclasses import dataclass

from app.application.services.quantity_split import QuantityAllocation


@dataclass(frozen=True)
class SettlementDebt:
    debtor: str
    creditor: str
    amount_paise: int


@dataclass(frozen=True)
class SplitContribution:
    person: str
    amount_paise: int


@dataclass(frozen=True)
class SettlementTransfer:
    debtor: str
    creditor: str
    amount_paise: int


@dataclass(frozen=True)
class SettlementSplitCalculation:
    owner_share_paise: int
    participant_shares: dict[str, int]
    priced_items_paise: int
    remainder_paise: int
    transfers: list[SettlementTransfer]
    contributions: list[SplitContribution]
    debts: list[SettlementDebt]


def calculate_settlement_split(
    total_paise: int,
    participant_names: list[str],
    allocations: list[QuantityAllocation],
    contributions: list[SplitContribution],
    debts: list[SettlementDebt],
) -> SettlementSplitCalculation:
    """Calculate expense shares and a separate net who-pays-whom plan using integer paise."""
    if total_paise <= 0 or not participant_names:
        raise ValueError('A positive expense and at least one named participant are required.')
    if any(name.strip().casefold() in {'me', 'myself', 'self', 'you', 'owner', 'my share'}
           for name in participant_names):
        raise ValueError('The owner is not an external participant; track the owner share separately.')
    canonical_names = ['You', *participant_names]
    names = {name.casefold(): name for name in canonical_names}
    if len(names) != len(canonical_names):
        raise ValueError('Split participants must be distinct and must not include the owner.')
    names.update({'me': 'You', 'myself': 'You', 'self': 'You', 'you': 'You', 'owner': 'You', 'my share': 'You'})

    fixed = {name: 0 for name in canonical_names}
    for allocation in allocations:
        if (
            isinstance(allocation.quantity_per_person, bool)
            or not isinstance(allocation.quantity_per_person, int)
            or not 1 <= allocation.quantity_per_person <= 1000
            or isinstance(allocation.unit_price_paise, bool)
            or not isinstance(allocation.unit_price_paise, int)
            or allocation.unit_price_paise <= 0
        ):
            raise ValueError('Use a positive quantity and unit price for each priced item.')
        if not allocation.people or len({person.casefold() for person in allocation.people}) != len(allocation.people):
            raise ValueError('Each priced allocation needs distinct people.')
        for person in allocation.people:
            canonical = names.get(person.casefold())
            if canonical is None or canonical == 'You':
                raise ValueError(f'{person} is not a named split participant.')
            fixed[canonical] += allocation.quantity_per_person * allocation.unit_price_paise

    priced_total = sum(fixed.values())
    remainder = total_paise - priced_total
    if remainder < 0:
        raise ValueError('Priced items exceed the recorded transaction total.')

    # Remainder is shared by everyone, including the owner. Leftover paise are assigned
    # deterministically in participant order, with the owner first.
    base, extra_paise = divmod(remainder, len(canonical_names))
    shares = {
        person: fixed[person] + base + (index < extra_paise)
        for index, person in enumerate(canonical_names)
    }

    paid = {person: 0 for person in canonical_names}
    normalized_contributions: list[SplitContribution] = []
    contribution_total = 0
    for contribution in contributions:
        canonical = names.get(contribution.person.casefold())
        if canonical is None or canonical == 'You':
            raise ValueError('Contributions must name a split participant, not the owner.')
        if (
            isinstance(contribution.amount_paise, bool)
            or not isinstance(contribution.amount_paise, int)
            or contribution.amount_paise <= 0
        ):
            raise ValueError('Each contribution must be a positive amount in paise.')
        paid[canonical] += contribution.amount_paise
        contribution_total += contribution.amount_paise
        normalized_contributions.append(SplitContribution(canonical, contribution.amount_paise))
    if contribution_total > total_paise:
        raise ValueError('Participant contributions cannot exceed the transaction total.')
    paid['You'] = total_paise - contribution_total

    balances = {person: paid[person] - shares[person] for person in canonical_names}
    normalized_debts: list[SettlementDebt] = []
    for debt in debts:
        debtor = names.get(debt.debtor.casefold())
        creditor = names.get(debt.creditor.casefold())
        if debtor is None or creditor is None:
            raise ValueError('Every debt must name the owner or a listed split participant.')
        if debtor == creditor:
            raise ValueError('A person cannot owe money to themselves.')
        if isinstance(debt.amount_paise, bool) or not isinstance(debt.amount_paise, int) or debt.amount_paise <= 0:
            raise ValueError('Each debt must be a positive amount in paise.')
        balances[debtor] -= debt.amount_paise
        balances[creditor] += debt.amount_paise
        normalized_debts.append(SettlementDebt(debtor, creditor, debt.amount_paise))

    if sum(shares.values()) != total_paise or sum(balances.values()) != 0:
        raise ValueError('The calculated split does not balance to the transaction total.')

    debtors = [[-balance, person] for person, balance in balances.items() if balance < 0]
    creditors = [[balance, person] for person, balance in balances.items() if balance > 0]
    debtors.sort(key=lambda entry: (-entry[0], entry[1].casefold()))
    creditors.sort(key=lambda entry: (-entry[0], entry[1].casefold()))
    transfers: list[SettlementTransfer] = []
    debtor_index = creditor_index = 0
    while debtor_index < len(debtors) and creditor_index < len(creditors):
        amount = min(debtors[debtor_index][0], creditors[creditor_index][0])
        transfers.append(SettlementTransfer(
            debtor=debtors[debtor_index][1],
            creditor=creditors[creditor_index][1],
            amount_paise=amount,
        ))
        debtors[debtor_index][0] -= amount
        creditors[creditor_index][0] -= amount
        if debtors[debtor_index][0] == 0:
            debtor_index += 1
        if creditors[creditor_index][0] == 0:
            creditor_index += 1

    if debtor_index != len(debtors) or creditor_index != len(creditors):
        raise ValueError('Could not settle all participant balances exactly.')

    return SettlementSplitCalculation(
        owner_share_paise=shares['You'],
        participant_shares={person: shares[person] for person in participant_names},
        priced_items_paise=priced_total,
        remainder_paise=remainder,
        transfers=transfers,
        contributions=normalized_contributions,
        debts=normalized_debts,
    )
