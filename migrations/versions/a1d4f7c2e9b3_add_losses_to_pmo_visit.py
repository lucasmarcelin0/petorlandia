"""add losses to pmo vaccination visit

Revision ID: a1d4f7c2e9b3
Revises: f2c6a9d1e4b8
Create Date: 2026-06-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a1d4f7c2e9b3'
down_revision = 'f2c6a9d1e4b8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('losses', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade():
    with op.batch_alter_table('pmo_vaccination_visit', schema=None) as batch_op:
        batch_op.drop_column('losses')
