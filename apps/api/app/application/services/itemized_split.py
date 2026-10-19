from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemAllocation:
    name: str
    amount_paise: int
    shared_by: list[str]
    food_type: str = 'unknown'
    owner_excluded: bool = False


@dataclass(frozen=True)
class ItemizedSplitCalculation:
    owner_share_paise: int
    participant_shares: dict[str, int]
    items: list[dict]
    warnings: list[str]


def _format_paise(amount_paise: int) -> str:
    rupees, paise = divmod(abs(amount_paise), 100)
    sign = '-' if amount_paise < 0 else ''
    return f'₹{sign}{rupees:,}.{paise:02d}'


def calculate_itemized_split(
    total_paise: int,
    participant_names: list[str],
    items: list[ItemAllocation],
    preferences: dict[str, str] | None = None,
) -> ItemizedSplitCalculation:
    """Allocate verified receipt rows in paise; `me` identifies the transaction owner."""
    if total_paise <= 0 or not items or len(items) > 100:
        raise ValueError('Add between 1 and 100 receipt items for a positive expense.')
    if not 1 <= len(participant_names) <= 20:
        raise ValueError('Add between 1 and 20 people to the itemized split.')
    normalized = [name.strip().casefold() for name in participant_names]
    if any(not name or len(name) > 100 or name in {'me', 'you'} for name in normalized):
        raise ValueError('Use distinct participant names other than me or you.')
    if len(set(normalized)) != len(normalized):
        raise ValueError('Participant names must be unique.')
    names = dict(zip(normalized, (name.strip() for name in participant_names), strict=True))
    shares = {'me': 0, **{name: 0 for name in normalized}}
    rendered_items: list[dict] = []
    warnings: list[str] = []
    item_total_paise = sum(item.amount_paise for item in items)
    if item_total_paise != total_paise:
        difference_paise = abs(total_paise - item_total_paise)
        difference_rupees = _format_paise(difference_paise)
        if item_total_paise < total_paise:
            raise ValueError(
                f'Receipt rows total {_format_paise(item_total_paise)}, but the expense total is '
                f'{_format_paise(total_paise)}. Add the missing {difference_rupees} as a tax, fee, or round-off '
                'shared-charge row, then allocate it among the people who shared the expense.'
            )
        raise ValueError(
            f'Receipt rows total {_format_paise(item_total_paise)}, which exceeds the expense total '
            f'{_format_paise(total_paise)} by {difference_rupees}. Correct the item amounts before splitting.'
        )
    for item in items:
        label = item.name.strip()
        if not label or len(label) > 255 or item.amount_paise <= 0:
            raise ValueError('Every receipt item needs a name and positive amount.')
        if item.food_type not in {'vegetarian', 'vegan', 'contains_meat', 'unknown', 'shared_charge'}:
            raise ValueError('Unsupported receipt item food type.')
        members = [name.strip().casefold() for name in item.shared_by]
        members = ['me' if name == 'you' else name for name in members]
        if item.owner_excluded and 'me' in members:
            raise ValueError(f'The owner cannot be both included and excluded from {label}.')
        if not item.owner_excluded and 'me' not in members:
            # The payer is part of a shared item by default. The AI must not
            # silently assign the owner a zero share just because it omitted "me".
            members.append('me')
        if not members or len(set(members)) != len(members) or any(name not in shares for name in members):
            raise ValueError(f'Choose valid, distinct people for {label}.')
        ordered = sorted(members, key=lambda name: (name != 'me', name))
        base, remainder = divmod(item.amount_paise, len(ordered))
        allocation = {name: base + (index < remainder) for index, name in enumerate(ordered)}
        for name, amount in allocation.items():
            shares[name] += amount
            if item.food_type == 'contains_meat' and (preferences or {}).get(name) in {'vegetarian', 'vegan'}:
                warnings.append(f'{names[name]} is marked vegetarian or vegan but is assigned {label}.')
            if item.food_type == 'vegetarian' and (preferences or {}).get(name) == 'vegan':
                warnings.append(f'Check whether {label} is vegan before assigning it to {names[name]}.')
            if item.food_type == 'unknown' and (preferences or {}).get(name) in {'vegetarian', 'vegan'}:
                warnings.append(f'Check the ingredients in {label} before assigning it to {names[name]}.')
        rendered_items.append({
            'name': label,
            'amount_paise': item.amount_paise,
            'food_type': item.food_type,
            'allocations': [{'person': 'me' if name == 'me' else names[name], 'amount_paise': amount}
                            for name, amount in allocation.items()],
        })
    if any(shares[name] <= 0 for name in normalized):
        raise ValueError('Each added person must have a positive share.')
    return ItemizedSplitCalculation(
        owner_share_paise=shares['me'],
        participant_shares={names[name]: shares[name] for name in normalized},
        items=rendered_items,
        warnings=warnings,
    )
