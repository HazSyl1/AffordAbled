from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.dto import CreateAccountInput, UpdateAccountInput
from app.application.name_formatting import capitalize_name
from app.domain.entities import Account
from app.domain.exceptions import AccountNotFoundError
from app.domain.repositories import AccountRepository


@dataclass
class AccountService:
    account_repository: AccountRepository

    async def create_account(self, data: CreateAccountInput) -> Account:
        now = datetime.now(UTC)
        existing_accounts = await self.account_repository.list_for_user(data.user_id)
        is_default = not any(account.is_default for account in existing_accounts)
        account = Account(
            id=uuid.uuid4(),
            user_id=data.user_id,
            name=capitalize_name(data.name),
            type=data.type,
            balance_paise=data.balance_paise,
            currency=data.currency,
            is_active=True,
            is_default=is_default,
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
        was_default = account.is_default
        if data.name is not None:
            account.name = capitalize_name(data.name)
        if data.is_active is not None:
            account.is_active = data.is_active
            if not data.is_active and was_default:
                account.is_default = False
        account.updated_at = datetime.now(UTC)
        updated_account = await self.account_repository.update(account)

        if was_default and not updated_account.is_active:
            replacement = next(
                (
                    candidate
                    for candidate in await self.account_repository.list_for_user(user_id)
                    if candidate.is_active
                ),
                None,
            )
            if replacement is not None:
                await self.account_repository.set_default_for_user(user_id, replacement.id)
        elif updated_account.is_active and not any(
            candidate.is_default for candidate in await self.account_repository.list_for_user(user_id)
        ):
            updated_account = await self.account_repository.set_default_for_user(user_id, account_id)

        return updated_account

    async def set_default_account(self, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
        account = await self.get_account(user_id, account_id)
        if not account.is_active:
            raise ValueError('An inactive account cannot be the default account.')
        return await self.account_repository.set_default_for_user(user_id, account_id)
