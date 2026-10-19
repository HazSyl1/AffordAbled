from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.dto import CreateChatThreadInput
from app.domain.entities import ChatMessage, ChatThread
from app.domain.exceptions import ChatThreadAlreadyExistsError, ChatThreadNotFoundError
from app.domain.repositories import ChatMessageRepository, ChatThreadRepository


@dataclass
class ChatThreadDetail:
    thread: ChatThread
    messages: list[ChatMessage]


@dataclass
class ThreadService:
    chat_thread_repository: ChatThreadRepository
    chat_message_repository: ChatMessageRepository

    async def create_thread(self, data: CreateChatThreadInput) -> ChatThread:
        resolved_thread_id = (data.thread_id or '').strip() or str(uuid.uuid4())
        existing = await self.chat_thread_repository.get_for_user(data.user_id, resolved_thread_id)
        if existing is not None:
            raise ChatThreadAlreadyExistsError(f'Thread already exists: {resolved_thread_id}')

        now = datetime.now(UTC)
        thread = ChatThread(
            id=uuid.uuid4(),
            user_id=data.user_id,
            thread_id=resolved_thread_id,
            title=data.title,
            created_at=now,
            updated_at=now,
        )
        return await self.chat_thread_repository.create(thread)

    async def list_threads(self, user_id: uuid.UUID) -> list[ChatThread]:
        return await self.chat_thread_repository.list_for_user(user_id)

    async def get_thread(self, user_id: uuid.UUID, thread_id: str) -> ChatThreadDetail:
        thread = await self.chat_thread_repository.get_for_user(user_id, thread_id)
        if thread is None:
            raise ChatThreadNotFoundError(f'Thread not found: {thread_id}')

        messages = await self.chat_message_repository.list_for_user_thread(user_id, thread_id)
        return ChatThreadDetail(thread=thread, messages=messages)

    async def get_or_create_transaction_thread(
        self, user_id: uuid.UUID, transaction_id: uuid.UUID, title: str, thread_id: str | None = None,
    ) -> ChatThreadDetail:
        thread = await self.chat_thread_repository.get_for_user_transaction(user_id, transaction_id)
        if thread is None and thread_id:
            thread = await self.chat_thread_repository.link_transaction_for_user(
                user_id, thread_id, transaction_id, title,
            )
        if thread is None:
            now = datetime.now(UTC)
            thread = await self.chat_thread_repository.create(ChatThread(
                id=uuid.uuid4(), user_id=user_id, thread_id=thread_id or str(uuid.uuid4()),
                title=title, created_at=now, updated_at=now, transaction_id=transaction_id,
            ))
        messages = await self.chat_message_repository.list_for_user_thread(user_id, thread.thread_id)
        return ChatThreadDetail(thread=thread, messages=messages)

    async def delete_thread(self, user_id: uuid.UUID, thread_id: str) -> None:
        exists = await self.chat_thread_repository.get_for_user(user_id, thread_id)
        if exists is None:
            raise ChatThreadNotFoundError(f'Thread not found: {thread_id}')

        await self.chat_message_repository.delete_for_user_thread(user_id, thread_id)
        await self.chat_thread_repository.delete_for_user(user_id, thread_id)
