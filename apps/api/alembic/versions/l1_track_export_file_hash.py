from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'l1_track_export_file_hash'
down_revision: str | None = 'k1_version_export_reports'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('exports', sa.Column('file_sha256', sa.String(length=64), nullable=True))
    op.create_index('ix_exports_user_file_sha256', 'exports', ['user_id', 'file_sha256'])


def downgrade() -> None:
    op.drop_index('ix_exports_user_file_sha256', table_name='exports')
    op.drop_column('exports', 'file_sha256')
