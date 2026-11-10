"""Store full balance settlement history for hosted payment pages.

Revision ID: aa6_settlement_details
Revises: aa5_reversible_split_transactions
"""

import sqlalchemy as sa

from alembic import op


revision = 'aa6_settlement_details'
down_revision = 'aa5_reversible_split_transactions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('split_notifications', sa.Column('settlement_details', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('split_notifications', 'settlement_details')
