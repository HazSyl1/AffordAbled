from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 's2_standalone_owed'
down_revision: str | None = 's1_chat_memory_analysis'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column('splits', 'transaction_id', existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    owed_count = op.get_bind().scalar(sa.text('SELECT count(*) FROM splits WHERE transaction_id IS NULL'))
    if owed_count:
        raise RuntimeError('Remove or migrate standalone money owed entries before downgrading this revision.')
    op.alter_column('splits', 'transaction_id', existing_type=sa.Uuid(), nullable=False)
