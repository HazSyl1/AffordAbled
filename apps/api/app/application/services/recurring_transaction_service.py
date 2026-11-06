from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.application.dto import CreateTransactionInput
from app.application.services.transaction_service import TransactionService
from app.domain.entities import (
    RecurrenceUnit,
    RecurringRuleStatus,
    RecurringTransactionRule,
    Transaction,
    TransactionType,
)
from app.infrastructure.database.repositories.sqlalchemy_recurring_transaction_repository import (
    SqlAlchemyRecurringTransactionRepository,
)
from app.infrastructure.recurring_scheduler_signal import wake_recurring_scheduler


@dataclass(frozen=True)
class CreateRecurringRuleInput:
    user_id: uuid.UUID
    account_id: uuid.UUID
    category_id: uuid.UUID
    type: TransactionType
    amount_paise: int
    merchant: str | None
    note: str | None
    recurrence_unit: RecurrenceUnit
    interval_count: int
    anchor_at: datetime
    timezone: str
    end_at: datetime | None = None
    max_occurrences: int | None = None
    create_initial_transaction: bool = False
    source: str = 'manual'
    source_memory_id: uuid.UUID | None = None
    source_turn_id: uuid.UUID | None = None
    source_task_id: str | None = None


def next_occurrence(current: datetime, rule: RecurringTransactionRule) -> datetime:
    timezone = ZoneInfo(rule.timezone)
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current
    anchor_at = rule.anchor_at.replace(tzinfo=UTC) if rule.anchor_at.tzinfo is None else rule.anchor_at
    local = current.astimezone(timezone)
    anchor = anchor_at.astimezone(timezone)
    if rule.recurrence_unit == RecurrenceUnit.DAILY:
        candidate = local + timedelta(days=rule.interval_count)
    elif rule.recurrence_unit == RecurrenceUnit.WEEKLY:
        candidate = local + timedelta(weeks=rule.interval_count)
    elif rule.recurrence_unit == RecurrenceUnit.MONTHLY:
        month_index = local.year * 12 + local.month - 1 + rule.interval_count
        year, month_zero = divmod(month_index, 12)
        month = month_zero + 1
        day = min(anchor.day, calendar.monthrange(year, month)[1])
        candidate = local.replace(year=year, month=month, day=day)
    else:
        year = local.year + rule.interval_count
        day = min(anchor.day, calendar.monthrange(year, anchor.month)[1])
        candidate = local.replace(year=year, month=anchor.month, day=day)
    return candidate.astimezone(UTC)


