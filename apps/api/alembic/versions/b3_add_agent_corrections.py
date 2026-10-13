from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3_add_agent_corrections'
down_revision: str | None = 'b2_add_chat_threads_messages'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'agent_corrections',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('thread_id', sa.String(length=120), nullable=False),
        sa.Column('original_proposal', sa.JSON(), nullable=False),
        sa.Column('corrected_proposal', sa.JSON(), nullable=False),
        sa.Column('user_message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_corrections_user_id'), 'agent_corrections', ['user_id'], unique=False)
    op.create_index(op.f('ix_agent_corrections_thread_id'), 'agent_corrections', ['thread_id'], unique=False)
    op.create_index(op.f('ix_agent_corrections_created_at'), 'agent_corrections', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_corrections_created_at'), table_name='agent_corrections')
    op.drop_index(op.f('ix_agent_corrections_thread_id'), table_name='agent_corrections')
    op.drop_index(op.f('ix_agent_corrections_user_id'), table_name='agent_corrections')
    op.drop_table('agent_corrections')
