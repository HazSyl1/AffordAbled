from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Account, AccountType
from app.infrastructure.database.models import AccountModel


class SqlAlchemyAccountRepository:
    """Every query is scoped by user_id — this is the enforcement point for
    per-user data isolation at the persistence layer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, account: Account) -> Account:
        model = AccountModel(
            id=account.id,
            user_id=account.user_id,
            name=account.name,
            type=account.type.value,
            balance_paise=account.balance_paise,
            currency=account.currency,
            is_active=account.is_active,
            is_default=account.is_default,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def get_for_user(self, account_id: uuid.UUID, user_id: uuid.UUID) -> Account | None:
        result = await self._session.execute(
            select(AccountModel).where(AccountModel.id == account_id, AccountModel.user_id == user_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_for_user(self, user_id: uuid.UUID) -> list[Account]:
        result = await self._session.execute(
            select(AccountModel).where(AccountModel.user_id == user_id).order_by(AccountModel.created_at)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, account: Account) -> Account:
        model = await self._session.get(AccountModel, account.id)
        if model is None or model.user_id != account.user_id:
            raise LookupError(str(account.id))
        model.name = account.name
        model.type = account.type.value
        model.balance_paise = account.balance_paise
        model.currency = account.currency
        model.is_active = account.is_active
        model.is_default = account.is_default
        model.updated_at = account.updated_at
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def set_default_for_user(self, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
        account = await self.get_for_user(account_id, user_id)
        if account is None:
            raise LookupError(str(account_id))
        if not account.is_active:
            raise ValueError('An inactive account cannot be the default account.')

        await self._session.execute(
            update(AccountModel)
            .where(AccountModel.user_id == user_id, AccountModel.is_default.is_(True))
            .values(is_default=False)
        )
        await self._session.execute(
            update(AccountModel)
            .where(AccountModel.id == account_id, AccountModel.user_id == user_id)
            .values(is_default=True)
        )
        await self._session.commit()
        updated_account = await self.get_for_user(account_id, user_id)
        if updated_account is None:
            raise LookupError(str(account_id))
        return updated_account

    @staticmethod
    def _to_entity(model: AccountModel) -> Account:
        return Account(
            id=model.id,
            user_id=model.user_id,
            name=model.name,
            type=AccountType(model.type),
            balance_paise=model.balance_paise,
            currency=model.currency,
            is_active=model.is_active,
            is_default=model.is_default,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
