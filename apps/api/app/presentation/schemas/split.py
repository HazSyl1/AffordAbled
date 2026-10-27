from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.infrastructure.database.models.split import SplitModel


class ParticipantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    share_paise: int = Field(default=0, ge=0)


class CreateSplitRequest(BaseModel):
    transaction_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    amount_paise: int = Field(gt=0)
    mode: Literal['equal', 'custom']
    owner_share_paise: int | None = Field(default=None, ge=0)
    participants: list[ParticipantRequest] = Field(min_length=1, max_length=20)


class CreateOwedRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    name: str = Field(min_length=1, max_length=100)
    amount_paise: int = Field(gt=0)
    direction: Literal['to_you', 'by_you'] = 'to_you'


class UpdateParticipantRequest(BaseModel):
    id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    share_paise: int = Field(gt=0)


class UpdateSplitRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    owner_share_paise: int = Field(ge=0)
    participants: list[UpdateParticipantRequest] = Field(min_length=1, max_length=20)


class ParticipantResponse(BaseModel):
    id: uuid.UUID
    name: str
    share_paise: int
    settled_paise: int
    repayment_transaction_id: uuid.UUID | None


class SettleParticipantRequest(BaseModel):
    repayment_transaction_id: uuid.UUID


class RepayParticipantRequest(BaseModel):
    account_id: uuid.UUID


class PayOwedRequest(BaseModel):
    account_id: uuid.UUID


class RepaySettlementTransferRequest(BaseModel):
    debtor: str = Field(min_length=1, max_length=100)
    account_id: uuid.UUID


class SplitContactPreferenceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dietary_preference: Literal['vegetarian', 'vegan', 'omnivore'] | None = None


class SplitContactPreferenceResponse(BaseModel):
    id: uuid.UUID
    name: str
    dietary_preference: Literal['vegetarian', 'vegan', 'omnivore'] | None
    preference_confirmed_at: datetime | None


class ItemAllocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    amount_paise: int = Field(gt=0)
    shared_by: list[str] = Field(default_factory=list, max_length=21)
    food_type: Literal['vegetarian', 'vegan', 'contains_meat', 'unknown', 'shared_charge'] = 'unknown'
    owner_excluded: bool = False


class ItemizedSplitRequest(BaseModel):
    transaction_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    amount_paise: int = Field(gt=0)
    participants: list[str] = Field(min_length=1, max_length=20)
    items: list[ItemAllocationRequest] = Field(min_length=1, max_length=100)
    confirmed: bool = False
    approve_warnings: bool = False


class ItemizedSplitPreviewResponse(BaseModel):
    owner_share_paise: int
    participant_shares: dict[str, int]
    items: list[dict]
    warnings: list[str]


class SplitResponse(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID | None
    kind: Literal['expense_split', 'money_owed']
    direction: Literal['to_you', 'by_you']
    title: str
    owner_share_paise: int
    total_paise: int
    outstanding_paise: int
    created_at: datetime
    participants: list[ParticipantResponse]
    item_breakdown: list[dict] | None = None
    settlement_breakdown: dict | None = None

    @classmethod
    def from_model(cls, split: SplitModel) -> SplitResponse:
        people = sorted(split.participants, key=lambda person: person.name.casefold())
        return cls(
            id=split.id,
            transaction_id=split.transaction_id,
            kind='expense_split' if split.transaction_id else 'money_owed',
            direction='to_you' if split.transaction_id else split.direction,
            title=split.title,
            owner_share_paise=split.owner_share_paise,
            total_paise=split.owner_share_paise + sum(person.share_paise for person in people),
            outstanding_paise=(
                sum(
                    int(transfer.get('amount_paise') or 0)
                    for transfer in (split.settlement_breakdown or {}).get('transfers', [])
                    if transfer.get('creditor') == 'You' and not transfer.get('repayment_transaction_id')
                )
                if split.settlement_breakdown is not None
                else sum(person.share_paise - person.settled_paise for person in people)
            ),
            created_at=split.created_at,
            participants=[
                ParticipantResponse(
                    id=person.id, name=person.name,
                    share_paise=person.share_paise, settled_paise=person.settled_paise,
                    repayment_transaction_id=person.repayment_transaction_id,
                ) for person in people
            ],
            item_breakdown=split.item_breakdown,
            settlement_breakdown=split.settlement_breakdown,
        )
