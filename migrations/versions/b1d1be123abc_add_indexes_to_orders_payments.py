"""add indexes to orders and payments

Revision ID: b1d1be123abc
Revises: e8aff173e0fe
Create Date: 2025-07-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b1d1be123abc'
down_revision = 'e8aff173e0fe'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_order_user_id', 'order', ['user_id'])
    op.create_index('ix_payment_user_id', 'payment', ['user_id'])
    op.create_index('ix_payment_status', 'payment', ['status'])


def downgrade():
    op.drop_index('ix_payment_status', table_name='payment')
    op.drop_index('ix_payment_user_id', table_name='payment')
    op.drop_index('ix_order_user_id', table_name='order')
