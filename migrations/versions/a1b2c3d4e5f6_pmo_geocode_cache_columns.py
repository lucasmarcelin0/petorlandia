"""pmo geocode cache columns

Revision ID: a1b2c3d4e5f6
Revises: fb8c2d1e4a6f
Create Date: 2026-06-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'fb8c2d1e4a6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('pmo_vaccination_visit', sa.Column('geocode_lat', sa.Float(), nullable=True))
    op.add_column('pmo_vaccination_visit', sa.Column('geocode_lng', sa.Float(), nullable=True))
    op.add_column('pmo_vaccination_visit', sa.Column('geocode_address_key', sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column('pmo_vaccination_visit', 'geocode_address_key')
    op.drop_column('pmo_vaccination_visit', 'geocode_lng')
    op.drop_column('pmo_vaccination_visit', 'geocode_lat')
