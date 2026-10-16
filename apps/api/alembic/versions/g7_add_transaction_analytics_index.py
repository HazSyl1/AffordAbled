"""Add the composite index used by analytics windows."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g7_add_transaction_analytics_index"
down_revision: str | None = "f2_add_default_account"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_transactions_user_occurred_active",
        "transactions",
        ["user_id", "occurred_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_user_occurred_active", table_name="transactions")
