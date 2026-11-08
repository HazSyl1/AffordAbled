"""Add user tiers and daily usage events.

Revision ID: aa4_user_tiers_usage
Revises: aa3_split_scoped_notifications
"""

import sqlalchemy as sa

from alembic import op

revision = 'aa4_user_tiers_usage'
down_revision = 'aa3_split_scoped_notifications'
branch_labels = None
depends_on = None

TEST_USER_ID = 'a8843e3d-dcd4-4e43-9af0-9c845dae190a'


def upgrade() -> None:
    op.add_column(
        'users', sa.Column('account_tier', sa.String(length=20), nullable=False, server_default='free'),
    )
    op.create_check_constraint(
        'ck_users_account_tier', 'users', "account_tier IN ('free', 'subscribed', 'test')",
    )
    op.execute(
        f"UPDATE users SET account_tier = 'test' WHERE id = '{TEST_USER_ID}'::uuid"
    )
    op.create_table(
        'user_usage_events',
        sa.Column('id', sa.Uuid(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric', sa.String(length=32), nullable=False),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "metric IN ('chat_turn', 'ai_transaction', 'media_request')", name='ck_user_usage_events_metric',
        ),
        sa.CheckConstraint('quantity > 0', name='ck_user_usage_events_quantity_positive'),
        sa.UniqueConstraint('user_id', 'metric', 'idempotency_key', name='uq_user_usage_event_key'),
    )
    op.create_index('ix_user_usage_events_user_id', 'user_usage_events', ['user_id'])
    op.create_index(
        'ix_user_usage_events_daily', 'user_usage_events', ['user_id', 'metric', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_user_usage_events_daily', table_name='user_usage_events')
    op.drop_index('ix_user_usage_events_user_id', table_name='user_usage_events')
    op.drop_table('user_usage_events')
    op.drop_constraint('ck_users_account_tier', 'users', type_='check')
    op.drop_column('users', 'account_tier')
