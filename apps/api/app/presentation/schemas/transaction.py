from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from app.domain.entities import Transaction, TransactionType


class CreateTransactionRequest(BaseModel):
    account_id: uuid.UUID
    type: TransactionType
    amount_paise: int = Field(gt=0)
    occurred_at: datetime
    category_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = None


class UpdateTransactionRequest(BaseModel):
    account_id: uuid.UUID | None = None
    type: TransactionType | None = None
    amount_paise: int | None = Field(default=None, gt=0)
    occurred_at: datetime | None = None
    category_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = None


class TransactionResponse(BaseModel):
    id: str
    account_id: str
    to_account_id: str | None
    category_id: str | None
    type: TransactionType
    amount_paise: int
    merchant: str | None
    note: str | None
    occurred_at: datetime
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, transaction: Transaction) -> Self:
        return cls(
            id=str(transaction.id),
            account_id=str(transaction.account_id),
            to_account_id=str(transaction.to_account_id) if transaction.to_account_id is not None else None,
            category_id=str(transaction.category_id) if transaction.category_id is not None else None,
            type=transaction.type,
            amount_paise=transaction.amount_paise,
            merchant=transaction.merchant,
            note=transaction.note,
            occurred_at=transaction.occurred_at,
            deleted_at=transaction.deleted_at,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
        )
