from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.application.name_formatting import capitalize_name

_OWNER_PARTICIPANT_LABELS = {'me', 'myself', 'self', 'you', 'owner', 'my share'}


def is_owner_participant_label(name: str | None) -> bool:
    """Owner shares are represented separately and must never be split contacts."""
    return ' '.join((name or '').strip().casefold().split()) in _OWNER_PARTICIPANT_LABELS


@dataclass(frozen=True)
class ParticipantShare:
    name: str
    share_paise: int


@dataclass(frozen=True)
class ParticipantEditShare:
    id: uuid.UUID | None
    name: str
    share_paise: int


class SplitStore(Protocol):
    async def create(
        self, user_id: uuid.UUID, transaction_id: uuid.UUID, title: str,
        owner_share_paise: int, participants: list[ParticipantShare], item_breakdown: list[dict] | None = None,
        settlement_breakdown: dict | None = None,
    ): ...

    async def create_owed(self, user_id: uuid.UUID, title: str, person: ParticipantShare): ...

    async def list_for_user(self, user_id: uuid.UUID): ...

    async def get_for_user(self, user_id: uuid.UUID, split_id: uuid.UUID): ...

    async def update(
        self, user_id: uuid.UUID, split_id: uuid.UUID, title: str,
        owner_share_paise: int, participants: list[ParticipantEditShare],
    ): ...

    async def settle(
        self, user_id: uuid.UUID, split_id: uuid.UUID,
        participant_id: uuid.UUID, repayment_transaction_id: uuid.UUID,
    ): ...

    async def repay(
        self, user_id: uuid.UUID, split_id: uuid.UUID,
        participant_id: uuid.UUID, account_id: uuid.UUID,
    ): ...

    async def repay_settlement_transfer(
        self, user_id: uuid.UUID, split_id: uuid.UUID, debtor: str, account_id: uuid.UUID,
    ): ...

    async def delete(self, user_id: uuid.UUID, split_id: uuid.UUID) -> bool: ...

    async def contact_names(self, user_id: uuid.UUID) -> list[str]: ...

    async def list_contact_preferences(self, user_id: uuid.UUID): ...

    async def contact_preference_suggestions(self, user_id: uuid.UUID) -> list[dict]: ...

    async def set_contact_preference(self, user_id: uuid.UUID, name: str, dietary_preference: str | None): ...

    async def delete_contact_preference(self, user_id: uuid.UUID, contact_id: uuid.UUID) -> bool: ...


class MemoryEventWriter(Protocol):
    async def add_review_event(self, **kwargs): ...


