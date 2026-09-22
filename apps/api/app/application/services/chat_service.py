from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.exceptions import InvalidChatInputError
from app.domain.ports import ChatCheckpointMessage, ConversationCheckpointer


@dataclass
class ChatResponseOutput:
    thread_id: str
    message: str


@dataclass
class ChatService:
    checkpointer: ConversationCheckpointer

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

        messages = await self.checkpointer.load_messages(user_id=user_id, thread_id=resolved_thread_id)
        previous_user_messages = [item.content for item in messages if item.role == 'user']

        if previous_user_messages:
            assistant_message = (
                f'Got it. You said: "{normalized_message}". '
                f'Earlier you mentioned: "{previous_user_messages[-1]}".'
            )
        else:
            assistant_message = f'Got it. You said: "{normalized_message}".'

        updated_messages = [
            *messages,
            ChatCheckpointMessage(role='user', content=normalized_message),
            ChatCheckpointMessage(role='assistant', content=assistant_message),
        ]
        await self.checkpointer.save_messages(
            user_id=user_id,
            thread_id=resolved_thread_id,
            messages=updated_messages,
        )

        return ChatResponseOutput(thread_id=resolved_thread_id, message=assistant_message)

