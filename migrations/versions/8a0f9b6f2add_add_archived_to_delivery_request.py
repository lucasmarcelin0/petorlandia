"""
Add archived flag to delivery requests

Revision ID: 8a0f9b6f2add
Revises: 6ec5a8a3dea4
Create Date: 2024-08-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8a0f9b6f2add'
down_revision = '6ec5a8a3dea4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('delivery_request', sa.Column('archived', sa.Boolean(), nullable=False, server_default='0'))
    op.alter_column('delivery_request', 'archived', server_default=None)


def downgrade():
    op.drop_column('delivery_request', 'archived')
