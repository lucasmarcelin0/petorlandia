"""add is_active to product

Revision ID: 1f0a1c2d3e45
Revises: ffcc9c32861f
Create Date: 2025-08-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f0a1c2d3e45'
down_revision = 'ffcc9c32861f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'product',
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute("UPDATE product SET is_active = TRUE")


def downgrade():
    op.drop_column('product', 'is_active')
