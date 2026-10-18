from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'k1_version_export_reports'
down_revision: str | None = 'j1_add_transaction_imports'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('exports', sa.Column('report_schema_version', sa.Integer(), nullable=True))
    # Previously generated files contain internal IDs and notes; revoke their download window.
    op.execute(
        sa.text("UPDATE exports SET expires_at = now() WHERE content IS NOT NULL AND expires_at > now()")
    )


def downgrade() -> None:
    op.drop_column('exports', 'report_schema_version')
