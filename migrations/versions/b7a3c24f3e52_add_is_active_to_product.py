"""add is_active flag to product

Revision ID: b7a3c24f3e52
Revises: ffcc9c32861f
Create Date: 2025-10-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7a3c24f3e52'
down_revision = 'ffcc9c32861f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'product',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('product', 'is_active', server_default=None)


def downgrade():
    op.drop_column('product', 'is_active')
