from __future__ import annotations

import asyncio
import logging

from app.infrastructure.ai.agents.chat_memory_analysis import extract_chat_memory_candidates
from app.infrastructure.database.models.memory import MemoryAnalysisOutboxModel
from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository
from app.infrastructure.database.session import SessionLocal

logger = logging.getLogger(__name__)


async def run_memory_outbox_once(*, batch_size: int = 20, analysis_llm=None) -> dict[str, int]:
    async with SessionLocal() as session:
        repository = SqlAlchemyMemoryRepository(session)
        rows = await repository.claim_batch(limit=batch_size)
        row_ids = [row.id for row in rows]
        analysis_rows = await repository.claim_analysis_batch(limit=max(1, batch_size // 2)) if analysis_llm else []
        analysis_ids = [row.id for row in analysis_rows]

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
    analysis_processed = 0
    analysis_failed = 0
    for row_id in analysis_ids:
        async with SessionLocal() as session:
            repository = SqlAlchemyMemoryRepository(session)
            row = await session.get(MemoryAnalysisOutboxModel, row_id)
            if row is None:
                continue
            try:
                candidates = await extract_chat_memory_candidates(analysis_llm, row.payload_json)
                await repository.complete_chat_analysis(row_id, candidates)
                analysis_processed += 1
            except Exception as error:  # noqa: BLE001 - retryable worker boundary
                await session.rollback()
                await repository.fail_chat_analysis(row_id, str(error))
                analysis_failed += 1
                logger.exception('memory.analysis.failed', extra={'outbox_id': str(row_id)})
    return {
        'claimed': len(row_ids) + len(analysis_ids), 'processed': processed + analysis_processed,
        'failed': failed + analysis_failed,
    }


async def run_memory_outbox_loop(*, poll_interval_seconds: int = 5, batch_size: int = 20, analysis_llm=None) -> None:
    while True:
        try:
            stats = await run_memory_outbox_once(batch_size=batch_size, analysis_llm=analysis_llm)
            if stats['claimed']:
                logger.info('memory.outbox.completed', extra=stats)
        except Exception:  # noqa: BLE001 - keep the API alive and retry next poll
            logger.exception('memory.outbox.poll_failed')
        await asyncio.sleep(max(1, poll_interval_seconds))
