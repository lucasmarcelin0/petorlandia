"""add attended_by to pmo vaccination visit

Revision ID: d2e7f1a8b3c5
Revises: c5d9a1e7f3b4
Create Date: 2026-05-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd2e7f1a8b3c5'
down_revision = 'c5d9a1e7f3b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attended_by', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.drop_column('attended_by')
