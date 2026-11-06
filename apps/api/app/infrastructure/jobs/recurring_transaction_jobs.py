from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.application.services.recurring_transaction_service import RecurringTransactionService
from app.application.services.transaction_service import TransactionService
from app.infrastructure.database.repositories.sqlalchemy_account_repository import SqlAlchemyAccountRepository
from app.infrastructure.database.repositories.sqlalchemy_category_repository import SqlAlchemyCategoryRepository
from app.infrastructure.database.repositories.sqlalchemy_recurring_transaction_repository import (
    SqlAlchemyRecurringTransactionRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_split_repository import SqlAlchemySplitRepository
from app.infrastructure.database.repositories.sqlalchemy_transaction_repository import SqlAlchemyTransactionRepository
from app.infrastructure.database.session import SessionLocal
from app.infrastructure.recurring_scheduler_signal import (
    clear_recurring_scheduler_wakeup,
    install_recurring_scheduler_wakeup,
)

logger = logging.getLogger(__name__)


def _service(session) -> RecurringTransactionService:
    transaction_service = TransactionService(
        SqlAlchemyTransactionRepository(session), SqlAlchemyAccountRepository(session),
        SqlAlchemyCategoryRepository(session), split_repository=SqlAlchemySplitRepository(session),
    )
    return RecurringTransactionService(SqlAlchemyRecurringTransactionRepository(session), transaction_service)


def seconds_until_next_due(next_due_at: datetime | None, *, max_sleep_seconds: int) -> float:
    """Sleep until the next eligible occurrence, but wake periodically for stale-claim recovery."""
    ceiling = max(1, max_sleep_seconds)
    if next_due_at is None:
        return float(ceiling)
    due_at = next_due_at.replace(tzinfo=UTC) if next_due_at.tzinfo is None else next_due_at
    return max(0.0, min(float(ceiling), (due_at - datetime.now(UTC)).total_seconds()))


async def wait_for_schedule_change_or_timeout(wakeup_event: asyncio.Event, wait_seconds: float) -> bool:
    """Return True when a rule change interrupts the sleep, False at the scheduled wake time."""
    try:
        await asyncio.wait_for(wakeup_event.wait(), timeout=max(0.0, wait_seconds))
        return True
    except TimeoutError:
        return False


async def run_recurring_transaction_batch_once(
    *, stale_after_seconds: int = 300, max_attempts: int = 8, batch_size: int = 50,
    session_factory=SessionLocal,
) -> int:
    async with session_factory() as session:
        service = _service(session)
        rules = await service.repository.claim_due_batch(
            stale_after_seconds=stale_after_seconds, limit=batch_size,
        )
    for rule in rules:
        try:
            async with session_factory() as session:
                service = _service(session)
                await service.process_due(rule)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - durable worker boundary
            logger.exception('recurring_transaction.occurrence_failed', extra={'rule_id': str(rule.id)})
            async with session_factory() as session:
                await _service(session).fail_due(rule, str(error), max_attempts=max_attempts)
    return len(rules)


async def run_recurring_transaction_once(*, stale_after_seconds: int = 300, max_attempts: int = 8,
                                         session_factory=SessionLocal) -> bool:
    return bool(await run_recurring_transaction_batch_once(
        stale_after_seconds=stale_after_seconds, max_attempts=max_attempts, batch_size=1,
        session_factory=session_factory,
    ))


async def run_recurring_transaction_loop(*, stale_after_seconds: int = 300, max_attempts: int = 8,
                                         batch_size: int = 50, max_sleep_seconds: int = 300) -> None:
    wakeup_event = asyncio.Event()
    install_recurring_scheduler_wakeup(wakeup_event)
    try:
        while True:
            processed_count = await run_recurring_transaction_batch_once(
                stale_after_seconds=stale_after_seconds,
                max_attempts=max_attempts,
                batch_size=batch_size,
            )
            if processed_count:
                # Yield before the next catch-up batch rather than sleeping through overdue work.
                await asyncio.sleep(0)
                continue
            # Clear before the read. A change before this point is visible in the
            # query; a change after it sets the event and interrupts the wait.
            wakeup_event.clear()
            async with SessionLocal() as session:
                next_due_at = await SqlAlchemyRecurringTransactionRepository(session).next_eligible_due_at(
                    stale_after_seconds=stale_after_seconds,
                )
            await wait_for_schedule_change_or_timeout(
                wakeup_event,
                seconds_until_next_due(next_due_at, max_sleep_seconds=max_sleep_seconds),
            )
    finally:
        clear_recurring_scheduler_wakeup(wakeup_event)
