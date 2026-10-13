"""animal: regua do anuncio de adocao (revisao mensal e pedido de foto/telefone)

Revision ID: b3f7a2d9c5e1
Revises: 522950f3ced1
Create Date: 2026-10-13 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b3f7a2d9c5e1'
down_revision = '522950f3ced1'
branch_labels = None
depends_on = None


COLUNAS = (
    'adocao_revisada_em',
    'adocao_lembrete_em',
    'adocao_pedido_dados_em',
    'adocao_expirada_em',
)


def upgrade():
    for coluna in COLUNAS:
        op.add_column('animal', sa.Column(coluna, sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for coluna in reversed(COLUNAS):
        op.drop_column('animal', coluna)
