from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import UserTier
from app.infrastructure.database.models import UserModel, UserUsageEventModel


def utc_day_window(now: datetime) -> tuple[datetime, datetime]:
    current = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


class SqlAlchemyUserUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tier_for_user(self, user_id: uuid.UUID, *, lock: bool = False) -> UserTier:
        query = select(UserModel.account_tier).where(UserModel.id == user_id)
        if lock:
            query = query.with_for_update()
        value = await self._session.scalar(query)
        if value is None:
            raise LookupError('User not found.')
        return UserTier(value)

    async def count(self, user_id: uuid.UUID, metric: str, *, now: datetime) -> int:
        start, end = utc_day_window(now)
        return int(await self._session.scalar(
            select(func.coalesce(func.sum(UserUsageEventModel.quantity), 0)).where(
                UserUsageEventModel.user_id == user_id,
                UserUsageEventModel.metric == metric,
                UserUsageEventModel.created_at >= start,
                UserUsageEventModel.created_at < end,
            )
        ) or 0)

    async def get_by_key(self, user_id: uuid.UUID, metric: str, key: str) -> UserUsageEventModel | None:
        return await self._session.scalar(select(UserUsageEventModel).where(
            UserUsageEventModel.user_id == user_id,
            UserUsageEventModel.metric == metric,
            UserUsageEventModel.idempotency_key == key,
        ))

    async def add(
        self, user_id: uuid.UUID, metric: str, key: str, quantity: int, *, now: datetime, commit: bool,
    ) -> UserUsageEventModel:
        event = UserUsageEventModel(
            id=uuid.uuid4(), user_id=user_id, metric=metric, idempotency_key=key,
            quantity=quantity, created_at=now,
        )
        self._session.add(event)
        await self._session.flush()
        if commit:
            await self._session.commit()
            await self._session.refresh(event)
        return event

    async def remove(self, user_id: uuid.UUID, metric: str, key: str) -> None:
        await self._session.execute(delete(UserUsageEventModel).where(
            UserUsageEventModel.user_id == user_id,
            UserUsageEventModel.metric == metric,
            UserUsageEventModel.idempotency_key == key,
        ))
        await self._session.commit()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
