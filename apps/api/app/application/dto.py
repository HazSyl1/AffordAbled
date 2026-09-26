from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.entities import AccountType, CategoryType, TransactionType


@dataclass
class RegisterUserInput:
    email: str
    name: str
    date_of_birth: date
    password: str


@dataclass
class LoginInput:
    email: str
    password: str


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'


@dataclass
class CreateAccountInput:
    user_id: uuid.UUID
    name: str
    type: AccountType
    balance_paise: int
    currency: str = 'INR'


@dataclass
class UpdateAccountInput:
    name: str | None = None
    is_active: bool | None = None


@dataclass
class CreateCategoryInput:
    user_id: uuid.UUID
    name: str
    type: CategoryType
    icon: str | None = None
    color: str | None = None


@dataclass
class UpdateCategoryInput:
    name: str | None = None
    type: CategoryType | None = None
    icon: str | None = None
    color: str | None = None


@dataclass
class CreateTransactionInput:
    user_id: uuid.UUID
    account_id: uuid.UUID
    type: TransactionType
    amount_paise: int
    occurred_at: datetime
    category_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    merchant: str | None = None
    note: str | None = None


@dataclass
class UpdateTransactionInput:
    account_id: uuid.UUID | None = None
    type: TransactionType | None = None
    amount_paise: int | None = None
    occurred_at: datetime | None = None
    category_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    merchant: str | None = None
    note: str | None = None
