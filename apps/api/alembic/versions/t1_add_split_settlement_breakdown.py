from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 't1_split_settlement_breakdown'
down_revision: str | None = 's2_standalone_owed'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column('splits', sa.Column('settlement_breakdown', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('splits', 'settlement_breakdown')
