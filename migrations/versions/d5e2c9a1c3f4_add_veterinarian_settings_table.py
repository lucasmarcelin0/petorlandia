"""Add veterinarian settings table

Revision ID: d5e2c9a1c3f4
Revises: 3b4c5d6e7f80
Create Date: 2024-05-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from decimal import Decimal
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'd5e2c9a1c3f4'
down_revision = '3b4c5d6e7f80'
branch_labels = None
depends_on = None


def upgrade():
    # Check if table already exists
    ctx = op.get_context()
    inspector = sa.inspect(ctx.bind)
    
    if 'veterinarian_settings' not in inspector.get_table_names():
        op.create_table(
            'veterinarian_settings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('membership_price', sa.Numeric(10, 2), nullable=False, server_default='60.00'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id')
        )

        settings_table = sa.table(
            'veterinarian_settings',
            sa.column('id', sa.Integer()),
            sa.column('membership_price', sa.Numeric(10, 2)),
            sa.column('created_at', sa.DateTime()),
            sa.column('updated_at', sa.DateTime()),
        )

        now = datetime.utcnow()
        op.bulk_insert(
            settings_table,
            [
                {
                    'id': 1,
                    'membership_price': Decimal('60.00'),
                    'created_at': now,
                    'updated_at': now,
                }
            ],
        )


def downgrade():
    op.drop_table('veterinarian_settings')
