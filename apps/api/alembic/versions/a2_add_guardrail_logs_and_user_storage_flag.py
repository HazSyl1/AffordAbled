from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a2_add_guardrail_logs_and_user_storage_flag'
down_revision: str | None = 'f1_add_user_profile_fields'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('conversation_storage_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        'guardrail_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('thread_id', sa.String(length=120), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('intent', sa.String(length=64), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('triggered', sa.Boolean(), nullable=False),
        sa.Column('layer', sa.String(length=32), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_guardrail_logs_user_id'), 'guardrail_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_guardrail_logs_thread_id'), 'guardrail_logs', ['thread_id'], unique=False)
    op.create_index(op.f('ix_guardrail_logs_triggered'), 'guardrail_logs', ['triggered'], unique=False)
    op.create_index(op.f('ix_guardrail_logs_expires_at'), 'guardrail_logs', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_guardrail_logs_expires_at'), table_name='guardrail_logs')
    op.drop_index(op.f('ix_guardrail_logs_triggered'), table_name='guardrail_logs')
    op.drop_index(op.f('ix_guardrail_logs_thread_id'), table_name='guardrail_logs')
    op.drop_index(op.f('ix_guardrail_logs_user_id'), table_name='guardrail_logs')
    op.drop_table('guardrail_logs')

    op.drop_column('users', 'conversation_storage_enabled')
