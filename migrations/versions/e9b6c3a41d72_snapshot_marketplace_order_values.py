"""Snapshot marketplace seller and fee values on order items.

Revision ID: e9b6c3a41d72
Revises: c4a8f2d71e90
Create Date: 2026-07-29 21:35:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e9b6c3a41d72'
down_revision = 'c4a8f2d71e90'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('order_item', sa.Column('seller_unit_amount', sa.Numeric(10, 2), nullable=True))
    op.add_column('order_item', sa.Column('platform_fee_amount', sa.Numeric(10, 2), nullable=True))
    op.add_column('order_item', sa.Column('seller_type', sa.String(length=20), nullable=True))
    op.add_column('order_item', sa.Column('seller_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('order_item', 'seller_id')
    op.drop_column('order_item', 'seller_type')
    op.drop_column('order_item', 'platform_fee_amount')
    op.drop_column('order_item', 'seller_unit_amount')
