from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class SplitNotificationModel(Base):
    __tablename__ = 'split_notifications'
    __table_args__ = (
        UniqueConstraint(
            'sent_by_user_id', 'idempotency_key', 'split_participant_id',
            name='uq_split_notification_campaign_recipient',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    split_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('splits.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    split_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('split_participants.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    sent_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default='sms', server_default='sms')
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default='azure_acs')
    recipient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    recipient_phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='INR', server_default='INR')
    message_body: Mapped[str] = mapped_column(Text, nullable=False)
    upi_link: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
