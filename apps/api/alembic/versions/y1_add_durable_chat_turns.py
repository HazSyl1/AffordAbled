"""Add durable chat turns and chat mutation idempotency.

Revision ID: y1_durable_chat_turns
Revises: x1_split_payment_history
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'y1_durable_chat_turns'
down_revision: str | None = 'x1_split_payment_history'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'chat_turn_jobs',
        sa.Column('id', sa.Uuid(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('thread_id', sa.String(length=120), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='queued'),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('error_code', sa.String(length=80), nullable=True),
        sa.Column('error_message', sa.String(length=600), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('user_id', 'id', name='uq_chat_turn_jobs_user_id'),
    )
    op.create_index('ix_chat_turn_jobs_user_id', 'chat_turn_jobs', ['user_id'])
    op.create_index('ix_chat_turn_jobs_thread_id', 'chat_turn_jobs', ['thread_id'])
    op.create_index('ix_chat_turn_jobs_status', 'chat_turn_jobs', ['status'])
    op.create_index('ix_chat_turn_jobs_claim', 'chat_turn_jobs', ['status', 'created_at'])
    op.create_index(
        'uq_chat_turn_jobs_processing_thread',
        'chat_turn_jobs',
        ['user_id', 'thread_id'],
        unique=True,
        postgresql_where=sa.text("status = 'processing'"),
    )

    op.add_column('chat_messages', sa.Column('turn_id', sa.Uuid(), nullable=True))
    op.create_index('ix_chat_messages_turn_id', 'chat_messages', ['turn_id'])
    op.create_unique_constraint(
        'uq_chat_messages_user_turn_role', 'chat_messages', ['user_id', 'turn_id', 'role'],
    )

    op.add_column('transactions', sa.Column('source_turn_id', sa.Uuid(), nullable=True))
    op.add_column('transactions', sa.Column('source_task_id', sa.String(length=80), nullable=True))
    op.add_column('transactions', sa.Column('source_item_index', sa.Integer(), nullable=True))
    op.create_index('ix_transactions_source_turn_id', 'transactions', ['source_turn_id'])
    op.create_unique_constraint(
        'uq_transactions_chat_source', 'transactions',
        ['user_id', 'source_turn_id', 'source_task_id', 'source_item_index'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_transactions_chat_source', 'transactions', type_='unique')
    op.drop_index('ix_transactions_source_turn_id', table_name='transactions')
    op.drop_column('transactions', 'source_item_index')
    op.drop_column('transactions', 'source_task_id')
    op.drop_column('transactions', 'source_turn_id')

    op.drop_constraint('uq_chat_messages_user_turn_role', 'chat_messages', type_='unique')
    op.drop_index('ix_chat_messages_turn_id', table_name='chat_messages')
    op.drop_column('chat_messages', 'turn_id')

    op.drop_index('ix_chat_turn_jobs_claim', table_name='chat_turn_jobs')
    op.drop_index('uq_chat_turn_jobs_processing_thread', table_name='chat_turn_jobs')
    op.drop_index('ix_chat_turn_jobs_status', table_name='chat_turn_jobs')
    op.drop_index('ix_chat_turn_jobs_thread_id', table_name='chat_turn_jobs')
    op.drop_index('ix_chat_turn_jobs_user_id', table_name='chat_turn_jobs')
    op.drop_table('chat_turn_jobs')
