from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ChatTurnJobModel


class ChatTurnConflictError(ValueError):
    pass


class SqlAlchemyChatTurnJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get(
        self,
        *,
        turn_id: uuid.UUID,
        user_id: uuid.UUID,
        thread_id: str,
        message: str,
        timezone: str,
    ) -> ChatTurnJobModel:
        existing = await self.get_for_user(user_id, turn_id)
        if existing is not None:
            if (
                existing.thread_id != thread_id
                or existing.message != message
                or existing.timezone != timezone
            ):
                raise ChatTurnConflictError('turn_id was already used for different input') from None
            return existing

        model = ChatTurnJobModel(
            id=turn_id,
            user_id=user_id,
            thread_id=thread_id,
            message=message,
            timezone=timezone,
            status='queued',
        )
        self._session.add(model)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self.get_for_user(user_id, turn_id)
            if existing is None:
                raise
            if (
                existing.thread_id != thread_id
                or existing.message != message
                or existing.timezone != timezone
            ):
                raise ChatTurnConflictError('turn_id was already used for different input') from None
            return existing
        await self._session.refresh(model)
        return model

    async def get_for_user(self, user_id: uuid.UUID, turn_id: uuid.UUID) -> ChatTurnJobModel | None:
        return await self._session.scalar(
            select(ChatTurnJobModel).where(
                ChatTurnJobModel.id == turn_id,
                ChatTurnJobModel.user_id == user_id,
            )
        )

    async def get(self, turn_id: uuid.UUID) -> ChatTurnJobModel | None:
        return await self._session.get(ChatTurnJobModel, turn_id)

    async def claim_next(self, *, stale_after_seconds: int, max_attempts: int) -> ChatTurnJobModel | None:
        now = datetime.now(UTC)
        stale_at = now - timedelta(seconds=max(1, stale_after_seconds))
        query = (
            select(ChatTurnJobModel)
            .where(
                ChatTurnJobModel.attempts < max(1, max_attempts),
                or_(
                    ChatTurnJobModel.status == 'queued',
                    (ChatTurnJobModel.status == 'processing') & (ChatTurnJobModel.claimed_at <= stale_at),
                ),
            )
            .order_by(ChatTurnJobModel.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = await self._session.scalar(query)
        if job is None:
            return None
        job.status = 'processing'
        job.claimed_at = now
        job.attempts += 1
        job.error_code = None
        job.error_message = None
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            return None
        await self._session.refresh(job)
        return job

    async def mark_succeeded(self, turn_id: uuid.UUID, result: dict[str, Any]) -> None:
        job = await self.get(turn_id)
        if job is None:
            return
        job.status = 'succeeded'
        job.result_json = result
        job.error_code = None
        job.error_message = None
        job.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def mark_failed(self, turn_id: uuid.UUID, *, error_code: str, error_message: str) -> None:
        job = await self.get(turn_id)
        if job is None:
            return
        job.status = 'failed'
        job.error_code = error_code[:80]
        job.error_message = error_message[:600]
        job.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def release_for_retry(self, turn_id: uuid.UUID, *, error_code: str, error_message: str) -> None:
        job = await self.get(turn_id)
        if job is None:
            return
        job.status = 'queued'
        job.error_code = error_code[:80]
        job.error_message = error_message[:600]
        job.claimed_at = None
        await self._session.commit()
