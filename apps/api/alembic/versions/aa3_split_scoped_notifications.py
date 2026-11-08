"""Scope reminder campaigns and idempotency to a split."""

import sqlalchemy as sa

from alembic import op

revision = 'aa3_split_scoped_notifications'
down_revision = 'aa2_email_split_notifications'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('uq_split_notification_idempotency', 'split_notifications', type_='unique')
    op.create_unique_constraint(
        'uq_split_notification_campaign_recipient',
        'split_notifications',
        ['sent_by_user_id', 'idempotency_key', 'split_participant_id'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_split_notification_campaign_recipient', 'split_notifications', type_='unique')
    duplicate_campaigns = sa.text("""
        DELETE FROM split_notifications current
        USING split_notifications keeper
        WHERE current.sent_by_user_id = keeper.sent_by_user_id
          AND current.idempotency_key = keeper.idempotency_key
          AND current.id > keeper.id
    """)
    op.execute(duplicate_campaigns)
    op.create_unique_constraint(
        'uq_split_notification_idempotency',
        'split_notifications',
        ['sent_by_user_id', 'idempotency_key'],
    )
