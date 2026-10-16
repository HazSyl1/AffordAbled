"""Allow Alembic revision identifiers longer than its default 32 characters."""

from collections.abc import Sequence

from alembic import op

revision: str = 'f3_widen_alembic_version'
down_revision: str | None = 'f2_add_default_account'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)')


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)')
