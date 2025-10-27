"""add user privacy flag

Revision ID: 8c5e4d7c9b1a
Revises: 2f9a0dc93f25
Create Date: 2024-05-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c5e4d7c9b1a'
down_revision = '2f9a0dc93f25'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user',
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(
        "UPDATE \"user\" SET is_private = CASE WHEN clinica_id IS NULL THEN FALSE ELSE TRUE END"
    )


def downgrade():
    op.drop_column('user', 'is_private')
