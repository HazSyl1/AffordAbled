"""Add payment history for partial split and IOU repayments.

Revision ID: x1_split_payment_history
Revises: w1_split_categories
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'x1_split_payment_history'
down_revision: str | None = 'w1_split_categories'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        'split_payments',
        sa.Column('id', sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            'participant_id', sa.Uuid(),
            sa.ForeignKey('split_participants.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column(
            'transaction_id', sa.Uuid(),
            sa.ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('transaction_id', name='uq_split_payment_transaction'),
    )
    op.create_index('ix_split_payments_participant_id', 'split_payments', ['participant_id'])

    # Preserve historical full repayments in the new ledger. Legacy records only
    # have a single linked transaction, so settled_paise is their payment amount.
    op.execute(sa.text("""
        INSERT INTO split_payments (id, participant_id, amount_paise, transaction_id, created_at)
        SELECT gen_random_uuid(), id, settled_paise, repayment_transaction_id, now()
        FROM split_participants
        WHERE settled_paise > 0 AND repayment_transaction_id IS NOT NULL
    """))


def downgrade() -> None:
    op.drop_index('ix_split_payments_participant_id', table_name='split_payments')
    op.drop_table('split_payments')
