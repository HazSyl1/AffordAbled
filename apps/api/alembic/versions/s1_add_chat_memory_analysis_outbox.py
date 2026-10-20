from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 's1_chat_memory_analysis'
down_revision: str | None = 'r1_tx_chat_link'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'memory_analysis_outbox',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('transaction_id', sa.Uuid(), sa.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('signal_type', sa.String(length=32), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('transaction_id', name='uq_memory_analysis_transaction'),
    )
    op.create_index('ix_memory_analysis_outbox_user_id', 'memory_analysis_outbox', ['user_id'])
    op.create_index('ix_memory_analysis_outbox_status', 'memory_analysis_outbox', ['status'])
    op.create_index(
        'ix_memory_analysis_claim', 'memory_analysis_outbox', ['status', 'next_attempt_at', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_memory_analysis_claim', table_name='memory_analysis_outbox')
    op.drop_index('ix_memory_analysis_outbox_status', table_name='memory_analysis_outbox')
    op.drop_index('ix_memory_analysis_outbox_user_id', table_name='memory_analysis_outbox')
    op.drop_table('memory_analysis_outbox')
