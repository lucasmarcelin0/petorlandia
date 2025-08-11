"""add latitude and longitude to endereco

Revision ID: 0e1f2d3c4b5a
Revises: c1f5f3d4f4b2
Create Date: 2024-08-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0e1f2d3c4b5a'
down_revision = 'c1f5f3d4f4b2'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('endereco', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('endereco', sa.Column('longitude', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('endereco', 'longitude')
    op.drop_column('endereco', 'latitude')
