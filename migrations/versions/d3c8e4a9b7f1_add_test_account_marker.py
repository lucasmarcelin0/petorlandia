"""Add durable marker for internally-created test accounts."""

from alembic import op
import sqlalchemy as sa


revision = 'd3c8e4a9b7f1'
down_revision = 'e5b3c7d9a1f2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user',
        sa.Column('is_test_account', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('user', sa.Column('test_label', sa.String(length=120), nullable=True))
    op.create_index('ix_user_is_test_account', 'user', ['is_test_account'])


def downgrade():
    op.drop_index('ix_user_is_test_account', table_name='user')
    op.drop_column('user', 'test_label')
    op.drop_column('user', 'is_test_account')
