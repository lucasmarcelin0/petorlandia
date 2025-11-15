"""create plantonista_escalas table

Revision ID: 1f8d8d4bd6e5
Revises: 2f8a5b4d1234
Create Date: 2025-02-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '1f8d8d4bd6e5'
down_revision = '2f8a5b4d1234'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return inspector.has_table(table_name)


def upgrade():
    if _table_exists('plantonista_escalas'):
        return

    op.create_table(
        'plantonista_escalas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('clinic_id', sa.Integer(), sa.ForeignKey('clinica.id'), nullable=False),
        sa.Column('medico_id', sa.Integer(), sa.ForeignKey('veterinario.id'), nullable=True),
        sa.Column('medico_nome', sa.String(length=150), nullable=False),
        sa.Column('medico_cnpj', sa.String(length=20), nullable=True),
        sa.Column('turno', sa.String(length=80), nullable=False),
        sa.Column('inicio', sa.DateTime(), nullable=False),
        sa.Column('fim', sa.DateTime(), nullable=False),
        sa.Column('plantao_horas', sa.Numeric(5, 2), nullable=True),
        sa.Column('valor_previsto', sa.Numeric(14, 2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='agendado'),
        sa.Column('nota_fiscal_recebida', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('retencao_validada', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('realizado_em', sa.DateTime(), nullable=True),
        sa.Column('pj_payment_id', sa.Integer(), sa.ForeignKey('pj_payments.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint('valor_previsto >= 0', name='ck_plantonista_valor_positive'),
    )
    op.create_index('ix_plantonista_escalas_clinic_id', 'plantonista_escalas', ['clinic_id'])
    op.create_index('ix_plantonista_escalas_medico_id', 'plantonista_escalas', ['medico_id'])
    op.create_index('ix_plantonista_escalas_inicio', 'plantonista_escalas', ['inicio'])


def downgrade():
    if not _table_exists('plantonista_escalas'):
        return

    op.drop_index('ix_plantonista_escalas_inicio', table_name='plantonista_escalas')
    op.drop_index('ix_plantonista_escalas_medico_id', table_name='plantonista_escalas')
    op.drop_index('ix_plantonista_escalas_clinic_id', table_name='plantonista_escalas')
    op.drop_table('plantonista_escalas')
