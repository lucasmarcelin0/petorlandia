"""add feed store shipping fields

Revision ID: a4f8c2d9e1b7
Revises: 9c4e1a7b2d6f
Create Date: 2026-05-18 00:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a4f8c2d9e1b7'
down_revision = '9c4e1a7b2d6f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('casa_de_racao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('valor_frete', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('pedido_minimo_entrega', sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column('prazo_entrega_min', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('prazo_entrega_max', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('casa_de_racao', schema=None) as batch_op:
        batch_op.drop_column('prazo_entrega_max')
        batch_op.drop_column('prazo_entrega_min')
        batch_op.drop_column('pedido_minimo_entrega')
        batch_op.drop_column('valor_frete')
