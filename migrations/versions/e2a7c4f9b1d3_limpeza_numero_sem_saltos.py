"""Limpeza urbana: número da comunicação sem saltos.

Revision ID: e2a7c4f9b1d3
Revises: d5e1b8c3a9f2
Create Date: 2026-11-16 15:00:00.000000

O ``id`` do Postgres pula quando uma gravação é desfeita (envio repetido do
aparelho, por exemplo). A coluna ``numero`` numera as comunicações existentes
em ordem de chegada (1, 2, 3…) e as próximas continuam a partir daí.
"""
from alembic import op
import sqlalchemy as sa

revision = "e2a7c4f9b1d3"
down_revision = "d5e1b8c3a9f2"
branch_labels = None
depends_on = None


def upgrade():
    colunas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("limpeza_solicitacao")}
    if "numero" not in colunas:
        op.add_column("limpeza_solicitacao", sa.Column("numero", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE limpeza_solicitacao SET numero = ordem.n FROM ("
        " SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS n FROM limpeza_solicitacao"
        ") AS ordem WHERE limpeza_solicitacao.id = ordem.id AND limpeza_solicitacao.numero IS NULL"
    )
    op.create_unique_constraint("uq_limpeza_solicitacao_numero", "limpeza_solicitacao", ["numero"])


def downgrade():
    op.drop_constraint("uq_limpeza_solicitacao_numero", "limpeza_solicitacao", type_="unique")
    op.drop_column("limpeza_solicitacao", "numero")
