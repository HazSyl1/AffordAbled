from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TransactionType(str, Enum):
    EXPENSE = 'expense'
    INCOME = 'income'
    TRANSFER = 'transfer'
    REFUND = 'refund'


@dataclass
class Transaction:
    id: uuid.UUID
    user_id: uuid.UUID
    account_id: uuid.UUID
    to_account_id: uuid.UUID | None
    category_id: uuid.UUID | None
    type: TransactionType
    amount_paise: int
    merchant: str | None
    note: str | None
    occurred_at: datetime
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
