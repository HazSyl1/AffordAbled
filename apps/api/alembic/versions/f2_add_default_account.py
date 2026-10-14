from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2_add_default_account'
down_revision: str | None = 'b4_add_exports_table'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'accounts',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    accounts = sa.table(
        'accounts',
        sa.column('id', sa.Uuid()),
        sa.column('user_id', sa.Uuid()),
        sa.column('is_active', sa.Boolean()),
        sa.column('is_default', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(accounts.c.id, accounts.c.user_id, accounts.c.is_active).order_by(
            accounts.c.user_id,
            accounts.c.created_at,
            accounts.c.id,
        )
    ).all()

    chosen_by_user: dict[object, object] = {}
    for account_id, user_id, is_active in rows:
        if is_active and user_id not in chosen_by_user:
            chosen_by_user[user_id] = account_id

    for _user_id, account_id in chosen_by_user.items():
        connection.execute(
            accounts.update()
            .where(accounts.c.id == account_id)
            .values(is_default=True)
        )

    op.create_index(
        'uq_accounts_one_default_per_user',
        'accounts',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text('is_default = true'),
        sqlite_where=sa.text('is_default = 1'),
    )


def downgrade() -> None:
    op.drop_index('uq_accounts_one_default_per_user', table_name='accounts')
    op.drop_column('accounts', 'is_default')
