"""add clinic marketplace shipping

Revision ID: b5e1c7a9d4f2
Revises: a4f8c2d9e1b7
Create Date: 2026-05-18 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b5e1c7a9d4f2'
down_revision = 'a4f8c2d9e1b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clinica', schema=None) as batch_op:
        batch_op.add_column(sa.Column('modo_entrega', sa.String(length=20), nullable=False, server_default='plataforma'))
        batch_op.add_column(sa.Column('valor_frete', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('pedido_minimo_entrega', sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column('prazo_entrega_min', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('prazo_entrega_max', sa.Integer(), nullable=True))

    with op.batch_alter_table('store_payment_account', schema=None) as batch_op:
        batch_op.alter_column('casa_de_racao_id', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('clinica_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_store_payment_account_clinica_id'), ['clinica_id'], unique=False)
        batch_op.create_foreign_key(None, 'clinica', ['clinica_id'], ['id'], ondelete='CASCADE')
        batch_op.create_unique_constraint('uq_store_payment_clinic_provider', ['clinica_id', 'provider'])


def downgrade():
    with op.batch_alter_table('store_payment_account', schema=None) as batch_op:
        batch_op.drop_constraint('uq_store_payment_clinic_provider', type_='unique')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_store_payment_account_clinica_id'))
        batch_op.drop_column('clinica_id')
        batch_op.alter_column('casa_de_racao_id', existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table('clinica', schema=None) as batch_op:
        batch_op.drop_column('prazo_entrega_max')
        batch_op.drop_column('prazo_entrega_min')
        batch_op.drop_column('pedido_minimo_entrega')
        batch_op.drop_column('valor_frete')
        batch_op.drop_column('modo_entrega')
