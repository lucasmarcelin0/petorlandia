"""create plantonista escalas

Revision ID: 9c54d2177bf8
Revises: c8f6b9a0d5d9
Create Date: 2025-11-15 21:37:24.276757

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c54d2177bf8'
down_revision = 'c8f6b9a0d5d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'plantonista_escalas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('medico_id', sa.Integer(), nullable=True),
        sa.Column('medico_nome', sa.String(length=150), nullable=False),
        sa.Column('medico_cnpj', sa.String(length=20), nullable=True),
        sa.Column('turno', sa.String(length=80), nullable=False),
        sa.Column('inicio', sa.DateTime(), nullable=False),
        sa.Column('fim', sa.DateTime(), nullable=False),
        sa.Column('valor_previsto', sa.Numeric(14, 2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='agendado'),
        sa.Column('nota_fiscal_recebida', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('retencao_validada', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('realizado_em', sa.DateTime(), nullable=True),
        sa.Column('pj_payment_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('valor_previsto >= 0', name='ck_plantonista_valor_positive'),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinica.id']),
        sa.ForeignKeyConstraint(['medico_id'], ['veterinario.id']),
        sa.ForeignKeyConstraint(['pj_payment_id'], ['pj_payments.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_plantonista_escalas_clinic_id', 'plantonista_escalas', ['clinic_id'])
    op.create_index('ix_plantonista_escalas_medico_id', 'plantonista_escalas', ['medico_id'])
    op.create_index('ix_plantonista_escalas_inicio', 'plantonista_escalas', ['inicio'])


def downgrade():
    op.drop_index('ix_plantonista_escalas_inicio', table_name='plantonista_escalas')
    op.drop_index('ix_plantonista_escalas_medico_id', table_name='plantonista_escalas')
    op.drop_index('ix_plantonista_escalas_clinic_id', table_name='plantonista_escalas')
    op.drop_table('plantonista_escalas')
