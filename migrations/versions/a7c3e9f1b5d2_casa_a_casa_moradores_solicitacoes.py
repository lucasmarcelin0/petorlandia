"""casa a casa: moradores do imóvel e solicitações com foto para outros setores

Revision ID: a7c3e9f1b5d2
Revises: d4b8f2a6c1e3
Create Date: 2026-10-28 18:00:00.000000

- ``entomologia_imovel_morador``: nome e telefone dos moradores, anotados pela
  equipe em campo. Ao remover, nome e telefone são apagados (fica a marca).
- ``entomologia_solicitacao``: problema encontrado em campo para outro setor
  resolver, com foto, data e coordenadas; base do ofício.
Só cria tabelas novas: nada do que já existe muda.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a7c3e9f1b5d2'
down_revision = 'd4b8f2a6c1e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'entomologia_imovel_morador',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid_local', sa.String(length=64), nullable=False),
        sa.Column('imovel', sa.String(length=80), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=True),
        sa.Column('telefone', sa.String(length=20), nullable=True),
        sa.Column('criado_por_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('criado_por', sa.String(length=160), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('removido_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('removido_por', sa.String(length=160), nullable=True),
        sa.UniqueConstraint('uuid_local', name='uq_entomologia_morador_uuid'),
    )
    op.create_index('ix_entomologia_imovel_morador_imovel', 'entomologia_imovel_morador', ['imovel'])

    op.create_table(
        'entomologia_solicitacao',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid_local', sa.String(length=64), nullable=False),
        sa.Column('imovel', sa.String(length=80), nullable=True),
        sa.Column('bloco', sa.String(length=40), nullable=True),
        sa.Column('setor', sa.String(length=20), nullable=True),
        sa.Column('quarteirao', sa.String(length=20), nullable=True),
        sa.Column('logradouro', sa.String(length=200), nullable=True),
        sa.Column('numero', sa.String(length=50), nullable=True),
        sa.Column('complemento', sa.String(length=80), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('precisao_m', sa.Float(), nullable=True),
        sa.Column('categoria', sa.String(length=30), nullable=False),
        sa.Column('destino', sa.String(length=120), nullable=True),
        sa.Column('descricao', sa.Text(), nullable=False),
        sa.Column('foto_url', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ABERTA'),
        sa.Column('oficio', sa.String(length=60), nullable=True),
        sa.Column('agente_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('agente', sa.String(length=160), nullable=True),
        sa.Column('registrado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recebido_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('atualizado_por', sa.String(length=160), nullable=True),
        sa.UniqueConstraint('uuid_local', name='uq_entomologia_solicitacao_uuid'),
    )
    op.create_index('ix_entomologia_solicitacao_imovel', 'entomologia_solicitacao', ['imovel'])
    op.create_index('ix_entomologia_solicitacao_bloco', 'entomologia_solicitacao', ['bloco'])
    op.create_index('ix_entomologia_solicitacao_status', 'entomologia_solicitacao', ['status'])
    op.create_index('ix_entomologia_solicitacao_agente_id', 'entomologia_solicitacao', ['agente_id'])


def downgrade():
    op.drop_index('ix_entomologia_solicitacao_agente_id', table_name='entomologia_solicitacao')
    op.drop_index('ix_entomologia_solicitacao_status', table_name='entomologia_solicitacao')
    op.drop_index('ix_entomologia_solicitacao_bloco', table_name='entomologia_solicitacao')
    op.drop_index('ix_entomologia_solicitacao_imovel', table_name='entomologia_solicitacao')
    op.drop_table('entomologia_solicitacao')
    op.drop_index('ix_entomologia_imovel_morador_imovel', table_name='entomologia_imovel_morador')
    op.drop_table('entomologia_imovel_morador')
