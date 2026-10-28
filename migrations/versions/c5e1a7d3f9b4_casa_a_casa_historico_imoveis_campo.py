"""casa a casa: histórico dos imóveis acrescentados em campo

Revision ID: c5e1a7d3f9b4
Revises: b2d6f8a4c9e7
Create Date: 2026-10-28 23:50:00.000000

- ``entomologia_imovel_campo_evento``: local ajustado no mapa, exclusão e
  restauração de um imóvel acrescentado em campo, com quem fez e quando.
  Só cria uma tabela nova: nada do que já existe muda.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c5e1a7d3f9b4'
down_revision = 'b2d6f8a4c9e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'entomologia_imovel_campo_evento',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('imovel', sa.String(length=80), nullable=False),
        sa.Column('acao', sa.String(length=20), nullable=False),
        sa.Column('detalhes_json', sa.Text(), nullable=True),
        sa.Column('motivo', sa.String(length=300), nullable=True),
        sa.Column('por_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('por', sa.String(length=160), nullable=True),
        sa.Column('em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_entomologia_imovel_campo_evento_imovel', 'entomologia_imovel_campo_evento', ['imovel'])
    op.create_index('ix_entomologia_imovel_campo_evento_em', 'entomologia_imovel_campo_evento', ['em'])


def downgrade():
    op.drop_index('ix_entomologia_imovel_campo_evento_em', table_name='entomologia_imovel_campo_evento')
    op.drop_index('ix_entomologia_imovel_campo_evento_imovel', table_name='entomologia_imovel_campo_evento')
    op.drop_table('entomologia_imovel_campo_evento')
