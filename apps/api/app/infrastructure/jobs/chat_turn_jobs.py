from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.infrastructure.database.models import ChatTurnJobModel
from app.infrastructure.database.repositories.sqlalchemy_chat_turn_job_repository import (
    SqlAlchemyChatTurnJobRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_user_usage_repository import SqlAlchemyUserUsageRepository
from app.infrastructure.database.session import SessionLocal

logger = logging.getLogger(__name__)

ChatTurnProcessor = Callable[[ChatTurnJobModel], Awaitable[dict[str, Any]]]


async def run_chat_turn_once(
    processor: ChatTurnProcessor,
    *,
    stale_after_seconds: int = 120,
    max_attempts: int = 3,
    session_factory=SessionLocal,
) -> bool:
    async with session_factory() as session:
        repository = SqlAlchemyChatTurnJobRepository(session)
        job = await repository.claim_next(
            stale_after_seconds=stale_after_seconds,
            max_attempts=max_attempts,
        )
    if job is None:
        return False

    try:
        result = await processor(job)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - durable worker boundary
        logger.exception('chat.turn.failed', extra={'turn_id': str(job.id), 'attempt': job.attempts})
        async with session_factory() as session:
            repository = SqlAlchemyChatTurnJobRepository(session)
            if job.attempts >= max(1, max_attempts):
                await repository.mark_failed(
                    job.id,
                    error_code='processing_failed',
                    error_message='The assistant could not process this turn.',
                )
                # A turn that never produced an answer must not use up the user's daily allowance.
                await SqlAlchemyUserUsageRepository(session).remove(job.user_id, 'chat_turn', f'turn:{job.id}')
            else:
                await repository.release_for_retry(
                    job.id,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
        return True

    async with session_factory() as session:
        await SqlAlchemyChatTurnJobRepository(session).mark_succeeded(job.id, result)
    logger.info('chat.turn.succeeded', extra={'turn_id': str(job.id), 'attempt': job.attempts})
    return True


async def run_chat_turn_loop(
    processor: ChatTurnProcessor,
    *,
    poll_interval_seconds: int = 2,
    stale_after_seconds: int = 120,
    max_attempts: int = 3,
    session_factory=SessionLocal,
) -> None:
    while True:
        processed = await run_chat_turn_once(
            processor,
            stale_after_seconds=stale_after_seconds,
            max_attempts=max_attempts,
            session_factory=session_factory,
        )
        if not processed:
            await asyncio.sleep(max(1, poll_interval_seconds))
