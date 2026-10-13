from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ChatMessageModel,
    ExportArtifactModel,
    GuardrailLogModel,
    UserModel,
)
from app.infrastructure.jobs import run_retention_cleanup_once


async def test_run_retention_cleanup_once_removes_expired_and_old_records(db_session: AsyncSession) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    user_id = uuid.uuid4()

    db_session.add(
        UserModel(
            id=user_id,
            email='retention-jobs@example.com',
            name='Retention Jobs',
            date_of_birth=None,
            hashed_password='hashed',
            google_sub=None,
            conversation_storage_enabled=True,
        )
    )

    db_session.add_all(
        [
            GuardrailLogModel(
                id=uuid.uuid4(),
                user_id=user_id,
                thread_id='retention-thread-1',
                message='old guardrail',
                intent='query_spending',
                confidence=0.8,
                triggered=False,
                layer='semantic',
                expires_at=now - timedelta(days=1),
                created_at=now - timedelta(days=2),
            ),
            GuardrailLogModel(
                id=uuid.uuid4(),
                user_id=user_id,
                thread_id='retention-thread-2',
                message='fresh guardrail',
                intent='query_spending',
                confidence=0.9,
                triggered=False,
                layer='semantic',
                expires_at=now + timedelta(days=1),
                created_at=now,
            ),
            ExportArtifactModel(
                id=uuid.uuid4(),
                user_id=user_id,
                format='pdf',
                download_url='https://example.com/old.pdf',
                expires_at=now - timedelta(hours=1),
                created_at=now - timedelta(days=1),
            ),
            ExportArtifactModel(
                id=uuid.uuid4(),
                user_id=user_id,
                format='xlsx',
                download_url='https://example.com/new.xlsx',
                expires_at=now + timedelta(hours=1),
                created_at=now,
            ),
            ChatMessageModel(
                id=uuid.uuid4(),
                user_id=user_id,
                thread_id='retention-thread-1',
                role='user',
                content='old message',
                created_at=now - timedelta(days=95),
            ),
            ChatMessageModel(
                id=uuid.uuid4(),
                user_id=user_id,
                thread_id='retention-thread-1',
                role='assistant',
                content='recent message',
                created_at=now - timedelta(days=2),
            ),
        ]
    )
    await db_session.commit()

    cleanup_stats = await run_retention_cleanup_once(db_session, now=now, chat_message_retention_days=30)

    assert cleanup_stats == {
        'deleted_guardrail_logs': 1,
        'deleted_exports': 1,
        'deleted_old_messages': 1,
    }

    remaining_guardrail_logs = (await db_session.execute(select(GuardrailLogModel))).scalars().all()
    remaining_exports = (await db_session.execute(select(ExportArtifactModel))).scalars().all()
    remaining_messages = (await db_session.execute(select(ChatMessageModel))).scalars().all()

    assert len(remaining_guardrail_logs) == 1
    assert len(remaining_exports) == 1
    assert len(remaining_messages) == 1
    assert remaining_messages[0].content == 'recent message'
