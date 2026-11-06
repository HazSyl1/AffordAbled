from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.domain.entities import RecurrenceUnit, RecurringRuleStatus, RecurringTransactionRule, TransactionType
from app.presentation.schemas.transaction import TransactionResponse


class CreateRecurringTransactionRequest(BaseModel):
    account_id: uuid.UUID
    category_id: uuid.UUID
    type: TransactionType
    amount_paise: int = Field(gt=0)
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = None
    recurrence_unit: RecurrenceUnit
    interval_count: int = Field(default=1, ge=1, le=52)
    anchor_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    end_at: datetime | None = None
    max_occurrences: int | None = Field(default=None, ge=1, le=10000)
    create_initial_transaction: bool = False
    source_memory_id: uuid.UUID | None = None

    @model_validator(mode='after')
    def validate_scope(self) -> Self:
        if self.type not in {TransactionType.EXPENSE, TransactionType.INCOME}:
            raise ValueError('Recurring transactions support expenses and income only.')
        if self.recurrence_unit != RecurrenceUnit.WEEKLY and self.interval_count != 1:
            raise ValueError('Custom intervals are supported for weekly schedules only.')
        if self.end_at is not None and self.max_occurrences is not None:
            raise ValueError('Choose an end date or an occurrence count, not both.')
        return self


class UpdateRecurringTransactionRequest(BaseModel):
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    amount_paise: int | None = Field(default=None, gt=0)
    merchant: str | None = Field(default=None, max_length=255)
    note: str | None = None
    recurrence_unit: RecurrenceUnit | None = None
    interval_count: int | None = Field(default=None, ge=1, le=52)
    anchor_at: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    end_at: datetime | None = None
    max_occurrences: int | None = Field(default=None, ge=1, le=10000)


class RecurringTransactionResponse(BaseModel):
    id: str
    account_id: str | None
    category_id: str | None
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
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, rule: RecurringTransactionRule) -> Self:
        return cls(
            id=str(rule.id), account_id=str(rule.account_id) if rule.account_id else None,
            category_id=str(rule.category_id) if rule.category_id else None, type=rule.type,
            amount_paise=rule.amount_paise, merchant=rule.merchant, note=rule.note,
            recurrence_unit=rule.recurrence_unit, interval_count=rule.interval_count,
            anchor_at=rule.anchor_at, timezone=rule.timezone, end_at=rule.end_at,
            max_occurrences=rule.max_occurrences, next_occurrence_at=rule.next_occurrence_at,
            generated_count=rule.generated_count, status=rule.status, source=rule.source,
            last_error=rule.last_error, created_at=rule.created_at, updated_at=rule.updated_at,
        )


class CreateRecurringTransactionResponse(BaseModel):
    rule: RecurringTransactionResponse
    initial_transaction: TransactionResponse | None = None
