"""create pj payments table

Revision ID: a99a4be65f35
Revises: b0415360aa2f
Create Date: 2025-05-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a99a4be65f35'
down_revision = 'b0415360aa2f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pj_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('prestador_nome', sa.String(length=150), nullable=False),
        sa.Column('prestador_cnpj', sa.String(length=20), nullable=False),
        sa.Column('nota_fiscal_numero', sa.String(length=80), nullable=True),
        sa.Column('valor', sa.Numeric(14, 2), nullable=False),
        sa.Column('data_servico', sa.Date(), nullable=False),
        sa.Column('data_pagamento', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pendente'),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('valor >= 0', name='ck_pj_payments_valor_positive'),
        sa.CheckConstraint("status IN ('pendente','pago')", name='ck_pj_payments_status'),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pj_payments_clinic_id', 'pj_payments', ['clinic_id'])
    op.create_index('ix_pj_payments_data_servico', 'pj_payments', ['data_servico'])


def downgrade():
    op.drop_index('ix_pj_payments_data_servico', table_name='pj_payments')
    op.drop_index('ix_pj_payments_clinic_id', table_name='pj_payments')
    op.drop_table('pj_payments')
