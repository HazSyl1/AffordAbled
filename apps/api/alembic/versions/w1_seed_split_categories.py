"""Seed Split expense and income categories for every wallet.

Revision ID: w1_split_categories
Revises: v1_standalone_debt_direction
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = 'w1_split_categories'
down_revision: str | None = 'v1_standalone_debt_direction'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


DEFAULT_CATEGORIES = (('Split', 'expense'), ('Split', 'income'))


def upgrade() -> None:
    bind = op.get_bind()
    users = bind.execute(sa.text('SELECT id FROM users')).all()
    existing = bind.execute(sa.text('SELECT user_id, name, type FROM categories')).all()
    existing_keys = {(str(user_id), name.casefold(), category_type) for user_id, name, category_type in existing}
    now = datetime.now(UTC)
    categories = sa.table(
        'categories',
        sa.column('id', sa.Uuid()),
        sa.column('user_id', sa.Uuid()),
        sa.column('name', sa.String(length=120)),
        sa.column('icon', sa.String(length=64)),
        sa.column('color', sa.String(length=32)),
        sa.column('type', sa.String(length=20)),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    rows = []
    for (user_id,) in users:
        for name, category_type in DEFAULT_CATEGORIES:
            key = (str(user_id), name.casefold(), category_type)
            if key in existing_keys:
                continue
            rows.append({
                'id': uuid.uuid4(), 'user_id': user_id, 'name': name, 'icon': None,
                'color': None, 'type': category_type, 'created_at': now,
            })
    if rows:
        op.bulk_insert(categories, rows)


def downgrade() -> None:
    # These categories may have been used by wallet transactions; preserve user data.
    pass
