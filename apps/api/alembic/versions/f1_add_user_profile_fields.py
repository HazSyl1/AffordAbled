from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1_add_user_profile_fields'
down_revision: str | None = 'c5d2a1e4f9b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('name', sa.String(length=120), nullable=False, server_default='User'),
    )
    op.add_column('users', sa.Column('date_of_birth', sa.Date(), nullable=True))
    op.alter_column('users', 'name', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'date_of_birth')
    op.drop_column('users', 'name')
