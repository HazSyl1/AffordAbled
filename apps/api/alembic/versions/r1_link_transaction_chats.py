from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'r1_tx_chat_link'
down_revision: str | None = 'q1_seed_default_categories'
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column('chat_threads', sa.Column('transaction_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_chat_threads_transaction_id_transactions', 'chat_threads', 'transactions', ['transaction_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_chat_threads_transaction_id', 'chat_threads', ['transaction_id'])
    op.create_unique_constraint('uq_chat_threads_user_transaction', 'chat_threads', ['user_id', 'transaction_id'])


def downgrade() -> None:
    op.drop_constraint('uq_chat_threads_user_transaction', 'chat_threads', type_='unique')
    op.drop_index('ix_chat_threads_transaction_id', table_name='chat_threads')
    op.drop_constraint('fk_chat_threads_transaction_id_transactions', 'chat_threads', type_='foreignkey')
    op.drop_column('chat_threads', 'transaction_id')
