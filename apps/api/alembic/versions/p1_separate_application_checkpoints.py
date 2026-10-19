from collections.abc import Sequence

from sqlalchemy import inspect

from alembic import op

revision: str = 'p1_separate_application_checkpoints'
down_revision: str | None = 'o1_add_shared_memory'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'checkpoints' not in tables:
        return

    columns = {column['name'] for column in inspector.get_columns('checkpoints')}
    app_columns = {'id', 'user_id', 'thread_id', 'state_json', 'created_at', 'updated_at'}
    if not app_columns.issubset(columns):
        # A correctly shaped LangGraph table already owns this name.
        return

    if 'application_checkpoints' in tables:
        raise RuntimeError(
            'Both app-owned checkpoints tables exist; resolve the duplicate before applying this migration.'
        )

    op.rename_table('checkpoints', 'application_checkpoints')

    # LangGraph may have recorded its migrations even though CREATE TABLE IF
    # NOT EXISTS skipped creation of its checkpoint table due to the name
    # collision. Remove only its version ledger so AsyncPostgresSaver.setup()
    # can safely replay its idempotent migrations and create the correct table.
    if 'checkpoint_migrations' in tables:
        op.drop_table('checkpoint_migrations')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if 'application_checkpoints' not in tables:
        return

    columns = {column['name'] for column in inspector.get_columns('application_checkpoints')}
    app_columns = {'id', 'user_id', 'thread_id', 'state_json', 'created_at', 'updated_at'}
    if not app_columns.issubset(columns):
        return

    if 'checkpoints' in tables:
        raise RuntimeError(
            'Cannot move application_checkpoints back to checkpoints while the LangGraph table exists.'
        )

    op.rename_table('application_checkpoints', 'checkpoints')
