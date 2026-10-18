from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'm1_add_split_contacts'
down_revision: str | None = 'l1_track_export_file_hash'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'split_contacts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('normalized_name', sa.String(length=100), nullable=False),
        sa.Column('dietary_preference', sa.String(length=24), nullable=True),
        sa.Column('preference_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('user_id', 'normalized_name', name='uq_split_contact_user_name'),
    )
    op.create_index('ix_split_contacts_user_id', 'split_contacts', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_split_contacts_user_id', table_name='split_contacts')
    op.drop_table('split_contacts')
