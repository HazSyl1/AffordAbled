"""Add email recipients to split notifications."""

import sqlalchemy as sa

from alembic import op

revision = 'aa2_email_split_notifications'
down_revision = 'aa1_split_notifications'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('split_contacts', sa.Column('email', sa.String(length=320), nullable=True))
    op.add_column('split_notifications', sa.Column('recipient_email', sa.String(length=320), nullable=True))
    op.add_column('split_notifications', sa.Column('email_subject', sa.String(length=255), nullable=True))
    op.alter_column('split_notifications', 'recipient_phone_e164', nullable=True)
    op.drop_constraint('ck_split_notifications_channel', 'split_notifications', type_='check')
    op.create_check_constraint(
        'ck_split_notifications_channel', 'split_notifications', "channel IN ('sms', 'email')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_split_notifications_channel', 'split_notifications', type_='check')
    op.create_check_constraint(
        'ck_split_notifications_channel', 'split_notifications', "channel = 'sms'",
    )
    op.alter_column('split_notifications', 'recipient_phone_e164', nullable=False)
    op.drop_column('split_notifications', 'email_subject')
    op.drop_column('split_notifications', 'recipient_email')
    op.drop_column('split_contacts', 'email')
