from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class SettlementDraftModel(Base):
    __tablename__ = 'settlement_drafts'
    __table_args__ = (UniqueConstraint('user_id', 'request_key', name='uq_settlement_draft_request'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    request_key: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    input_json: Mapped[dict] = mapped_column(JSON)
    preview_json: Mapped[dict] = mapped_column(JSON)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('settlement_plans.id', ondelete='SET NULL'), nullable=True,
    )
    revision_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('settlement_plans.id', ondelete='CASCADE'), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SettlementPlanModel(Base):
    __tablename__ = 'settlement_plans'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    title: Mapped[str] = mapped_column(String(255))
    total_paise: Mapped[int] = mapped_column(BigInteger)
    input_json: Mapped[dict] = mapped_column(JSON)
    preview_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    transactions: Mapped[list[SettlementPlanTransactionModel]] = relationship(
        back_populates='plan', cascade='all, delete-orphan', lazy='selectin',
    )
    transfers: Mapped[list[SettlementPlanTransferModel]] = relationship(
        back_populates='plan', cascade='all, delete-orphan', lazy='selectin',
    )


class SettlementPlanTransactionModel(Base):
    __tablename__ = 'settlement_plan_transactions'

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('transactions.id', ondelete='RESTRICT'), primary_key=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('settlement_plans.id', ondelete='CASCADE'), index=True)
    plan: Mapped[SettlementPlanModel] = relationship(back_populates='transactions')


class SettlementPlanTransferModel(Base):
    __tablename__ = 'settlement_plan_transfers'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('settlement_plans.id', ondelete='CASCADE'), index=True)
    debtor: Mapped[str] = mapped_column(String(100))
    creditor: Mapped[str] = mapped_column(String(100))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repayment_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True, unique=True,
    )
    plan: Mapped[SettlementPlanModel] = relationship(back_populates='transfers')
