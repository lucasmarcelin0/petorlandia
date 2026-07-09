"""Add medication curation review table

Revision ID: fc1d7a9e4b2c
Revises: fb9f33ae1c23
Create Date: 2026-07-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'fc1d7a9e4b2c'
down_revision = 'fb9f33ae1c23'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'curadoria_medicamento_review',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome_normalizado', sa.String(length=180), nullable=False),
        sa.Column('nome_prescrito_principal', sa.Text(), nullable=False),
        sa.Column('medicamento_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('prioridade', sa.Integer(), nullable=False),
        sa.Column('total_prescricoes', sa.Integer(), nullable=False),
        sa.Column('ultima_prescricao_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('confianca_alias', sa.String(length=20), nullable=False),
        sa.Column('resumo_historico', sa.JSON(), nullable=True),
        sa.Column('diagnostico', sa.JSON(), nullable=True),
        sa.Column('proposta', sa.JSON(), nullable=True),
        sa.Column('fontes', sa.JSON(), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False),
        sa.Column('aprovado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('aprovado_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['aprovado_por_id'], ['user.id']),
        sa.ForeignKeyConstraint(['medicamento_id'], ['medicamento.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_curadoria_medicamento_review_confianca_alias'), 'curadoria_medicamento_review', ['confianca_alias'], unique=False)
    op.create_index(op.f('ix_curadoria_medicamento_review_medicamento_id'), 'curadoria_medicamento_review', ['medicamento_id'], unique=False)
    op.create_index(op.f('ix_curadoria_medicamento_review_nome_normalizado'), 'curadoria_medicamento_review', ['nome_normalizado'], unique=True)
    op.create_index(op.f('ix_curadoria_medicamento_review_prioridade'), 'curadoria_medicamento_review', ['prioridade'], unique=False)
    op.create_index(op.f('ix_curadoria_medicamento_review_status'), 'curadoria_medicamento_review', ['status'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_curadoria_medicamento_review_status'), table_name='curadoria_medicamento_review')
    op.drop_index(op.f('ix_curadoria_medicamento_review_prioridade'), table_name='curadoria_medicamento_review')
    op.drop_index(op.f('ix_curadoria_medicamento_review_nome_normalizado'), table_name='curadoria_medicamento_review')
    op.drop_index(op.f('ix_curadoria_medicamento_review_medicamento_id'), table_name='curadoria_medicamento_review')
    op.drop_index(op.f('ix_curadoria_medicamento_review_confianca_alias'), table_name='curadoria_medicamento_review')
    op.drop_table('curadoria_medicamento_review')
