"""entomologia: plano de quarteiroes e visitas do casa a casa

Revision ID: d9a4c1e7b352
Revises: c7d2e4f6a8b1
Create Date: 2026-10-13 20:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd9a4c1e7b352'
down_revision = 'c7d2e4f6a8b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'entomologia_quarteirao_trabalho',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bloco', sa.String(length=40), nullable=False),
        sa.Column('setor', sa.String(length=20), nullable=False),
        sa.Column('quarteirao', sa.String(length=20), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('responsavel_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('responsavel', sa.String(length=160), nullable=True),
        sa.Column('concluido_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('concluido_por', sa.String(length=160), nullable=True),
        sa.Column('concluido_por_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('criado_por', sa.String(length=160), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('bloco', 'data', name='uq_entomologia_quarteirao_dia'),
    )
    op.create_index('ix_entomologia_quarteirao_trabalho_bloco', 'entomologia_quarteirao_trabalho', ['bloco'])
    op.create_index('ix_entomologia_quarteirao_trabalho_data', 'entomologia_quarteirao_trabalho', ['data'])
    op.create_index('ix_entomologia_quarteirao_trabalho_responsavel_id', 'entomologia_quarteirao_trabalho',
                    ['responsavel_id'])

    op.create_table(
        'entomologia_visita_domiciliar',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid_local', sa.String(length=64), nullable=False),
        sa.Column('bloco', sa.String(length=40), nullable=False),
        sa.Column('setor', sa.String(length=20), nullable=False),
        sa.Column('quarteirao', sa.String(length=20), nullable=False),
        sa.Column('imovel', sa.String(length=80), nullable=False),
        sa.Column('logradouro', sa.String(length=200), nullable=True),
        sa.Column('numero', sa.String(length=50), nullable=True),
        sa.Column('complemento', sa.String(length=80), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('situacao', sa.String(length=20), nullable=False),
        sa.Column('recipientes_existentes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('recipientes_agua', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('recipientes_larva', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('larvas_encontradas', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('tubitos', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('controle_mecanico', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('controle_alternativo', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('tratamento_focal', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('recuperacao', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.Column('agente_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('agente', sa.String(length=160), nullable=True),
        sa.Column('data_visita', sa.Date(), nullable=False),
        sa.Column('horario_visita', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recebido_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('uuid_local', name='uq_entomologia_visita_uuid'),
    )
    for coluna in ('uuid_local', 'bloco', 'imovel', 'agente_id', 'data_visita'):
        op.create_index(f'ix_entomologia_visita_domiciliar_{coluna}', 'entomologia_visita_domiciliar', [coluna])


def downgrade():
    op.drop_table('entomologia_visita_domiciliar')
    op.drop_table('entomologia_quarteirao_trabalho')
