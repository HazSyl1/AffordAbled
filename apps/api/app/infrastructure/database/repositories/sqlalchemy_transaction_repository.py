from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Transaction, TransactionType
from app.infrastructure.database.models import TransactionModel


class SqlAlchemyTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, transaction: Transaction) -> Transaction:
        model = TransactionModel(
            id=transaction.id,
            user_id=transaction.user_id,
            account_id=transaction.account_id,
            to_account_id=transaction.to_account_id,
            category_id=transaction.category_id,
            type=transaction.type.value,
            amount_paise=transaction.amount_paise,
            merchant=transaction.merchant,
            note=transaction.note,
            occurred_at=transaction.occurred_at,
            deleted_at=transaction.deleted_at,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def get_for_user(
        self,
        transaction_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> Transaction | None:
        query = select(TransactionModel).where(
            TransactionModel.id == transaction_id,
            TransactionModel.user_id == user_id,
        )
        if not include_deleted:
            query = query.where(TransactionModel.deleted_at.is_(None))

        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_for_user(self, user_id: uuid.UUID, *, include_deleted: bool = False) -> list[Transaction]:
        query = select(TransactionModel).where(TransactionModel.user_id == user_id)
        if not include_deleted:
            query = query.where(TransactionModel.deleted_at.is_(None))

        result = await self._session.execute(query.order_by(TransactionModel.occurred_at.desc()))
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, transaction: Transaction) -> Transaction:
        model = await self._session.get(TransactionModel, transaction.id)
        if model is None or model.user_id != transaction.user_id:
            raise LookupError(str(transaction.id))

        model.account_id = transaction.account_id
        model.to_account_id = transaction.to_account_id
        model.category_id = transaction.category_id
        model.type = transaction.type.value
        model.amount_paise = transaction.amount_paise
        model.merchant = transaction.merchant
        model.note = transaction.note
        model.occurred_at = transaction.occurred_at
        model.deleted_at = transaction.deleted_at
        model.updated_at = transaction.updated_at

        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def soft_delete_for_user(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        now = datetime.now(UTC)
        result = await self._session.execute(
            update(TransactionModel)
            .where(
                TransactionModel.id == transaction_id,
                TransactionModel.user_id == user_id,
                TransactionModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )
        await self._session.commit()
        return (result.rowcount or 0) > 0

    async def restore_for_user(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        now = datetime.now(UTC)
        result = await self._session.execute(
            update(TransactionModel)
            .where(
                TransactionModel.id == transaction_id,
                TransactionModel.user_id == user_id,
                TransactionModel.deleted_at.is_not(None),
            )
            .values(deleted_at=None, updated_at=now)
        )
        await self._session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def _to_entity(model: TransactionModel) -> Transaction:
        return Transaction(
            id=model.id,
            user_id=model.user_id,
            account_id=model.account_id,
            to_account_id=model.to_account_id,
            category_id=model.category_id,
            type=TransactionType(model.type),
            amount_paise=model.amount_paise,
            merchant=model.merchant,
            note=model.note,
            occurred_at=model.occurred_at,
            deleted_at=model.deleted_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
