from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from app.domain.entities import Account, AccountType


class CreateAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    balance_paise: int = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)


class UpdateAccountRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class AccountResponse(BaseModel):
    id: str
    name: str
    type: AccountType
    balance_paise: int
    currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, account: Account) -> Self:
        return cls(
            id=str(account.id),
            name=account.name,
            type=account.type,
            balance_paise=account.balance_paise,
            currency=account.currency,
            is_active=account.is_active,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
