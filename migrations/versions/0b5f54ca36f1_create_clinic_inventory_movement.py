"""create clinic inventory movement table

Revision ID: 0b5f54ca36f1
Revises: 2b53b0d7094b
Create Date: 2025-11-15 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0b5f54ca36f1'
down_revision = '2b53b0d7094b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'clinic_inventory_movement',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('clinica_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('quantity_change', sa.Integer(), nullable=False),
        sa.Column('quantity_before', sa.Integer(), nullable=False),
        sa.Column('quantity_after', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['clinica_id'], ['clinica.id']),
        sa.ForeignKeyConstraint(['item_id'], ['clinic_inventory_item.id'], ondelete='CASCADE'),
    )


def downgrade():
    op.drop_table('clinic_inventory_movement')
