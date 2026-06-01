"""add pmo requested date

Revision ID: a5c7e9d2f4b8
Revises: fb8c2d1e4a6f
Create Date: 2026-06-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a5c7e9d2f4b8'
down_revision = 'fb8c2d1e4a6f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requested_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.drop_column('requested_date')
