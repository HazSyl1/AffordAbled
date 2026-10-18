from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'i1_add_export_content'
down_revision: str | None = 'h1_add_splits'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('exports', sa.Column('content', sa.LargeBinary(), nullable=True))
    op.add_column('exports', sa.Column('content_type', sa.String(length=120), nullable=True))
    op.add_column('exports', sa.Column('filename', sa.String(length=255), nullable=True))
    op.add_column('exports', sa.Column('row_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('exports', 'row_count')
    op.drop_column('exports', 'filename')
    op.drop_column('exports', 'content_type')
    op.drop_column('exports', 'content')
