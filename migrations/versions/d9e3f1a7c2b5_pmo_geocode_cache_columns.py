"""pmo geocode cache columns

Revision ID: d9e3f1a7c2b5
Revises: b8f4c2d6e9a1
Create Date: 2026-06-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd9e3f1a7c2b5'
down_revision = 'b8f4c2d6e9a1'
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
