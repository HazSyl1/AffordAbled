"""Support reversible deletion of transaction-backed splits.

Revision ID: aa5_reversible_split_transactions
Revises: aa4_user_tiers_usage
"""

import sqlalchemy as sa

from alembic import op

revision = 'aa5_reversible_split_transactions'
down_revision = 'aa4_user_tiers_usage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('splits', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_splits_deleted_at', 'splits', ['deleted_at'])


def downgrade() -> None:
    op.drop_index('ix_splits_deleted_at', table_name='splits')
    op.drop_column('splits', 'deleted_at')
