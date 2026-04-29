"""add intervalo_min_max_horas to dose_medicamento

Revision ID: d1a3f7c2b9e8
Revises: c4d9e7a1f6b2, f3b9a2c7d4e6
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1a3f7c2b9e8'
down_revision = ('c4d9e7a1f6b2', 'f3b9a2c7d4e6')
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('dose_medicamento') as batch:
        batch.add_column(sa.Column('intervalo_min_horas', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('intervalo_max_horas', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('dose_medicamento') as batch:
        batch.drop_column('intervalo_max_horas')
        batch.drop_column('intervalo_min_horas')
