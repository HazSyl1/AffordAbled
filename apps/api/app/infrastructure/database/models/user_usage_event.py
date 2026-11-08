from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class UserUsageEventModel(Base):
    __tablename__ = 'user_usage_events'
    __table_args__ = (
        CheckConstraint(
            "metric IN ('chat_turn', 'ai_transaction', 'media_request')", name='ck_user_usage_events_metric',
        ),
        CheckConstraint('quantity > 0', name='ck_user_usage_events_quantity_positive'),
        UniqueConstraint('user_id', 'metric', 'idempotency_key', name='uq_user_usage_event_key'),
        Index('ix_user_usage_events_daily', 'user_id', 'metric', 'created_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
