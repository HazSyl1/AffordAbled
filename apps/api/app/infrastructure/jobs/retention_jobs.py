from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ChatMessageModel, ExportArtifactModel, GuardrailLogModel


async def run_retention_cleanup_once(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    chat_message_retention_days: int = 180,
) -> dict[str, int]:
    cleanup_now = now or datetime.now(UTC)
    retention_days = max(1, int(chat_message_retention_days))
    message_cutoff = cleanup_now - timedelta(days=retention_days)

    deleted_guardrail_logs = await session.execute(
        delete(GuardrailLogModel).where(GuardrailLogModel.expires_at <= cleanup_now)
    )
    deleted_exports = await session.execute(
        delete(ExportArtifactModel).where(ExportArtifactModel.expires_at <= cleanup_now)
    )
    deleted_old_messages = await session.execute(
        delete(ChatMessageModel).where(ChatMessageModel.created_at <= message_cutoff)
    )

    await session.commit()
    return {
        'deleted_guardrail_logs': deleted_guardrail_logs.rowcount or 0,
        'deleted_exports': deleted_exports.rowcount or 0,
        'deleted_old_messages': deleted_old_messages.rowcount or 0,
    }
