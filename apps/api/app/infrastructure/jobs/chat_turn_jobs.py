from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.infrastructure.chat_turn_scheduler_signal import (
    clear_chat_turn_scheduler_wakeup,
    install_chat_turn_scheduler_wakeup,
    publish_chat_turn_status,
)
from app.infrastructure.database.models import ChatTurnJobModel
from app.infrastructure.database.repositories.sqlalchemy_chat_turn_job_repository import (
    SqlAlchemyChatTurnJobRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_user_usage_repository import SqlAlchemyUserUsageRepository
from app.infrastructure.database.session import SessionLocal

logger = logging.getLogger(__name__)

ChatTurnProcessor = Callable[[ChatTurnJobModel], Awaitable[dict[str, Any]]]


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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

    queue_wait_ms = round((datetime.now(UTC) - _as_utc(job.created_at)).total_seconds() * 1000, 2)
    logger.info('chat.turn.claimed', extra={
        'turn_id': str(job.id), 'attempt': job.attempts, 'queue_wait_ms': max(0, queue_wait_ms),
    })
    publish_chat_turn_status(str(job.id))
    processing_started = perf_counter()

    try:
        result = await processor(job)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - durable worker boundary
        logger.exception('chat.turn.failed', extra={
            'turn_id': str(job.id), 'attempt': job.attempts,
            'processing_ms': round((perf_counter() - processing_started) * 1000, 2),
        })
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
        publish_chat_turn_status(str(job.id))
        return True

    async with session_factory() as session:
        await SqlAlchemyChatTurnJobRepository(session).mark_succeeded(job.id, result)
    publish_chat_turn_status(str(job.id))
    logger.info('chat.turn.succeeded', extra={
        'turn_id': str(job.id), 'attempt': job.attempts,
        'processing_ms': round((perf_counter() - processing_started) * 1000, 2),
    })
    return True


async def run_chat_turn_loop(
    processor: ChatTurnProcessor,
    *,
    poll_interval_seconds: int = 2,
    stale_after_seconds: int = 120,
    max_attempts: int = 3,
    session_factory=SessionLocal,
) -> None:
    wakeup = asyncio.Event()
    install_chat_turn_scheduler_wakeup(wakeup)
    try:
        while True:
            wakeup.clear()
            processed = await run_chat_turn_once(
                processor,
                stale_after_seconds=stale_after_seconds,
                max_attempts=max_attempts,
                session_factory=session_factory,
            )
            if processed:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(wakeup.wait(), timeout=max(1, poll_interval_seconds))
            except TimeoutError:
                pass
    finally:
        clear_chat_turn_scheduler_wakeup(wakeup)
