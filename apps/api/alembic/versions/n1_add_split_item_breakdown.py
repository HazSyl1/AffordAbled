from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'n1_add_split_item_breakdown'
down_revision: str | None = 'm1_add_split_contacts'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('splits', sa.Column('item_breakdown', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('splits', 'item_breakdown')
