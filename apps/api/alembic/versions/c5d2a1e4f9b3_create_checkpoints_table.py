from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5d2a1e4f9b3'
down_revision: str | None = 'b1f4d8a2c7e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'checkpoints',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('thread_id', sa.String(length=120), nullable=False),
        sa.Column('state_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'thread_id', name='uq_checkpoints_user_thread'),
    )
    op.create_index(op.f('ix_checkpoints_thread_id'), 'checkpoints', ['thread_id'], unique=False)
    op.create_index(op.f('ix_checkpoints_user_id'), 'checkpoints', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_checkpoints_user_id'), table_name='checkpoints')
    op.drop_index(op.f('ix_checkpoints_thread_id'), table_name='checkpoints')
    op.drop_table('checkpoints')
