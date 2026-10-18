from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'j1_add_transaction_imports'
down_revision: str | None = 'i1_add_export_content'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'transaction_imports',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'file_hash', name='uq_transaction_import_user_hash'),
    )
    op.create_index(op.f('ix_transaction_imports_user_id'), 'transaction_imports', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_transaction_imports_user_id'), table_name='transaction_imports')
    op.drop_table('transaction_imports')
