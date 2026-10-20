from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuantityAllocation:
    people: list[str]
    quantity_per_person: int
    unit_price_paise: int


def calculate_quantity_split(
    total_paise: int,
    participant_names: list[str],
    allocations: list[QuantityAllocation],
) -> tuple[int, dict[str, int], int]:
    """Add priced quantities to named shares, then divide the balance with the owner."""
    if total_paise <= 0 or not participant_names or not allocations:
        raise ValueError('A positive expense, participants, and priced quantities are required.')
    names = {name.casefold(): name for name in participant_names}
    if len(names) != len(participant_names):
        raise ValueError('Split participants must be distinct.')
    fixed = {name: 0 for name in names}
    for allocation in allocations:
        if not 1 <= allocation.quantity_per_person <= 1000 or allocation.unit_price_paise <= 0:
            raise ValueError('Use a positive quantity and unit price for each priced item.')
        if not allocation.people or len({name.casefold() for name in allocation.people}) != len(allocation.people):
            raise ValueError('Each priced item needs distinct people.')
        for person in allocation.people:
            key = person.casefold()
            if key not in names:
                raise ValueError(f'{person} is not a split participant.')
            fixed[key] += allocation.quantity_per_person * allocation.unit_price_paise
    remainder = total_paise - sum(fixed.values())
    if remainder < 0:
        raise ValueError('Priced items exceed the recorded transaction total.')
    base, extra_paise = divmod(remainder, len(names) + 1)
    # Give leftover paise to the owner first, then participants in supplied order.
    owner_share = base + (extra_paise > 0)
    shares = {
        name: fixed[name.casefold()] + base + (index + 1 < extra_paise)
        for index, name in enumerate(participant_names)
    }
    assert owner_share + sum(shares.values()) == total_paise
    return owner_share, shares, remainder
