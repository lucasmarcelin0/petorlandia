"""merge fiscal phase 1 hardening branches

Revision ID: f9a7b3c2d8e1
Revises: c2f7a8b3d1e6, e7f3a9c2b4d1
Create Date: 2026-04-22 06:32:59.995924

Por que esse merge existe:
    Durante a Fase 1 de hardening fiscal apareceram dois heads de
    Alembic no mesmo banco:

      - `c2f7a8b3d1e6`: adiciona indicacao/fabricante/vetsmart_produto_id
        (branch do bulário, veio de `a9d3e7b1c2f4`).
      - `e7f3a9c2b4d1`: cria tabelas operacionais da contabilidade (Fase 3,
        veio de `b7c1a2d3e4f5`).

    Ambas chegaram em produção como heads paralelos, o que faz `flask db
    upgrade` falhar ("multiple heads detected"). Esta migration é um
    merge NO-OP: não toca schema, só junta os dois heads numa revisão
    única pra destravar o upgrade normal.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9a7b3c2d8e1'
down_revision = ('c2f7a8b3d1e6', 'e7f3a9c2b4d1')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
