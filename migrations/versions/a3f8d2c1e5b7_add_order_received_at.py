"""Add order.received_at for buyer delivery confirmation

Revision ID: a3f8d2c1e5b7
Revises: b2d4f6a8c1e9
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3f8d2c1e5b7'
down_revision = 'b2d4f6a8c1e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('received_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('received_at')
