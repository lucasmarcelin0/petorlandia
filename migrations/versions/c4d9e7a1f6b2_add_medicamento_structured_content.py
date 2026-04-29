"""add structured medication content json

Revision ID: c4d9e7a1f6b2
Revises: b8c3d5e9f2a7
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d9e7a1f6b2'
down_revision = 'b8c3d5e9f2a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('medicamento') as batch:
        batch.add_column(sa.Column('conteudo_estruturado', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('medicamento') as batch:
        batch.drop_column('conteudo_estruturado')
