from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import ChatThread
from app.infrastructure.database.models import ChatThreadModel


class SqlAlchemyChatThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, chat_thread: ChatThread) -> ChatThread:
        model = ChatThreadModel(
            id=chat_thread.id,
            user_id=chat_thread.user_id,
            thread_id=chat_thread.thread_id,
            title=chat_thread.title,
            transaction_id=chat_thread.transaction_id,
        )
        self._session.add(model)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            if chat_thread.transaction_id is None:
                raise
            existing = await self.get_for_user_transaction(chat_thread.user_id, chat_thread.transaction_id)
            if existing is None:
                raise
            return existing
        await self._session.refresh(model)
        return self._to_entity(model)

    async def get_for_user(self, user_id: uuid.UUID, thread_id: str) -> ChatThread | None:
        result = await self._session.execute(
            select(ChatThreadModel).where(ChatThreadModel.user_id == user_id, ChatThreadModel.thread_id == thread_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_for_user_transaction(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> ChatThread | None:
        result = await self._session.execute(
            select(ChatThreadModel).where(
                ChatThreadModel.user_id == user_id,
                ChatThreadModel.transaction_id == transaction_id,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def link_transaction_for_user(
        self, user_id: uuid.UUID, thread_id: str, transaction_id: uuid.UUID, title: str,
    ) -> ChatThread | None:
        result = await self._session.execute(
            select(ChatThreadModel).where(ChatThreadModel.user_id == user_id, ChatThreadModel.thread_id == thread_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.transaction_id = transaction_id
        model.title = title
        model.updated_at = datetime.now(UTC)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self.get_for_user_transaction(user_id, transaction_id)
            if existing is None:
                raise
            return existing
        await self._session.refresh(model)
        return self._to_entity(model)

    async def list_for_user(self, user_id: uuid.UUID) -> list[ChatThread]:
        result = await self._session.execute(
            select(ChatThreadModel)
            .where(ChatThreadModel.user_id == user_id)
            .order_by(ChatThreadModel.updated_at.desc(), ChatThreadModel.created_at.desc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def touch_for_user(self, user_id: uuid.UUID, thread_id: str) -> None:
        result = await self._session.execute(
            select(ChatThreadModel).where(ChatThreadModel.user_id == user_id, ChatThreadModel.thread_id == thread_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.updated_at = datetime.now(UTC)
        await self._session.commit()

    async def delete_for_user(self, user_id: uuid.UUID, thread_id: str) -> bool:
        result = await self._session.execute(
            delete(ChatThreadModel).where(ChatThreadModel.user_id == user_id, ChatThreadModel.thread_id == thread_id)
        )
        await self._session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def _to_entity(model: ChatThreadModel) -> ChatThread:
        return ChatThread(
            id=model.id,
            user_id=model.user_id,
            thread_id=model.thread_id,
            title=model.title,
            transaction_id=model.transaction_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
