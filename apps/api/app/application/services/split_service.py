from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


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
        owner_share_paise: int, participants: list[ParticipantShare],
    ): ...

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

    async def delete(self, user_id: uuid.UUID, split_id: uuid.UUID) -> bool: ...

    async def contact_names(self, user_id: uuid.UUID) -> list[str]: ...


@dataclass
class SplitService:
    store: SplitStore

    async def create(
        self, user_id: uuid.UUID, transaction_id: uuid.UUID, title: str, amount_paise: int,
        mode: str, participants: list[ParticipantShare], owner_share_paise: int | None,
    ):
        clean_title = title.strip()
        if not clean_title or len(clean_title) > 255:
            raise ValueError('Enter a split title (up to 255 characters).')
        if amount_paise <= 0:
            raise ValueError('Split amount must be positive.')
        if not 1 <= len(participants) <= 20:
            raise ValueError('Add between 1 and 20 people.')
        names = [person.name.strip() for person in participants]
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
        return await self.store.create(user_id, transaction_id, clean_title, owner_share_paise, shares)

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
        names = [person.name.strip() for person in participants]
        if any(not name or len(name) > 100 for name in names) or len({name.casefold() for name in names}) != len(names):
            raise ValueError('Participant names must be unique and between 1 and 100 characters.')
        if any(person.share_paise <= 0 for person in participants):
            raise ValueError('Each person must have a positive share.')
        ids = [person.id for person in participants if person.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError('Each existing person may only appear once.')
        cleaned = [ParticipantEditShare(person.id, name, person.share_paise)
                   for person, name in zip(participants, names, strict=True)]
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

    async def delete(self, user_id: uuid.UUID, split_id: uuid.UUID) -> bool:
        return await self.store.delete(user_id, split_id)

    async def contact_names(self, user_id: uuid.UUID) -> list[str]:
        return await self.store.contact_names(user_id)
