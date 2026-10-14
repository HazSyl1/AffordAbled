from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4_add_exports_table'
down_revision: str | None = 'b3_add_agent_corrections'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'exports',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('format', sa.String(length=24), nullable=False),
        sa.Column('download_url', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_exports_user_id'), 'exports', ['user_id'], unique=False)
    op.create_index(op.f('ix_exports_expires_at'), 'exports', ['expires_at'], unique=False)
    op.create_index(op.f('ix_exports_created_at'), 'exports', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_exports_created_at'), table_name='exports')
    op.drop_index(op.f('ix_exports_expires_at'), table_name='exports')
    op.drop_index(op.f('ix_exports_user_id'), table_name='exports')
    op.drop_table('exports')
