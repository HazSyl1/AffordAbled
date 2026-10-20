from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.memory_service import candidates_for_event, fingerprint, is_self_split_subject
from app.infrastructure.database.models import (
    MemoryAnalysisOutboxModel,
    MemoryModel,
    MemoryOutboxModel,
    MemoryReviewEventModel,
)


class SqlAlchemyMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def add_chat_analysis(
        self,
        *,
        user_id: uuid.UUID,
        transaction_id: uuid.UUID,
        signal_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Stage one bounded analysis job in the transaction's current DB transaction."""
        self.session.add(MemoryAnalysisOutboxModel(
            id=uuid.uuid4(), user_id=user_id, transaction_id=transaction_id,
            signal_type=signal_type, payload_json=payload,
        ))

    async def claim_analysis_batch(
        self, *, limit: int = 10, stale_after_seconds: int = 120,
    ) -> list[MemoryAnalysisOutboxModel]:
        now = datetime.now(UTC)
        stale_at = now - timedelta(seconds=stale_after_seconds)
        query = (
            select(MemoryAnalysisOutboxModel)
            .where(
                ((MemoryAnalysisOutboxModel.status == 'pending') &
                 (MemoryAnalysisOutboxModel.next_attempt_at <= now))
                | ((MemoryAnalysisOutboxModel.status == 'processing') &
                   (MemoryAnalysisOutboxModel.claimed_at <= stale_at)),
            )
            .order_by(MemoryAnalysisOutboxModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list((await self.session.scalars(query)).all())
        for row in rows:
            row.status = 'processing'
            row.claimed_at = now
            row.attempts += 1
        await self.session.commit()
        return rows

    async def complete_chat_analysis(self, outbox_id: uuid.UUID, candidates: list[dict[str, Any]]) -> None:
        row = await self.session.get(MemoryAnalysisOutboxModel, outbox_id)
        if row is None:
            return
        if candidates:
            payload = {
                'transaction_id': str(row.transaction_id),
                'candidates': candidates,
            }
            event_fingerprint = fingerprint(payload)
            with self.session.no_autoflush:
                existing = await self.session.scalar(select(MemoryReviewEventModel).where(
                    MemoryReviewEventModel.user_id == row.user_id,
                    MemoryReviewEventModel.fingerprint == event_fingerprint,
                ))
            if existing is None:
                event = MemoryReviewEventModel(
                    id=uuid.uuid4(), user_id=row.user_id, transaction_id=row.transaction_id,
                    action='accepted', source='chat_context_analysis', before_json={},
                    after_json={'memory_candidates': candidates}, fingerprint=event_fingerprint,
                )
                self.session.add(event)
                await self.session.flush()
                self.session.add(MemoryOutboxModel(id=uuid.uuid4(), user_id=row.user_id, event_id=event.id))
        row.status = 'processed'
        row.processed_at = datetime.now(UTC)
        row.last_error = None
        # The queued transcript and account/category snapshot are no longer needed.
        row.payload_json = {}
        await self.session.commit()

    async def fail_chat_analysis(self, outbox_id: uuid.UUID, error: str) -> None:
        row = await self.session.get(MemoryAnalysisOutboxModel, outbox_id)
        if row is None:
            return
        delay_seconds = min(3600, 2 ** min(row.attempts, 10))
        row.status = 'failed' if row.attempts >= 8 else 'pending'
        row.last_error = error[:1000]
        if row.status == 'failed':
            row.payload_json = {}
        row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        await self.session.commit()

    async def add_review_event(
        self,
        *,
        user_id: uuid.UUID,
        action: str,
        source: str,
        before: dict[str, Any],
        after: dict[str, Any],
        transaction_id: uuid.UUID | None = None,
        split_id: uuid.UUID | None = None,
    ) -> MemoryReviewEventModel:
        payload = {
            'transaction_id': str(transaction_id) if transaction_id else None,
            'split_id': str(split_id) if split_id else None,
            'action': action,
            'source': source,
            'before': before,
            'after': after,
        }
        event_fingerprint = fingerprint(payload)
        # Do not flush the transaction being edited while checking for a
        # duplicate event. The transaction service deliberately commits the
        # transaction and its memory event together after this method returns.
        with self.session.no_autoflush:
            existing = await self.session.scalar(select(MemoryReviewEventModel).where(
                MemoryReviewEventModel.user_id == user_id,
                MemoryReviewEventModel.fingerprint == event_fingerprint,
            ))
        if existing is not None:
            return existing

        # The HTTP request can be retried or submitted twice before the first
        # request commits. PostgreSQL handles that race atomically; the
        # fallback below keeps the lightweight SQLite test database working.
        if self.session.bind is not None and self.session.bind.dialect.name == 'postgresql':
            event_id = uuid.uuid4()
            event_statement = postgres_insert(MemoryReviewEventModel.__table__).values(
                id=event_id, user_id=user_id, transaction_id=transaction_id, split_id=split_id,
                action=action, source=source, before_json=before, after_json=after,
                fingerprint=event_fingerprint,
            ).on_conflict_do_nothing(index_elements=['user_id', 'fingerprint'])
            with self.session.no_autoflush:
                await self.session.execute(event_statement)
                event = await self.session.scalar(select(MemoryReviewEventModel).where(
                    MemoryReviewEventModel.user_id == user_id,
                    MemoryReviewEventModel.fingerprint == event_fingerprint,
                ))
            if event is None:
                raise RuntimeError('Could not create or retrieve the memory review event.')
            outbox_statement = postgres_insert(MemoryOutboxModel.__table__).values(
                id=uuid.uuid4(), user_id=user_id, event_id=event.id,
            ).on_conflict_do_nothing(index_elements=['event_id'])
            with self.session.no_autoflush:
                await self.session.execute(outbox_statement)
            return event

        event = MemoryReviewEventModel(
            id=uuid.uuid4(), user_id=user_id, transaction_id=transaction_id, split_id=split_id,
            action=action, source=source, before_json=before, after_json=after,
            fingerprint=event_fingerprint,
        )
        self.session.add(event)
        # The outbox row has a foreign key to the event. Explicitly flush the
        # event first because SQLAlchemy has no relationship metadata between
        # these two pending objects and SQLite may otherwise insert the outbox
        # row before its parent during autoflush.
        await self.session.flush()
        self.session.add(MemoryOutboxModel(id=uuid.uuid4(), user_id=user_id, event_id=event.id))
        return event

    async def list_for_user(self, user_id: uuid.UUID, *, status: str | None = None) -> list[MemoryModel]:
        query = select(MemoryModel).where(MemoryModel.user_id == user_id)
        if status:
            query = query.where(MemoryModel.status == status)
            if status == 'suggested':
                # A pattern is user-visible only after three distinct reviewed events.
                query = query.where(MemoryModel.evidence_count >= 3)
        else:
            query = query.where(
                MemoryModel.status.in_({'suggested', 'confirmed', 'dismissed'}),
                or_(MemoryModel.status != 'suggested', MemoryModel.evidence_count >= 3),
            )
        result = await self.session.scalars(query.order_by(MemoryModel.updated_at.desc(), MemoryModel.id.desc()))
        return [
            memory for memory in result.all()
            if not (memory.memory_type == 'split_method' and is_self_split_subject(memory.subject_key))
        ]

    async def relevant_confirmed(
        self, user_id: uuid.UUID, *, subjects: list[str], scopes: list[str], limit: int = 20,
    ) -> list[MemoryModel]:
        normalized_subjects = [subject.casefold() for subject in subjects if subject]
        query = select(MemoryModel).where(
            MemoryModel.user_id == user_id,
            MemoryModel.status == 'confirmed',
            MemoryModel.scope.in_(scopes),
        )
        if normalized_subjects:
            query = query.where(MemoryModel.subject_key.in_(normalized_subjects))
        result = await self.session.scalars(query.order_by(MemoryModel.updated_at.desc()).limit(limit))
        return [
            memory for memory in result.all()
            if not (memory.memory_type == 'split_method' and is_self_split_subject(memory.subject_key))
        ]

    async def confirm(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> MemoryModel | None:
        memory = await self.session.scalar(select(MemoryModel).where(
            MemoryModel.id == memory_id, MemoryModel.user_id == user_id,
        ))
        if memory is None:
            return None
        memory.status = 'confirmed'
        memory.confirmed_at = datetime.now(UTC)
        memory.dismissed_at = None
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def update_value(self, user_id: uuid.UUID, memory_id: uuid.UUID, value: dict) -> MemoryModel | None:
        memory = await self.session.scalar(select(MemoryModel).where(
            MemoryModel.id == memory_id, MemoryModel.user_id == user_id,
        ))
        if memory is None:
            return None
        memory.value_json = value
        memory.status = 'suggested'
        memory.dismissed_at = None
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def dismiss(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> MemoryModel | None:
        memory = await self.session.scalar(select(MemoryModel).where(
            MemoryModel.id == memory_id, MemoryModel.user_id == user_id,
        ))
        if memory is None:
            return None
        memory.status = 'dismissed'
        memory.dismissed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def delete(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
        memory = await self.session.scalar(select(MemoryModel).where(
            MemoryModel.id == memory_id, MemoryModel.user_id == user_id,
        ))
        if memory is None:
            return False
        await self.session.delete(memory)
        await self.session.commit()
        return True

    async def claim_batch(self, *, limit: int = 20, stale_after_seconds: int = 120) -> list[MemoryOutboxModel]:
        now = datetime.now(UTC)
        stale_at = now - timedelta(seconds=stale_after_seconds)
        query = (
            select(MemoryOutboxModel)
            .where(
                ((MemoryOutboxModel.status == 'pending') & (MemoryOutboxModel.next_attempt_at <= now))
                | ((MemoryOutboxModel.status == 'processing') & (MemoryOutboxModel.claimed_at <= stale_at)),
            )
            .order_by(MemoryOutboxModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list((await self.session.scalars(query)).all())
        for row in rows:
            row.status = 'processing'
            row.claimed_at = now
            row.attempts += 1
        await self.session.commit()
        return rows

    async def process_event(self, outbox_id: uuid.UUID) -> None:
        row = await self.session.get(MemoryOutboxModel, outbox_id)
        if row is None:
            return
        event = await self.session.get(MemoryReviewEventModel, row.event_id)
        if event is None:
            row.status = 'processed'
            row.processed_at = datetime.now(UTC)
            await self.session.commit()
            return
        for candidate in candidates_for_event(
            action=event.action, before=event.before_json, after=event.after_json,
        ):
            memory = await self.session.scalar(select(MemoryModel).where(
                MemoryModel.user_id == event.user_id,
                MemoryModel.fingerprint == candidate.fingerprint,
            ))
            if memory is None:
                memory = MemoryModel(
                    id=uuid.uuid4(), user_id=event.user_id,
                    scope=candidate.scope, subject_key=candidate.subject_key,
                    memory_type=candidate.memory_type, value_json=candidate.value_json,
                    fingerprint=candidate.fingerprint, status='pending',
                    confidence=0.0, evidence_count=0, source_event_ids=[],
                )
                self.session.add(memory)
            source_ids = list(memory.source_event_ids or [])
            if str(event.id) not in source_ids:
                source_ids.append(str(event.id))
                memory.source_event_ids = source_ids
                memory.evidence_count = len(source_ids)
            memory.confidence = min(1.0, memory.evidence_count / 3)
            memory.last_observed_at = datetime.now(UTC)
            if memory.evidence_count >= 3 and memory.status not in {'confirmed', 'dismissed'}:
                memory.status = 'suggested'
        row.status = 'processed'
        row.processed_at = datetime.now(UTC)
        row.last_error = None
        await self.session.commit()

    async def fail(self, outbox_id: uuid.UUID, error: str) -> None:
        row = await self.session.get(MemoryOutboxModel, outbox_id)
        if row is None:
            return
        delay_seconds = min(3600, 2 ** min(row.attempts, 10))
        row.status = 'failed' if row.attempts >= 8 else 'pending'
        row.last_error = error[:1000]
        row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        await self.session.commit()
