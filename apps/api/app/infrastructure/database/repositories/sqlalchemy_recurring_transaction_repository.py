from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import RecurrenceUnit, RecurringRuleStatus, RecurringTransactionRule, TransactionType
from app.infrastructure.database.models import MemoryModel, RecurringTransactionRuleModel


class SqlAlchemyRecurringTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, rule: RecurringTransactionRule) -> RecurringTransactionRule:
        model = RecurringTransactionRuleModel(**self._values(rule))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return self._entity(model)

    async def get_for_user(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringTransactionRule | None:
        model = await self.session.scalar(select(RecurringTransactionRuleModel).where(
            RecurringTransactionRuleModel.id == rule_id,
            RecurringTransactionRuleModel.user_id == user_id,
        ))
        return self._entity(model) if model else None

    async def get_by_chat_source(
        self, user_id: uuid.UUID, turn_id: uuid.UUID, task_id: str,
    ) -> RecurringTransactionRule | None:
        model = await self.session.scalar(select(RecurringTransactionRuleModel).where(
            RecurringTransactionRuleModel.user_id == user_id,
            RecurringTransactionRuleModel.source_turn_id == turn_id,
            RecurringTransactionRuleModel.source_task_id == task_id,
        ))
        return self._entity(model) if model else None

    async def list_for_user(self, user_id: uuid.UUID) -> list[RecurringTransactionRule]:
        rows = await self.session.scalars(select(RecurringTransactionRuleModel).where(
            RecurringTransactionRuleModel.user_id == user_id,
        ).order_by(RecurringTransactionRuleModel.created_at.desc()))
        return [self._entity(row) for row in rows.all()]

    async def update(self, rule: RecurringTransactionRule, *, commit: bool = True) -> RecurringTransactionRule:
        model = await self.session.get(RecurringTransactionRuleModel, rule.id)
        if model is None or model.user_id != rule.user_id:
            raise LookupError(str(rule.id))
        for key, value in self._values(rule).items():
            if key != 'id':
                setattr(model, key, value)
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        await self.session.refresh(model)
        return self._entity(model)

    async def commit(self) -> None:
        await self.session.commit()

    async def consume_memory(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        memory = await self.session.scalar(select(MemoryModel).where(
            MemoryModel.id == memory_id,
            MemoryModel.user_id == user_id,
            MemoryModel.memory_type == 'recurring_transaction',
            MemoryModel.status == 'suggested',
        ))
        if memory is None:
            raise ValueError('Recurring transaction suggestion was not found.')
        memory.status = 'confirmed'
        memory.confirmed_at = datetime.now(UTC)

    async def claim_due_batch(
        self, *, limit: int = 50, stale_after_seconds: int = 300,
    ) -> list[RecurringTransactionRule]:
        now = datetime.now(UTC)
        stale_at = now - timedelta(seconds=max(1, stale_after_seconds))
        rows = list((await self.session.scalars(
            select(RecurringTransactionRuleModel)
            .where(
                RecurringTransactionRuleModel.status == RecurringRuleStatus.ACTIVE.value,
                RecurringTransactionRuleModel.next_occurrence_at.is_not(None),
                RecurringTransactionRuleModel.next_occurrence_at <= now,
                or_(
                    RecurringTransactionRuleModel.claimed_at.is_(None),
                    RecurringTransactionRuleModel.claimed_at <= stale_at,
                ),
            )
            .order_by(RecurringTransactionRuleModel.next_occurrence_at)
            .limit(max(1, min(limit, 100)))
            .with_for_update(skip_locked=True)
        )).all())
        if not rows:
            return []
        for model in rows:
            model.claimed_at = now
            model.attempts += 1
        await self.session.commit()
        for model in rows:
            await self.session.refresh(model)
        return [self._entity(model) for model in rows]

    async def claim_due(self, *, stale_after_seconds: int = 300) -> RecurringTransactionRule | None:
        rows = await self.claim_due_batch(limit=1, stale_after_seconds=stale_after_seconds)
        return rows[0] if rows else None

    async def next_eligible_due_at(self, *, stale_after_seconds: int = 300) -> datetime | None:
        """Return the next unclaimed or stale-claimed active occurrence without loading rule rows."""
        stale_at = datetime.now(UTC) - timedelta(seconds=max(1, stale_after_seconds))
        return await self.session.scalar(
            select(func.min(RecurringTransactionRuleModel.next_occurrence_at)).where(
                RecurringTransactionRuleModel.status == RecurringRuleStatus.ACTIVE.value,
                RecurringTransactionRuleModel.next_occurrence_at.is_not(None),
                or_(
                    RecurringTransactionRuleModel.claimed_at.is_(None),
                    RecurringTransactionRuleModel.claimed_at <= stale_at,
                ),
            )
        )
    @staticmethod
    def _values(rule: RecurringTransactionRule) -> dict:
        return {
            'id': rule.id, 'user_id': rule.user_id, 'account_id': rule.account_id,
            'category_id': rule.category_id, 'type': rule.type.value, 'amount_paise': rule.amount_paise,
            'merchant': rule.merchant, 'note': rule.note, 'recurrence_unit': rule.recurrence_unit.value,
            'interval_count': rule.interval_count, 'anchor_at': rule.anchor_at, 'timezone': rule.timezone,
            'end_at': rule.end_at, 'max_occurrences': rule.max_occurrences,
            'next_occurrence_at': rule.next_occurrence_at, 'generated_count': rule.generated_count,
            'status': rule.status.value, 'source': rule.source, 'source_memory_id': rule.source_memory_id,
            'source_turn_id': rule.source_turn_id, 'source_task_id': rule.source_task_id,
            'attempts': rule.attempts, 'claimed_at': rule.claimed_at, 'last_error': rule.last_error,
            'created_at': rule.created_at, 'updated_at': rule.updated_at,
        }

    @staticmethod
    def _entity(model: RecurringTransactionRuleModel) -> RecurringTransactionRule:
        return RecurringTransactionRule(
            id=model.id, user_id=model.user_id, account_id=model.account_id, category_id=model.category_id,
            type=TransactionType(model.type), amount_paise=model.amount_paise, merchant=model.merchant,
            note=model.note, recurrence_unit=RecurrenceUnit(model.recurrence_unit),
            interval_count=model.interval_count, anchor_at=model.anchor_at, timezone=model.timezone,
            end_at=model.end_at, max_occurrences=model.max_occurrences,
            next_occurrence_at=model.next_occurrence_at, generated_count=model.generated_count,
            status=RecurringRuleStatus(model.status), source=model.source, source_memory_id=model.source_memory_id,
            source_turn_id=model.source_turn_id, source_task_id=model.source_task_id, attempts=model.attempts,
            claimed_at=model.claimed_at, last_error=model.last_error, created_at=model.created_at,
            updated_at=model.updated_at,
        )
