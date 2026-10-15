"""casa a casa: quarteirão dividido em L, atividade, larvicida do focal e imóveis acrescentados em campo

Revision ID: f4c9a2d6b8e1
Revises: e3b8f5a1c7d9
Create Date: 2026-10-14 22:00:00.000000

- ``entomologia_quarteirao_trabalho.parte``: "" (inteiro) ou o L de um canto
  (NE, NO, SE, SO). A unicidade passa de (bloco, data) para (bloco, data, parte),
  para um quarteirão poder ser dividido entre duas pessoas no mesmo dia.
  Linhas antigas recebem "" e continuam valendo como quarteirão inteiro.
- ``atividade`` no plano e na visita (avaliação de densidade larvária, visita a
  imóveis ou controle de criadouro, de rotina ou pendência). Opcional.
- ``focal_produto`` na visita (Natular, Vectobac). Opcional.
- ``entomologia_imovel_campo``: imóveis que faltavam na base oficial e foram
  acrescentados por agentes; passam a fazer parte do mapa do casa a casa.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f4c9a2d6b8e1'
down_revision = 'e3b8f5a1c7d9'
branch_labels = None
depends_on = None

PLANO = 'entomologia_quarteirao_trabalho'
VISITA = 'entomologia_visita_domiciliar'


def upgrade():
    op.add_column(PLANO, sa.Column('parte', sa.String(length=2), nullable=False, server_default=''))
    op.add_column(PLANO, sa.Column('atividade', sa.String(length=20), nullable=True))
    with op.batch_alter_table(PLANO) as tabela:
        tabela.drop_constraint('uq_entomologia_quarteirao_dia', type_='unique')
        tabela.create_unique_constraint('uq_entomologia_quarteirao_dia_parte', ['bloco', 'data', 'parte'])

    op.add_column(VISITA, sa.Column('focal_produto', sa.String(length=30), nullable=True))
    op.add_column(VISITA, sa.Column('atividade', sa.String(length=20), nullable=True))

    op.create_table(
        'entomologia_imovel_campo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('imovel', sa.String(length=80), nullable=False),
        sa.Column('bloco', sa.String(length=40), nullable=False),
        sa.Column('setor', sa.String(length=20), nullable=False),
        sa.Column('quarteirao', sa.String(length=20), nullable=False),
        sa.Column('logradouro', sa.String(length=200), nullable=False),
        sa.Column('numero', sa.String(length=50), nullable=False),
        sa.Column('complemento', sa.String(length=80), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('criado_por_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('criado_por', sa.String(length=160), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('removido_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('removido_por', sa.String(length=160), nullable=True),
        sa.UniqueConstraint('imovel', name='uq_entomologia_imovel_campo_imovel'),
    )
    op.create_index('ix_entomologia_imovel_campo_bloco', 'entomologia_imovel_campo', ['bloco'])


def downgrade():
    op.drop_index('ix_entomologia_imovel_campo_bloco', table_name='entomologia_imovel_campo')
    op.drop_table('entomologia_imovel_campo')
    op.drop_column(VISITA, 'atividade')
    op.drop_column(VISITA, 'focal_produto')
    # Volta a uma linha por quarteirão e dia: a segunda metade de um quarteirão dividido sai.
    op.execute(sa.text(f"DELETE FROM {PLANO} WHERE parte <> '' AND id NOT IN "
                       f"(SELECT MIN(id) FROM {PLANO} GROUP BY bloco, data)"))
    with op.batch_alter_table(PLANO) as tabela:
        tabela.drop_constraint('uq_entomologia_quarteirao_dia_parte', type_='unique')
        tabela.create_unique_constraint('uq_entomologia_quarteirao_dia', ['bloco', 'data'])
    op.drop_column(PLANO, 'atividade')
    op.drop_column(PLANO, 'parte')
