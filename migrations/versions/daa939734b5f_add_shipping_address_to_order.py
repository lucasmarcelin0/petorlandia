"""add shipping_address to order

Revision ID: daa939734b5f
Revises: b1d1be123abc
Create Date: 2025-07-26 14:03:24.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'daa939734b5f'
down_revision = 'b1d1be123abc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('shipping_address', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('shipping_address')
