from __future__ import annotations

import asyncio
import logging

from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository
from app.infrastructure.database.session import SessionLocal

logger = logging.getLogger(__name__)


async def run_memory_outbox_once(*, batch_size: int = 20) -> dict[str, int]:
    async with SessionLocal() as session:
        repository = SqlAlchemyMemoryRepository(session)
        rows = await repository.claim_batch(limit=batch_size)
        row_ids = [row.id for row in rows]

    processed = 0
    failed = 0
    for row_id in row_ids:
        async with SessionLocal() as session:
            repository = SqlAlchemyMemoryRepository(session)
            try:
                await repository.process_event(row_id)
                processed += 1
            except Exception as error:  # noqa: BLE001 - retryable worker boundary
                await session.rollback()
                await repository.fail(row_id, str(error))
                failed += 1
                logger.exception('memory.outbox.event_failed', extra={'outbox_id': str(row_id)})
    return {'claimed': len(row_ids), 'processed': processed, 'failed': failed}


async def run_memory_outbox_loop(*, poll_interval_seconds: int = 5, batch_size: int = 20) -> None:
    while True:
        try:
            stats = await run_memory_outbox_once(batch_size=batch_size)
            if stats['claimed']:
                logger.info('memory.outbox.completed', extra=stats)
        except Exception:  # noqa: BLE001 - keep the API alive and retry next poll
            logger.exception('memory.outbox.poll_failed')
        await asyncio.sleep(max(1, poll_interval_seconds))
