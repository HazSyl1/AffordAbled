from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class RecurringTransactionRuleModel(Base):
    __tablename__ = 'recurring_transaction_rules'
    __table_args__ = (
        UniqueConstraint('user_id', 'source_turn_id', 'source_task_id', name='uq_recurring_rules_chat_source'),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('accounts.id', ondelete='SET NULL'), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('categories.id', ondelete='SET NULL'), index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    recurrence_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    interval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default='UTC')
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_occurrences: Mapped[int | None] = mapped_column(Integer)
    next_occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='active', index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default='manual')
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('memories.id', ondelete='SET NULL'), unique=True,
    )
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    source_task_id: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
