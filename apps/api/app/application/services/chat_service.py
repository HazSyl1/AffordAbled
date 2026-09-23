from __future__ import annotations

import uuid
from dataclasses import dataclass

from langsmith import traceable

from app.domain.exceptions import InvalidChatInputError
from app.domain.ports import ChatOrchestrator


@dataclass
class ChatResponseOutput:
    thread_id: str
    message: str


@dataclass
class ChatService:
    orchestrator: ChatOrchestrator

    @traceable(name='chat_service.send_message', run_type='chain')
    async def send_message(
        self,
        *,
        user_id: uuid.UUID,
        message: str,
        thread_id: str | None = None,
    ) -> ChatResponseOutput:
        normalized_message = message.strip()
        if not normalized_message:
            raise InvalidChatInputError('Message cannot be empty')

        resolved_thread_id = (thread_id or '').strip() or str(uuid.uuid4())
        assistant_message = await self.orchestrator.run_turn(
            user_id=user_id,
            thread_id=resolved_thread_id,
            message=normalized_message,
        )

        return ChatResponseOutput(thread_id=resolved_thread_id, message=assistant_message)
