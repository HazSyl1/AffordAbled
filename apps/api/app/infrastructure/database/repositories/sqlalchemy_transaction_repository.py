from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
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
        # TransactionService may stage related durable outbox work in this
        # session. Flush makes the transaction visible to FK-backed outbox rows;
        # the service owns the single commit for both records.
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def commit(self) -> None:
        await self._session.commit()

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

    async def list_for_export(
        self, user_id: uuid.UUID, *, date_from: datetime | None, date_to: datetime | None, limit: int
    ) -> list[Transaction]:
        filters = [TransactionModel.user_id == user_id, TransactionModel.deleted_at.is_(None)]
        if date_from is not None:
            filters.append(TransactionModel.occurred_at >= date_from)
        if date_to is not None:
            filters.append(TransactionModel.occurred_at < date_to)
        result = await self._session.execute(
            select(TransactionModel)
            .where(*filters)
            .order_by(
                TransactionModel.occurred_at.desc(),
                TransactionModel.created_at.desc(),
                TransactionModel.id.desc(),
            )
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def existing_ids_for_user(self, user_id: uuid.UUID, ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not ids:
            return set()
        result = await self._session.execute(
            select(TransactionModel.id).where(TransactionModel.user_id == user_id, TransactionModel.id.in_(ids))
        )
        return set(result.scalars().all())

    async def list_recent_for_user(self, user_id: uuid.UUID, *, limit: int) -> list[Transaction]:
        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.user_id == user_id, TransactionModel.deleted_at.is_(None))
            .order_by(
                TransactionModel.occurred_at.desc(), TransactionModel.created_at.desc(), TransactionModel.id.desc()
            )
            .limit(max(1, min(limit, 5)))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_for_user_window(
        self,
        user_id: uuid.UUID,
        *,
        date_from: datetime,
        date_to: datetime,
        limit: int,
        offset: int = 0,
        transaction_type: TransactionType | None = None,
        category_id: uuid.UUID | None = None,
        account_id: uuid.UUID | None = None,
        order_by: str = "occurred_at",
        sort_order: str = "desc",
    ) -> tuple[list[Transaction], int]:
        filters = [
            TransactionModel.user_id == user_id,
            TransactionModel.deleted_at.is_(None),
            TransactionModel.occurred_at >= date_from,
            TransactionModel.occurred_at <= date_to,
        ]
        if transaction_type is not None:
            filters.append(TransactionModel.type == transaction_type.value)
        if category_id is not None:
            filters.append(TransactionModel.category_id == category_id)
        if account_id is not None:
            filters.append(TransactionModel.account_id == account_id)
        count_result = await self._session.execute(select(func.count()).select_from(TransactionModel).where(*filters))
        total_count = int(count_result.scalar_one())
        primary_order = TransactionModel.amount_paise if order_by == "amount" else TransactionModel.occurred_at
        primary_order = primary_order.asc() if sort_order == "asc" else primary_order.desc()
        result = await self._session.execute(
            select(TransactionModel)
            .where(*filters)
            .order_by(
                primary_order,
                TransactionModel.occurred_at.desc(),
                TransactionModel.created_at.desc(),
                TransactionModel.id.desc(),
            )
            .offset(max(0, offset))
            .limit(max(1, min(limit, 100)))
        )
        return [self._to_entity(model) for model in result.scalars().all()], total_count

    async def spending_summary_for_user(
        self, user_id: uuid.UUID, *, date_from: datetime, date_to: datetime, category_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        filters = [
            TransactionModel.user_id == user_id,
            TransactionModel.deleted_at.is_(None),
            TransactionModel.type == TransactionType.EXPENSE.value,
            TransactionModel.occurred_at >= date_from,
            TransactionModel.occurred_at <= date_to,
        ]
        if category_id is not None:
            filters.append(TransactionModel.category_id == category_id)
        totals = await self._session.execute(
            select(func.coalesce(func.sum(TransactionModel.amount_paise), 0), func.count())
            .where(*filters)
        )
        total_spent_paise, transaction_count = totals.one()
        grouped = await self._session.execute(
            select(TransactionModel.category_id, func.sum(TransactionModel.amount_paise))
            .where(*filters)
            .group_by(TransactionModel.category_id)
            .order_by(func.sum(TransactionModel.amount_paise).desc())
        )
        return {
            "total_spent_paise": int(total_spent_paise or 0),
            "transaction_count": int(transaction_count),
            "by_category": [(category_id, int(amount or 0)) for category_id, amount in grouped.all()],
        }

    async def spending_by_account_for_user(
        self, user_id: uuid.UUID, *, date_from: datetime, date_to: datetime, category_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        filters = [
            TransactionModel.user_id == user_id,
            TransactionModel.deleted_at.is_(None),
            TransactionModel.type == TransactionType.EXPENSE.value,
            TransactionModel.occurred_at >= date_from,
            TransactionModel.occurred_at <= date_to,
        ]
        if category_id is not None:
            filters.append(TransactionModel.category_id == category_id)
        result = await self._session.execute(
            select(
                TransactionModel.account_id,
                func.sum(TransactionModel.amount_paise).label("total_spent_paise"),
                func.count().label("transaction_count"),
            )
            .where(*filters)
            .group_by(TransactionModel.account_id)
            .order_by(func.sum(TransactionModel.amount_paise).desc())
        )
        return [
            {
                "account_id": account_id,
                "total_spent_paise": int(total or 0),
                "transaction_count": int(count),
            }
            for account_id, total, count in result.all()
        ]

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
