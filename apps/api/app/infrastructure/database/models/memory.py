from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class MemoryReviewEventModel(Base):
    __tablename__ = 'memory_review_events'
    __table_args__ = (
        Index('ix_memory_events_user_created', 'user_id', 'created_at'),
        Index('ix_memory_events_user_fingerprint', 'user_id', 'fingerprint', unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    split_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('splits.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    before_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    after_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class MemoryOutboxModel(Base):
    __tablename__ = 'memory_outbox'
    __table_args__ = (
        Index('ix_memory_outbox_claim', 'status', 'next_attempt_at', 'created_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('memory_review_events.id', ondelete='CASCADE'), nullable=False, unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class MemoryAnalysisOutboxModel(Base):
    """Durable, opt-in queue for extracting preference evidence from a chat turn."""

    __tablename__ = 'memory_analysis_outbox'
    __table_args__ = (
        Index('ix_memory_analysis_claim', 'status', 'next_attempt_at', 'created_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False, unique=True,
    )
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryModel(Base):
    __tablename__ = 'memories'
    __table_args__ = (
        Index('ix_memories_user_status', 'user_id', 'status'),
        Index('ix_memories_user_scope_subject', 'user_id', 'scope', 'subject_key'),
        Index('ix_memories_user_fingerprint', 'user_id', 'fingerprint', unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    scope: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='suggested', index=True)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_event_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
