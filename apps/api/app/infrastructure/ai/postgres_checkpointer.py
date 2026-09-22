from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ports import ChatCheckpointMessage
from app.infrastructure.database.models import CheckpointModel


class LangGraphPostgresCheckpointer:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_messages(self, *, user_id: uuid.UUID, thread_id: str) -> list[ChatCheckpointMessage]:
        result = await self._session.execute(
            select(CheckpointModel).where(
                CheckpointModel.user_id == user_id,
                CheckpointModel.thread_id == thread_id,
            )
        )
        checkpoint = result.scalar_one_or_none()
        if checkpoint is None:
            return []

        try:
            payload = json.loads(checkpoint.state_json)
        except json.JSONDecodeError:
            return []

        if not isinstance(payload, list):
            return []

        messages: list[ChatCheckpointMessage] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            role = str(item.get('role') or '').strip()
            content = str(item.get('content') or '').strip()
            if role and content:
                messages.append(ChatCheckpointMessage(role=role, content=content))
        return messages

    async def save_messages(
        self,
        *,
        user_id: uuid.UUID,
        thread_id: str,
        messages: list[ChatCheckpointMessage],
    ) -> None:
        result = await self._session.execute(
            select(CheckpointModel).where(
                CheckpointModel.user_id == user_id,
                CheckpointModel.thread_id == thread_id,
            )
        )
        checkpoint = result.scalar_one_or_none()

        serialized_messages = json.dumps(
            [{'role': message.role, 'content': message.content} for message in messages],
            ensure_ascii=False,
        )
        now = datetime.now(UTC)

        if checkpoint is None:
            checkpoint = CheckpointModel(
                id=uuid.uuid4(),
                user_id=user_id,
                thread_id=thread_id,
                state_json=serialized_messages,
                created_at=now,
                updated_at=now,
            )
            self._session.add(checkpoint)
        else:
            checkpoint.state_json = serialized_messages
            checkpoint.updated_at = now

        await self._session.commit()
