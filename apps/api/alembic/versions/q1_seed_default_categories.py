import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = 'q1_seed_default_categories'
down_revision: str | None = 'p1_separate_application_checkpoints'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ('Food', 'expense'),
    ('Groceries', 'expense'),
    ('Transport', 'expense'),
    ('Bills', 'expense'),
    ('Shopping', 'expense'),
    ('Health', 'expense'),
    ('Entertainment', 'expense'),
    ('Misc', 'expense'),
    ('Salary', 'income'),
    ('Other Income', 'income'),
)


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
            rows.append(
                {
                    'id': uuid.uuid4(),
                    'user_id': user_id,
                    'name': name,
                    'icon': None,
                    'color': None,
                    'type': category_type,
                    'created_at': now,
                }
            )
            existing_keys.add(key)

    if rows:
        op.bulk_insert(categories, rows)


def downgrade() -> None:
    # Seeded categories become user-owned data and may have been edited or used
    # by transactions. Keep them on downgrade rather than risk deleting data.
    pass
