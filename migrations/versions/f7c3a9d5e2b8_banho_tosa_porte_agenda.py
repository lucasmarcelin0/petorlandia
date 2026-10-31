"""banho e tosa: porte por faixa de peso, cobrança avulsa e agenda da loja

Revision ID: f7c3a9d5e2b8
Revises: e6b2d8f4c9a1
Create Date: 2026-10-31 22:00:00.000000

Colunas opcionais em grooming_plan (planos existentes continuam mensais e
para qualquer porte) e a tabela nova grooming_sessao.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f7c3a9d5e2b8'
down_revision = 'e6b2d8f4c9a1'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table):
    return {col['name'] for col in _inspector().get_columns(table)}


def upgrade():
    colunas = _columns('grooming_plan')
    if 'peso_min_kg' not in colunas:
        op.add_column('grooming_plan', sa.Column('peso_min_kg', sa.Numeric(precision=6, scale=2), nullable=True))
    if 'peso_max_kg' not in colunas:
        op.add_column('grooming_plan', sa.Column('peso_max_kg', sa.Numeric(precision=6, scale=2), nullable=True))
    if 'cobranca' not in colunas:
        op.add_column(
            'grooming_plan',
            sa.Column('cobranca', sa.String(length=10), nullable=False, server_default='mensal'),
        )

    if 'grooming_sessao' not in set(_inspector().get_table_names()):
        op.create_table(
            'grooming_sessao',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('casa_de_racao_id', sa.Integer(), nullable=False),
            sa.Column('plan_id', sa.Integer(), nullable=True),
            sa.Column('subscription_id', sa.Integer(), nullable=True),
            sa.Column('animal_id', sa.Integer(), nullable=False),
            sa.Column('agendado_para', sa.DateTime(timezone=True), nullable=False),
            sa.Column('status', sa.String(length=12), nullable=False, server_default='agendado'),
            sa.Column('valor', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('venda_id', sa.Integer(), nullable=True),
            sa.Column('observacao', sa.String(length=255), nullable=True),
            sa.Column('realizado_em', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_by_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['casa_de_racao_id'], ['casa_de_racao.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['plan_id'], ['grooming_plan.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['subscription_id'], ['grooming_subscription.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['animal_id'], ['animal.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['venda_id'], ['loja_venda.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_grooming_sessao_casa_de_racao_id'), 'grooming_sessao', ['casa_de_racao_id'])
        op.create_index(op.f('ix_grooming_sessao_subscription_id'), 'grooming_sessao', ['subscription_id'])
        op.create_index(op.f('ix_grooming_sessao_animal_id'), 'grooming_sessao', ['animal_id'])
        op.create_index(op.f('ix_grooming_sessao_agendado_para'), 'grooming_sessao', ['agendado_para'])
        op.create_index(op.f('ix_grooming_sessao_status'), 'grooming_sessao', ['status'])


def downgrade():
    if 'grooming_sessao' in set(_inspector().get_table_names()):
        op.drop_table('grooming_sessao')
    colunas = _columns('grooming_plan')
    for coluna in ('cobranca', 'peso_max_kg', 'peso_min_kg'):
        if coluna in colunas:
            op.drop_column('grooming_plan', coluna)
