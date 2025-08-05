"""Add worker location to delivery request

Revision ID: c1f5f3d4f4b2
Revises: 8a0f9b6f2add
Create Date: 2024-08-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c1f5f3d4f4b2'
down_revision = '8a0f9b6f2add'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('delivery_request', sa.Column('worker_latitude', sa.Float(), nullable=True))
    op.add_column('delivery_request', sa.Column('worker_longitude', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('delivery_request', 'worker_longitude')
    op.drop_column('delivery_request', 'worker_latitude')
