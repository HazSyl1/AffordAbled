"""Allow people to be forgotten without deleting historical split records.

Revision ID: aa7_archive_split_people
Revises: aa6_settlement_details
"""

import sqlalchemy as sa

from alembic import op


revision = 'aa7_archive_split_people'
down_revision = 'aa6_settlement_details'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'split_contacts',
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('split_contacts', 'is_archived')