class RecurringTransactionService:
    def __init__(
        self,
        repository: SqlAlchemyRecurringTransactionRepository,
        transaction_service: TransactionService,
    ) -> None:
        self.repository = repository
        self.transaction_service = transaction_service

    async def create_rule(self, data: CreateRecurringRuleInput) -> tuple[RecurringTransactionRule, Transaction | None]:
        if data.type not in {TransactionType.EXPENSE, TransactionType.INCOME}:
            raise ValueError('Recurring rules support expense and income transactions only.')
        if data.interval_count < 1 or data.amount_paise < 1:
            raise ValueError('Amount and recurrence interval must be greater than zero.')
        try:
            ZoneInfo(data.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError('Invalid timezone.') from exc
        if data.anchor_at.tzinfo is None or (data.end_at is not None and data.end_at.tzinfo is None):
            raise ValueError('Schedule dates must include a timezone.')
        if data.end_at is not None and data.end_at < data.anchor_at:
            raise ValueError('End date must not be before the start date.')
        if data.max_occurrences is not None and data.max_occurrences < 1:
            raise ValueError('Maximum occurrences must be greater than zero.')
        if data.source_turn_id and data.source_task_id:
            existing = await self.repository.get_by_chat_source(data.user_id, data.source_turn_id, data.source_task_id)
            if existing:
                return existing, None

        await self.transaction_service.validate_transaction_template(
            user_id=data.user_id, account_id=data.account_id, transaction_type=data.type,
            amount_paise=data.amount_paise, category_id=data.category_id, to_account_id=None,
        )
        now = datetime.now(UTC)
        rule = RecurringTransactionRule(
            id=uuid.uuid4(), user_id=data.user_id, account_id=data.account_id, category_id=data.category_id,
            type=data.type, amount_paise=data.amount_paise, merchant=data.merchant, note=data.note,
            recurrence_unit=data.recurrence_unit, interval_count=data.interval_count, anchor_at=data.anchor_at,
            timezone=data.timezone, end_at=data.end_at, max_occurrences=data.max_occurrences,
            next_occurrence_at=data.anchor_at.astimezone(UTC), generated_count=0,
            status=RecurringRuleStatus.ACTIVE, source=data.source, source_memory_id=data.source_memory_id,
            source_turn_id=data.source_turn_id, source_task_id=data.source_task_id, attempts=0,
            claimed_at=None, last_error=None, created_at=now, updated_at=now,
        )
        initial: Transaction | None = None
        if data.create_initial_transaction:
            rule.generated_count = 1
            rule.next_occurrence_at = next_occurrence(data.anchor_at, rule)
        else:
            rule.next_occurrence_at = data.anchor_at.astimezone(UTC)
        # The entered transaction is the latest known occurrence for a newly
        # created rule. Never manufacture historical cycles before activation;
        # advance directly to the first future occurrence instead.
        while rule.next_occurrence_at is not None and rule.next_occurrence_at <= now:
            rule.next_occurrence_at = next_occurrence(rule.next_occurrence_at, rule)
        self._complete_if_ended(rule)
        rule = await self.repository.create(rule)
        if data.source_memory_id is not None:
            await self.repository.consume_memory(data.user_id, data.source_memory_id)
        if data.create_initial_transaction:
            initial = await self._post(rule, data.anchor_at.astimezone(UTC))
        else:
            await self.repository.commit()
        wake_recurring_scheduler()
        return rule, initial

    async def list_rules(self, user_id: uuid.UUID) -> list[RecurringTransactionRule]:
        return await self.repository.list_for_user(user_id)

    async def get_rule(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringTransactionRule:
        rule = await self.repository.get_for_user(user_id, rule_id)
        if rule is None:
            raise LookupError(str(rule_id))
        return rule

    async def pause(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringTransactionRule:
        rule = await self.get_rule(user_id, rule_id)
        if rule.status == RecurringRuleStatus.ACTIVE:
            rule.status = RecurringRuleStatus.PAUSED
            rule.claimed_at = None
            rule.updated_at = datetime.now(UTC)
        updated = await self.repository.update(rule)
        wake_recurring_scheduler()
        return updated

    async def update_rule(self, user_id: uuid.UUID, rule_id: uuid.UUID, changes: dict) -> RecurringTransactionRule:
        rule = await self.get_rule(user_id, rule_id)
        if rule.status in {RecurringRuleStatus.CANCELLED, RecurringRuleStatus.COMPLETED}:
            raise ValueError('Completed or cancelled rules cannot be edited.')
        for field in ('account_id', 'category_id', 'amount_paise', 'merchant', 'note', 'recurrence_unit',
                      'interval_count', 'anchor_at', 'timezone', 'end_at', 'max_occurrences'):
            if field in changes:
                setattr(rule, field, changes[field])
        if rule.account_id is None or rule.category_id is None:
            raise ValueError('A valid account and category are required.')
        if rule.recurrence_unit != RecurrenceUnit.WEEKLY and rule.interval_count != 1:
            raise ValueError('Custom intervals are supported for weekly schedules only.')
        try:
            ZoneInfo(rule.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError('Invalid timezone.') from exc
        await self.transaction_service.validate_transaction_template(
            user_id=user_id, account_id=rule.account_id, transaction_type=rule.type,
            amount_paise=rule.amount_paise, category_id=rule.category_id, to_account_id=None,
        )
        now = datetime.now(UTC)
        candidate = rule.anchor_at.astimezone(UTC)
        while candidate <= now:
            candidate = next_occurrence(candidate, rule)
        rule.next_occurrence_at = candidate
        rule.updated_at = now
        rule.last_error = None
        rule.attempts = 0
        self._complete_if_ended(rule)
        updated = await self.repository.update(rule)
        wake_recurring_scheduler()
        return updated

    async def resume(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringTransactionRule:
        rule = await self.get_rule(user_id, rule_id)
        if rule.status not in {RecurringRuleStatus.PAUSED, RecurringRuleStatus.NEEDS_ATTENTION}:
            raise ValueError('Only paused or attention-required rules can be resumed.')
        now = datetime.now(UTC)
        current = rule.next_occurrence_at or rule.anchor_at
        current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
        while current <= now:
            current = next_occurrence(current, rule)
        rule.next_occurrence_at = current
        rule.status = RecurringRuleStatus.ACTIVE
        rule.claimed_at = None
        rule.attempts = 0
        rule.last_error = None
        rule.updated_at = now
        self._complete_if_ended(rule)
        updated = await self.repository.update(rule)
        wake_recurring_scheduler()
        return updated

    async def cancel(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringTransactionRule:
        rule = await self.get_rule(user_id, rule_id)
        rule.status = RecurringRuleStatus.CANCELLED
        rule.next_occurrence_at = None
        rule.claimed_at = None
        rule.updated_at = datetime.now(UTC)
        updated = await self.repository.update(rule)
        wake_recurring_scheduler()
        return updated

    async def process_due(self, rule: RecurringTransactionRule) -> Transaction:
        scheduled_for = rule.next_occurrence_at
        if scheduled_for is None:
            raise ValueError('Rule has no due occurrence.')
        transaction = await self._post(rule, scheduled_for)
        rule.generated_count += 1
        rule.next_occurrence_at = next_occurrence(scheduled_for, rule)
        rule.claimed_at = None
        rule.attempts = 0
        rule.last_error = None
        rule.updated_at = datetime.now(UTC)
        self._complete_if_ended(rule)
        await self.repository.update(rule)
        return transaction

    async def fail_due(self, rule: RecurringTransactionRule, error: str, *, max_attempts: int = 8) -> None:
        rule.claimed_at = None
        rule.last_error = error[:1000]
        rule.updated_at = datetime.now(UTC)
        if rule.attempts >= max_attempts:
            rule.status = RecurringRuleStatus.NEEDS_ATTENTION
        await self.repository.update(rule)

    async def _post(self, rule: RecurringTransactionRule, scheduled_for: datetime) -> Transaction:
        if rule.account_id is None or rule.category_id is None:
            raise ValueError('The recurring rule needs a valid account and category.')
        return await self.transaction_service.create_transaction(CreateTransactionInput(
            user_id=rule.user_id, account_id=rule.account_id, category_id=rule.category_id, type=rule.type,
            amount_paise=rule.amount_paise, occurred_at=scheduled_for, merchant=rule.merchant, note=rule.note,
            recurring_rule_id=rule.id, scheduled_for=scheduled_for,
        ))

    @staticmethod
    def _complete_if_ended(rule: RecurringTransactionRule) -> None:
        exhausted = rule.max_occurrences is not None and rule.generated_count >= rule.max_occurrences
        beyond_end = (
            rule.end_at is not None
            and rule.next_occurrence_at is not None
            and rule.next_occurrence_at > rule.end_at
        )
        if exhausted or beyond_end:
            rule.status = RecurringRuleStatus.COMPLETED
            rule.next_occurrence_at = None