@dataclass
class SplitService:
    store: SplitStore
    memory_event_writer: MemoryEventWriter | None = None

    async def create_owed(self, user_id: uuid.UUID, title: str | None, name: str, amount_paise: int):
        clean_title = (title or '').strip() or 'Money owed'
        clean_name = capitalize_name(name)
        if len(clean_title) > 255:
            raise ValueError('Enter a description (up to 255 characters).')
        if not clean_name or len(clean_name) > 100 or is_owner_participant_label(clean_name):
            raise ValueError('Enter the name of the person who owes you.')
        if amount_paise <= 0:
            raise ValueError('Amount owed must be positive.')
        return await self.store.create_owed(
            user_id, clean_title, ParticipantShare(clean_name, amount_paise),
        )

    async def create(
        self, user_id: uuid.UUID, transaction_id: uuid.UUID, title: str, amount_paise: int,
        mode: str, participants: list[ParticipantShare], owner_share_paise: int | None,
        item_breakdown: list[dict] | None = None, settlement_breakdown: dict | None = None,
    ):
        clean_title = title.strip()
        if not clean_title or len(clean_title) > 255:
            raise ValueError('Enter a split title (up to 255 characters).')
        if amount_paise <= 0:
            raise ValueError('Split amount must be positive.')
        if not 1 <= len(participants) <= 20:
            raise ValueError('Add between 1 and 20 people.')
        names = [capitalize_name(person.name) for person in participants]
        if any(is_owner_participant_label(name) for name in names):
            raise ValueError('Your share is tracked separately. Do not add yourself as a split participant.')
        if any(not name or len(name) > 100 for name in names) or len({name.casefold() for name in names}) != len(names):
            raise ValueError('Participant names must be unique and between 1 and 100 characters.')
        if mode == 'equal':
            base, remainder = divmod(amount_paise, len(participants) + 1)
            if base <= 0:
                raise ValueError('Amount is too small to divide between everyone.')
            owner_share_paise = base + remainder
            shares = [ParticipantShare(name, base) for name in names]
        elif mode == 'custom':
            if owner_share_paise is None or owner_share_paise < 0:
                raise ValueError('Enter your share for a custom split.')
            shares = [
                ParticipantShare(name, person.share_paise)
                for name, person in zip(names, participants, strict=True)
            ]
            if any(person.share_paise <= 0 for person in shares):
                raise ValueError('Each person must have a positive share.')
            if owner_share_paise + sum(person.share_paise for person in shares) != amount_paise:
                raise ValueError('Shares must add up to the expense amount exactly.')
        else:
            raise ValueError('Split mode must be equal or custom.')
        if self.memory_event_writer is not None:
            await self.memory_event_writer.add_review_event(
                user_id=user_id,
                split_id=None,
                action='accepted',
                source='split_review',
                before={},
                after={
                    'mode': mode,
                    'participants': [
                        {
                            'name': person.name,
                            'share_ratio': round(person.share_paise / amount_paise, 6),
                        }
                        for person in shares
                    ],
                },
                transaction_id=transaction_id,
            )
        if settlement_breakdown is None:
            return await self.store.create(
                user_id, transaction_id, clean_title, owner_share_paise, shares, item_breakdown,
            )
        return await self.store.create(
            user_id, transaction_id, clean_title, owner_share_paise, shares, item_breakdown, settlement_breakdown,
        )

    async def list_for_user(self, user_id: uuid.UUID):
        return await self.store.list_for_user(user_id)

    async def get_for_user(self, user_id: uuid.UUID, split_id: uuid.UUID):
        return await self.store.get_for_user(user_id, split_id)

    async def update(
        self, user_id: uuid.UUID, split_id: uuid.UUID, title: str,
        owner_share_paise: int, participants: list[ParticipantEditShare],
    ):
        clean_title = title.strip()
        if not clean_title or len(clean_title) > 255:
            raise ValueError('Enter a split title (up to 255 characters).')
        if owner_share_paise < 0:
            raise ValueError('Your share cannot be negative.')
        if not 1 <= len(participants) <= 20:
            raise ValueError('Add between 1 and 20 people.')
        names = [capitalize_name(person.name) for person in participants]
        if any(is_owner_participant_label(name) for name in names):
            raise ValueError('Your share is tracked separately. Do not add yourself as a split participant.')
        if any(not name or len(name) > 100 for name in names) or len({name.casefold() for name in names}) != len(names):
            raise ValueError('Participant names must be unique and between 1 and 100 characters.')
        if any(person.share_paise <= 0 for person in participants):
            raise ValueError('Each person must have a positive share.')
        ids = [person.id for person in participants if person.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError('Each existing person may only appear once.')
        cleaned = [ParticipantEditShare(person.id, name, person.share_paise)
                   for person, name in zip(participants, names, strict=True)]
        if self.memory_event_writer is not None:
            existing = await self.store.get_for_user(user_id, split_id)
            before = {
                'participants': [
                    {'name': person.name, 'share_ratio': round(person.share_paise / (owner_share_paise + sum(
                        item.share_paise for item in participants
                    )), 6)}
                    for person in (existing.participants if existing else [])
                ],
            }
            await self.memory_event_writer.add_review_event(
                user_id=user_id, split_id=split_id, action='edited', source='split_review',
                before=before,
                after={
                    'mode': 'custom',
                    'participants': [
                        {'name': person.name, 'share_ratio': round(person.share_paise / (
                            owner_share_paise + sum(item.share_paise for item in participants)
                        ), 6)}
                        for person in cleaned
                    ],
                },
            )
        return await self.store.update(user_id, split_id, clean_title, owner_share_paise, cleaned)

    async def settle(
        self, user_id: uuid.UUID, split_id: uuid.UUID,
        participant_id: uuid.UUID, repayment_transaction_id: uuid.UUID,
    ):
        return await self.store.settle(user_id, split_id, participant_id, repayment_transaction_id)

    async def repay(
        self, user_id: uuid.UUID, split_id: uuid.UUID,
        participant_id: uuid.UUID, account_id: uuid.UUID,
    ):
        return await self.store.repay(user_id, split_id, participant_id, account_id)

    async def repay_settlement_transfer(
        self, user_id: uuid.UUID, split_id: uuid.UUID, debtor: str, account_id: uuid.UUID,
    ):
        return await self.store.repay_settlement_transfer(user_id, split_id, debtor, account_id)

    async def delete(self, user_id: uuid.UUID, split_id: uuid.UUID) -> bool:
        return await self.store.delete(user_id, split_id)

    async def contact_names(self, user_id: uuid.UUID) -> list[str]:
        return await self.store.contact_names(user_id)

    async def list_contact_preferences(self, user_id: uuid.UUID):
        return await self.store.list_contact_preferences(user_id)

    async def contact_preference_suggestions(self, user_id: uuid.UUID) -> list[dict]:
        return await self.store.contact_preference_suggestions(user_id)

    async def set_contact_preference(self, user_id: uuid.UUID, name: str, dietary_preference: str | None):
        return await self.store.set_contact_preference(user_id, capitalize_name(name), dietary_preference)

    async def delete_contact_preference(self, user_id: uuid.UUID, contact_id: uuid.UUID) -> bool:
        return await self.store.delete_contact_preference(user_id, contact_id)
