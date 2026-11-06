"""add recurring transactions

Revision ID: z1_recurring_transactions
Revises: y1_durable_chat_turns
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'z1_recurring_transactions'
down_revision: str | None = 'y1_durable_chat_turns'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'recurring_transaction_rules',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('account_id', sa.Uuid(), nullable=True),
        sa.Column('category_id', sa.Uuid(), nullable=True),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('merchant', sa.String(255)), sa.Column('note', sa.Text()),
        sa.Column('recurrence_unit', sa.String(16), nullable=False),
        sa.Column('interval_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('anchor_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timezone', sa.String(64), nullable=False, server_default='UTC'),
        sa.Column('end_at', sa.DateTime(timezone=True)), sa.Column('max_occurrences', sa.Integer()),
        sa.Column('next_occurrence_at', sa.DateTime(timezone=True)),
        sa.Column('generated_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(24), nullable=False, server_default='active'),
        sa.Column('source', sa.String(16), nullable=False, server_default='manual'),
        sa.Column('source_memory_id', sa.Uuid()), sa.Column('source_turn_id', sa.Uuid()),
        sa.Column('source_task_id', sa.String(80)),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('claimed_at', sa.DateTime(timezone=True)), sa.Column('last_error', sa.String(1000)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_memory_id'], ['memories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_memory_id'),
        sa.UniqueConstraint('user_id', 'source_turn_id', 'source_task_id', name='uq_recurring_rules_chat_source'),
    )
    for column in ('user_id', 'account_id', 'category_id', 'next_occurrence_at', 'status', 'source_turn_id'):
        op.create_index(f'ix_recurring_transaction_rules_{column}', 'recurring_transaction_rules', [column])
    op.add_column('transactions', sa.Column('recurring_rule_id', sa.Uuid(), nullable=True))
    op.add_column('transactions', sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_transactions_recurring_rule', 'transactions', 'recurring_transaction_rules',
                          ['recurring_rule_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_transactions_recurring_rule_id', 'transactions', ['recurring_rule_id'])
    op.create_unique_constraint('uq_transactions_recurring_occurrence', 'transactions',
                                ['recurring_rule_id', 'scheduled_for'])


def downgrade() -> None:
    op.drop_constraint('uq_transactions_recurring_occurrence', 'transactions', type_='unique')
    op.drop_index('ix_transactions_recurring_rule_id', table_name='transactions')
    op.drop_constraint('fk_transactions_recurring_rule', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'scheduled_for')
    op.drop_column('transactions', 'recurring_rule_id')
    op.drop_table('recurring_transaction_rules')
