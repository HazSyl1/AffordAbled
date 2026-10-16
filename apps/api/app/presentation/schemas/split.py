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


class SplitResponse(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    title: str
    owner_share_paise: int
    total_paise: int
    outstanding_paise: int
    created_at: datetime
    participants: list[ParticipantResponse]

    @classmethod
    def from_model(cls, split: SplitModel) -> SplitResponse:
        people = sorted(split.participants, key=lambda person: person.name.casefold())
        return cls(
            id=split.id,
            transaction_id=split.transaction_id,
            title=split.title,
            owner_share_paise=split.owner_share_paise,
            total_paise=split.owner_share_paise + sum(person.share_paise for person in people),
            outstanding_paise=sum(person.share_paise - person.settled_paise for person in people),
            created_at=split.created_at,
            participants=[
                ParticipantResponse(
                    id=person.id, name=person.name,
                    share_paise=person.share_paise, settled_paise=person.settled_paise,
                    repayment_transaction_id=person.repayment_transaction_id,
                ) for person in people
            ],
        )
