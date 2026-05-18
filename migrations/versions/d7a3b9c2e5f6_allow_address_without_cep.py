"""allow address without cep

Revision ID: d7a3b9c2e5f6
Revises: c6d2e8f1a9b4
Create Date: 2026-05-18 12:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd7a3b9c2e5f6'
down_revision = 'c6d2e8f1a9b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('endereco', schema=None) as batch_op:
        batch_op.alter_column('cep', existing_type=sa.String(length=9), nullable=True)


def downgrade():
    with op.batch_alter_table('endereco', schema=None) as batch_op:
        batch_op.alter_column('cep', existing_type=sa.String(length=9), nullable=False)
