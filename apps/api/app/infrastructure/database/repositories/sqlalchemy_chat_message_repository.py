from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import ChatMessage
from app.infrastructure.database.models import ChatMessageModel


class SqlAlchemyChatMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, chat_message: ChatMessage) -> ChatMessage:
        model = ChatMessageModel(
            id=chat_message.id,
            user_id=chat_message.user_id,
            thread_id=chat_message.thread_id,
            role=chat_message.role,
            content=chat_message.content,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def list_for_user_thread(self, user_id: uuid.UUID, thread_id: str) -> list[ChatMessage]:
        result = await self._session.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.user_id == user_id, ChatMessageModel.thread_id == thread_id)
            .order_by(ChatMessageModel.created_at)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def delete_for_user_thread(self, user_id: uuid.UUID, thread_id: str) -> int:
        result = await self._session.execute(
            delete(ChatMessageModel).where(ChatMessageModel.user_id == user_id, ChatMessageModel.thread_id == thread_id)
        )
        await self._session.commit()
        return result.rowcount or 0

    @staticmethod
    def _to_entity(model: ChatMessageModel) -> ChatMessage:
        return ChatMessage(
            id=model.id,
            user_id=model.user_id,
            thread_id=model.thread_id,
            role=model.role,
            content=model.content,
            created_at=model.created_at,
        )
