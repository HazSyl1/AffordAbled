"""Add versioned settlement drafts and multi-transaction plans."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'u1_complex_settlement'
down_revision: str | None = 't1_split_settlement_breakdown'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        'settlement_plans',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('total_paise', sa.BigInteger(), nullable=False),
        sa.Column('input_json', sa.JSON(), nullable=False),
        sa.Column('preview_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_settlement_plans_user_id', 'settlement_plans', ['user_id'])
    op.create_table(
        'settlement_drafts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_key', sa.String(120), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('input_json', sa.JSON(), nullable=False),
        sa.Column('preview_json', sa.JSON(), nullable=False),
        sa.Column('plan_id', sa.Uuid(), sa.ForeignKey('settlement_plans.id', ondelete='SET NULL')),
        sa.Column('revision_plan_id', sa.Uuid(), sa.ForeignKey('settlement_plans.id', ondelete='CASCADE')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('user_id', 'request_key', name='uq_settlement_draft_request'),
    )
    op.create_index('ix_settlement_drafts_user_id', 'settlement_drafts', ['user_id'])
    op.create_table(
        'settlement_plan_transactions',
        sa.Column('transaction_id', sa.Uuid(), sa.ForeignKey('transactions.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('plan_id', sa.Uuid(), sa.ForeignKey('settlement_plans.id', ondelete='CASCADE'), nullable=False),
    )
    op.create_index('ix_settlement_plan_transactions_plan_id', 'settlement_plan_transactions', ['plan_id'])
    op.create_table(
        'settlement_plan_transfers',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('plan_id', sa.Uuid(), sa.ForeignKey('settlement_plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('debtor', sa.String(100), nullable=False),
        sa.Column('creditor', sa.String(100), nullable=False),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('settled_at', sa.DateTime(timezone=True)),
        sa.Column('repayment_transaction_id', sa.Uuid(),
                  sa.ForeignKey('transactions.id', ondelete='SET NULL'), unique=True),
    )
    op.create_index('ix_settlement_plan_transfers_plan_id', 'settlement_plan_transfers', ['plan_id'])


def downgrade() -> None:
    op.drop_table('settlement_plan_transfers')
    op.drop_table('settlement_plan_transactions')
    op.drop_table('settlement_drafts')
    op.drop_table('settlement_plans')
