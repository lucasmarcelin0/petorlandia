"""casa a casa: tipos de problema das solicitações criados pela equipe

Revision ID: b2d6f8a4c9e7
Revises: a7c3e9f1b5d2
Create Date: 2026-10-28 23:30:00.000000

- ``entomologia_solicitacao_categoria``: tipos de problema além dos que vêm
  prontos no sistema. Quem criou, ou um administrador, renomeia ou tira da
  lista. Só cria uma tabela nova: nada do que já existe muda.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b2d6f8a4c9e7'
down_revision = 'a7c3e9f1b5d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'entomologia_solicitacao_categoria',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chave', sa.String(length=30), nullable=False),
        sa.Column('nome', sa.String(length=80), nullable=False),
        sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('criado_por_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('criado_por', sa.String(length=160), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('atualizado_por', sa.String(length=160), nullable=True),
        sa.UniqueConstraint('chave', name='uq_entomologia_solicitacao_categoria_chave'),
    )


def downgrade():
    op.drop_table('entomologia_solicitacao_categoria')
