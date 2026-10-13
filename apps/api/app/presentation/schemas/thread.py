from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from app.domain.entities import ChatMessage, ChatThread


class CreateThreadRequest(BaseModel):
    thread_id: str | None = Field(default=None, min_length=1, max_length=120)
    title: str | None = Field(default=None, min_length=1, max_length=160)


class ThreadMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime

    @classmethod
    def from_entity(cls, message: ChatMessage) -> Self:
        return cls(
            id=str(message.id),
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )


class ThreadResponse(BaseModel):
    thread_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    @classmethod
    def from_entity(cls, thread: ChatThread, *, message_count: int = 0) -> Self:
        return cls(
            thread_id=thread.thread_id,
            title=thread.title,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            message_count=message_count,
        )


class ThreadDetailResponse(BaseModel):
    thread: ThreadResponse
    messages: list[ThreadMessageResponse]
