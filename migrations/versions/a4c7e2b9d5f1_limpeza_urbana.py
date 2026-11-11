"""Limpeza urbana: comunicações com foto e GPS, comprovações da equipe e papéis com período

Revision ID: a4c7e2b9d5f1
Revises: f8b2c6d4e1a7
Create Date: 2026-11-11 12:00:00.000000

Somente tabelas novas. Nada muda nos dados existentes.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a4c7e2b9d5f1'
down_revision = 'f8b2c6d4e1a7'
branch_labels = None
depends_on = None


def upgrade():
    existentes = set(sa.inspect(op.get_bind()).get_table_names())

    if 'limpeza_acesso' not in existentes:
        op.create_table(
            'limpeza_acesso',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('papel', sa.String(20), nullable=False),
            sa.Column('inicio', sa.Date()),
            sa.Column('fim', sa.Date()),
            sa.Column('concedido_por', sa.String(160), nullable=False),
            sa.Column('concedido_em', sa.DateTime(timezone=True), nullable=False),
            sa.Column('revogado_em', sa.DateTime(timezone=True)),
            sa.Column('revogado_por', sa.String(160)),
        )
        op.create_index('ix_limpeza_acesso_user_id', 'limpeza_acesso', ['user_id'])

    if 'limpeza_solicitacao' not in existentes:
        op.create_table(
            'limpeza_solicitacao',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('autor_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('categorias', sa.String(120), nullable=False),
            sa.Column('descricao', sa.String(500)),
            sa.Column('referencia', sa.String(200)),
            sa.Column('latitude', sa.Float(), nullable=False),
            sa.Column('longitude', sa.Float(), nullable=False),
            sa.Column('precisao_m', sa.Float()),
            sa.Column('origem_local', sa.String(12), nullable=False),
            sa.Column('foto_url', sa.String(500), nullable=False),
            sa.Column('foto_capturada_em', sa.DateTime(timezone=True)),
            sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
            sa.Column('status', sa.String(12), nullable=False, server_default='aberta'),
            sa.Column('concluida_em', sa.DateTime(timezone=True)),
            sa.Column('descartada_em', sa.DateTime(timezone=True)),
            sa.Column('descartada_por', sa.String(160)),
            sa.Column('motivo_descarte', sa.String(300)),
        )
        op.create_index('ix_limpeza_solicitacao_autor_id', 'limpeza_solicitacao', ['autor_id'])
        op.create_index('ix_limpeza_solicitacao_criado_em', 'limpeza_solicitacao', ['criado_em'])
        op.create_index('ix_limpeza_solicitacao_status', 'limpeza_solicitacao', ['status'])

    if 'limpeza_comprovacao' not in existentes:
        op.create_table(
            'limpeza_comprovacao',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('solicitacao_id', sa.Integer(), sa.ForeignKey('limpeza_solicitacao.id'), nullable=False),
            sa.Column('autor_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('observacao', sa.String(500)),
            sa.Column('latitude', sa.Float(), nullable=False),
            sa.Column('longitude', sa.Float(), nullable=False),
            sa.Column('precisao_m', sa.Float()),
            sa.Column('origem_local', sa.String(12), nullable=False),
            sa.Column('distancia_m', sa.Float()),
            sa.Column('foto_url', sa.String(500), nullable=False),
            sa.Column('foto_capturada_em', sa.DateTime(timezone=True)),
            sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
            sa.Column('status', sa.String(12), nullable=False, server_default='valida'),
            sa.Column('recusada_em', sa.DateTime(timezone=True)),
            sa.Column('recusada_por', sa.String(160)),
            sa.Column('motivo_recusa', sa.String(300)),
        )
        op.create_index('ix_limpeza_comprovacao_solicitacao_id', 'limpeza_comprovacao', ['solicitacao_id'])
        op.create_index('ix_limpeza_comprovacao_autor_id', 'limpeza_comprovacao', ['autor_id'])

    if 'limpeza_evento' not in existentes:
        op.create_table(
            'limpeza_evento',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('solicitacao_id', sa.Integer(), sa.ForeignKey('limpeza_solicitacao.id')),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id')),
            sa.Column('tipo', sa.String(30), nullable=False),
            sa.Column('detalhe', sa.String(500)),
            sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index('ix_limpeza_evento_solicitacao_id', 'limpeza_evento', ['solicitacao_id'])
        op.create_index('ix_limpeza_evento_criado_em', 'limpeza_evento', ['criado_em'])


def downgrade():
    for tabela in ('limpeza_evento', 'limpeza_comprovacao', 'limpeza_solicitacao', 'limpeza_acesso'):
        op.drop_table(tabela)
