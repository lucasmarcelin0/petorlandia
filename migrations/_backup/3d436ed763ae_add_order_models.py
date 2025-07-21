"""add order models"

Revision ID: 3d436ed763ae
Revises: dee1b546c208
Create Date: 2025-07-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3d436ed763ae'
down_revision = 'dee1b546c208'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'order',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'order_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('item_name', sa.String(length=100), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['order.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'delivery_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['order.id']),
        sa.ForeignKeyConstraint(['requested_by_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    op.drop_table('delivery_request')
    op.drop_table('order_item')
    op.drop_table('order')
