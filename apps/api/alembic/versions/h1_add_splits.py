"""Add owner-scoped split tracker for recorded expenses."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'h1_add_splits'
down_revision: str | None = 'g7_add_transaction_analytics_index'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'splits',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('transaction_id', sa.Uuid(), sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('owner_share_paise', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('transaction_id', name='uq_splits_transaction'),
    )
    op.create_index('ix_splits_user_id', 'splits', ['user_id'])
    op.create_table(
        'split_participants',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('split_id', sa.Uuid(), sa.ForeignKey('splits.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('share_paise', sa.BigInteger(), nullable=False),
        sa.Column('settled_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('repayment_transaction_id', sa.Uuid(),
                  sa.ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True, unique=True),
        sa.UniqueConstraint('split_id', 'name', name='uq_split_participant_name'),
    )
    op.create_index('ix_split_participants_split_id', 'split_participants', ['split_id'])


def downgrade() -> None:
    op.drop_index('ix_split_participants_split_id', table_name='split_participants')
    op.drop_table('split_participants')
    op.drop_index('ix_splits_user_id', table_name='splits')
    op.drop_table('splits')
