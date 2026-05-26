"""add lote column to vacina

Revision ID: b9e3f5a2c7d8
Revises: a8d2e4f9c1b7
Create Date: 2026-05-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b9e3f5a2c7d8'
down_revision = 'a8d2e4f9c1b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vacina', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lote', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('vacina', schema=None) as batch_op:
        batch_op.drop_column('lote')
