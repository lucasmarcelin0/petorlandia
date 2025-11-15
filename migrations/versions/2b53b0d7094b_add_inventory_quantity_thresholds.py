"""add inventory quantity thresholds

Revision ID: 2b53b0d7094b
Revises: f51ee31de1dd
Create Date: 2025-11-15 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b53b0d7094b'
down_revision = 'f51ee31de1dd'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'clinic_inventory_item',
        sa.Column('min_quantity', sa.Integer(), nullable=True)
    )
    op.add_column(
        'clinic_inventory_item',
        sa.Column('max_quantity', sa.Integer(), nullable=True)
    )


def downgrade():
    op.drop_column('clinic_inventory_item', 'max_quantity')
    op.drop_column('clinic_inventory_item', 'min_quantity')
