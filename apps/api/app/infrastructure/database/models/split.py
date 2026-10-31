from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class SplitModel(Base):
    __tablename__ = 'splits'
    __table_args__ = (UniqueConstraint('transaction_id', name='uq_splits_transaction'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('transactions.id', ondelete='CASCADE'), nullable=True,
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default='to_you', server_default='to_you')
    title: Mapped[str] = mapped_column(String(255))
    owner_share_paise: Mapped[int] = mapped_column(BigInteger)
    item_breakdown: Mapped[list[dict] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    settlement_breakdown: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    participants: Mapped[list[SplitParticipantModel]] = relationship(
        back_populates='split', cascade='all, delete-orphan', lazy='selectin'
    )


class SplitParticipantModel(Base):
    __tablename__ = 'split_participants'
    __table_args__ = (UniqueConstraint('split_id', 'name', name='uq_split_participant_name'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    split_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('splits.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    share_paise: Mapped[int] = mapped_column(BigInteger)
    settled_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    repayment_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True, unique=True
    )
    split: Mapped[SplitModel] = relationship(back_populates='participants')
    payments: Mapped[list[SplitPaymentModel]] = relationship(
        back_populates='participant', cascade='all, delete-orphan', lazy='selectin',
        order_by='SplitPaymentModel.created_at',
    )


class SplitPaymentModel(Base):
    __tablename__ = 'split_payments'
    __table_args__ = (UniqueConstraint('transaction_id', name='uq_split_payment_transaction'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('split_participants.id', ondelete='CASCADE'), index=True,
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    participant: Mapped[SplitParticipantModel] = relationship(back_populates='payments')
