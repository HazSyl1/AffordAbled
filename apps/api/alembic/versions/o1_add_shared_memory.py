from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'o1_add_shared_memory'
down_revision: str | None = 'n1_add_split_item_breakdown'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'memory_review_events',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('transaction_id', sa.Uuid(), sa.ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('split_id', sa.Uuid(), sa.ForeignKey('splits.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(length=24), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('before_json', sa.JSON(), nullable=False),
        sa.Column('after_json', sa.JSON(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_memory_events_user_created', 'memory_review_events', ['user_id', 'created_at'])
    op.create_index(
        'ix_memory_events_user_fingerprint', 'memory_review_events', ['user_id', 'fingerprint'], unique=True
    )
    op.create_index('ix_memory_review_events_user_id', 'memory_review_events', ['user_id'])
    op.create_index('ix_memory_review_events_transaction_id', 'memory_review_events', ['transaction_id'])
    op.create_index('ix_memory_review_events_split_id', 'memory_review_events', ['split_id'])

    op.create_table(
        'memory_outbox',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_id', sa.Uuid(), sa.ForeignKey('memory_review_events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('event_id', name='uq_memory_outbox_event'),
    )
    op.create_index('ix_memory_outbox_user_id', 'memory_outbox', ['user_id'])
    op.create_index('ix_memory_outbox_status', 'memory_outbox', ['status'])
    op.create_index('ix_memory_outbox_next_attempt_at', 'memory_outbox', ['next_attempt_at'])
    op.create_index('ix_memory_outbox_created_at', 'memory_outbox', ['created_at'])
    op.create_index('ix_memory_outbox_claim', 'memory_outbox', ['status', 'next_attempt_at', 'created_at'])

    op.create_table(
        'memories',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', sa.String(length=24), nullable=False),
        sa.Column('subject_key', sa.String(length=255), nullable=False),
        sa.Column('memory_type', sa.String(length=64), nullable=False),
        sa.Column('value_json', sa.JSON(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='suggested'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('evidence_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source_event_ids', sa.JSON(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_observed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_memories_user_id', 'memories', ['user_id'])
    op.create_index('ix_memories_user_status', 'memories', ['user_id', 'status'])
    op.create_index('ix_memories_user_scope_subject', 'memories', ['user_id', 'scope', 'subject_key'])
    op.create_index('ix_memories_user_fingerprint', 'memories', ['user_id', 'fingerprint'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_memories_user_fingerprint', table_name='memories')
    op.drop_index('ix_memories_user_scope_subject', table_name='memories')
    op.drop_index('ix_memories_user_status', table_name='memories')
    op.drop_index('ix_memories_user_id', table_name='memories')
    op.drop_table('memories')
    op.drop_index('ix_memory_outbox_claim', table_name='memory_outbox')
    op.drop_index('ix_memory_outbox_created_at', table_name='memory_outbox')
    op.drop_index('ix_memory_outbox_next_attempt_at', table_name='memory_outbox')
    op.drop_index('ix_memory_outbox_status', table_name='memory_outbox')
    op.drop_index('ix_memory_outbox_user_id', table_name='memory_outbox')
    op.drop_table('memory_outbox')
    op.drop_index('ix_memory_review_events_split_id', table_name='memory_review_events')
    op.drop_index('ix_memory_review_events_transaction_id', table_name='memory_review_events')
    op.drop_index('ix_memory_review_events_user_id', table_name='memory_review_events')
    op.drop_index('ix_memory_events_user_fingerprint', table_name='memory_review_events')
    op.drop_index('ix_memory_events_user_created', table_name='memory_review_events')
    op.drop_table('memory_review_events')
