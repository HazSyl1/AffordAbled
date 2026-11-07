"""add split payment notifications

Revision ID: aa1_split_notifications
Revises: z1_recurring_transactions
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'aa1_split_notifications'
down_revision: str | None = 'z1_recurring_transactions'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('upi_id', sa.String(255), nullable=True))
    op.add_column('split_contacts', sa.Column('phone_e164', sa.String(20), nullable=True))
    op.add_column('split_participants', sa.Column('contact_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_split_participants_contact', 'split_participants', 'split_contacts',
        ['contact_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_split_participants_contact_id', 'split_participants', ['contact_id'])

    op.create_table(
        'split_notifications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('split_id', sa.Uuid(), nullable=True),
        sa.Column('split_participant_id', sa.Uuid(), nullable=True),
        sa.Column('sent_by_user_id', sa.Uuid(), nullable=False),
        sa.Column('idempotency_key', sa.Uuid(), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False, server_default='sms'),
        sa.Column('provider', sa.String(30), nullable=False),
        sa.Column('recipient_name', sa.String(100), nullable=False),
        sa.Column('recipient_phone_e164', sa.String(20), nullable=False),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='INR'),
        sa.Column('message_body', sa.Text(), nullable=False),
        sa.Column('upi_link', sa.Text(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('blocked_reason', sa.String(50), nullable=True),
        sa.Column('provider_message_id', sa.String(255), nullable=True),
        sa.Column('provider_error_code', sa.String(100), nullable=True),
        sa.Column('provider_error_message', sa.String(500), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('amount_paise > 0', name='ck_split_notifications_amount_positive'),
        sa.CheckConstraint("channel = 'sms'", name='ck_split_notifications_channel'),
        sa.CheckConstraint(
            "status IN ('queued','processing','sent','failed','rate_limited','cancelled','uncertain')",
            name='ck_split_notifications_status',
        ),
        sa.ForeignKeyConstraint(['split_id'], ['splits.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['split_participant_id'], ['split_participants.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sent_by_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sent_by_user_id', 'idempotency_key', name='uq_split_notification_idempotency'),
    )
    op.create_index('ix_split_notifications_split_id', 'split_notifications', ['split_id'])
    op.create_index('ix_split_notifications_split_participant_id', 'split_notifications', ['split_participant_id'])
    op.create_index('ix_split_notifications_sent_by_user_id', 'split_notifications', ['sent_by_user_id'])
    op.create_index('ix_split_notifications_status', 'split_notifications', ['status'])
    op.create_index(
        'ix_split_notifications_participant_status_created', 'split_notifications',
        ['split_participant_id', 'status', 'created_at'],
    )
    op.create_index(
        'ix_split_notifications_user_status_created', 'split_notifications',
        ['sent_by_user_id', 'status', 'created_at'],
    )


def downgrade() -> None:
    op.drop_table('split_notifications')
    op.drop_index('ix_split_participants_contact_id', table_name='split_participants')
    op.drop_constraint('fk_split_participants_contact', 'split_participants', type_='foreignkey')
    op.drop_column('split_participants', 'contact_id')
    op.drop_column('split_contacts', 'phone_e164')
    op.drop_column('users', 'upi_id')
