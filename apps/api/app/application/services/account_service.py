from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.dto import CreateAccountInput, UpdateAccountInput
from app.domain.entities import Account
from app.domain.exceptions import AccountNotFoundError
from app.domain.repositories import AccountRepository


@dataclass
class AccountService:
    account_repository: AccountRepository

    async def create_account(self, data: CreateAccountInput) -> Account:
        now = datetime.now(UTC)
        account = Account(
            id=uuid.uuid4(),
            user_id=data.user_id,
            name=data.name,
            type=data.type,
            balance_paise=data.balance_paise,
            currency=data.currency,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        return await self.account_repository.create(account)

    async def list_accounts(self, user_id: uuid.UUID) -> list[Account]:
        return await self.account_repository.list_for_user(user_id)

    async def get_account(self, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
        account = await self.account_repository.get_for_user(account_id, user_id)
        if account is None:
            raise AccountNotFoundError(str(account_id))
        return account

    async def update_account(self, user_id: uuid.UUID, account_id: uuid.UUID, data: UpdateAccountInput) -> Account:
        account = await self.get_account(user_id, account_id)
        if data.name is not None:
            account.name = data.name
        if data.is_active is not None:
            account.is_active = data.is_active
        account.updated_at = datetime.now(UTC)
        return await self.account_repository.update(account)
