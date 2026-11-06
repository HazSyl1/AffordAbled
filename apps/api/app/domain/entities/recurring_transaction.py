from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.entities.transaction import TransactionType


class RecurrenceUnit(str, Enum):
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'


class RecurringRuleStatus(str, Enum):
    ACTIVE = 'active'
    PAUSED = 'paused'
    NEEDS_ATTENTION = 'needs_attention'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'


@dataclass
class RecurringTransactionRule:
    id: uuid.UUID
    user_id: uuid.UUID
    account_id: uuid.UUID | None
    category_id: uuid.UUID | None
    type: TransactionType
    amount_paise: int
    merchant: str | None
    note: str | None
    recurrence_unit: RecurrenceUnit
    interval_count: int
    anchor_at: datetime
    timezone: str
    end_at: datetime | None
    max_occurrences: int | None
    next_occurrence_at: datetime | None
    generated_count: int
    status: RecurringRuleStatus
    source: str
    source_memory_id: uuid.UUID | None
    source_turn_id: uuid.UUID | None
    source_task_id: str | None
    attempts: int
    claimed_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
