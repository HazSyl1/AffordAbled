from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'v1_standalone_debt_direction'
down_revision: str | None = 'u1_complex_settlement'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        'splits',
        sa.Column('direction', sa.String(length=20), nullable=False, server_default='to_you'),
    )


def downgrade() -> None:
    payable_count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM splits WHERE transaction_id IS NULL AND direction = 'by_you'")
    )
    if payable_count:
        raise RuntimeError('Remove or convert standalone debts you owe before downgrading this revision.')
    op.drop_column('splits', 'direction')
