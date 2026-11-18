"""Prefeitura integrada: comunicação ligada à solicitação do Casa a Casa.

Revision ID: a6c2e9d4b7f1
Revises: f3b8d1a6c2e4
Create Date: 2026-11-18 10:00:00.000000

A solicitação para outro setor registrada em campo (Casa a Casa) também abre
uma comunicação no mapa da Prefeitura integrada; a coluna guarda o vínculo
para o andamento de uma valer na outra.
"""
from alembic import op
import sqlalchemy as sa

revision = "a6c2e9d4b7f1"
down_revision = "f3b8d1a6c2e4"
branch_labels = None
depends_on = None


def upgrade():
    colunas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("limpeza_solicitacao")}
    if "entomologia_solicitacao_id" not in colunas:
        op.add_column("limpeza_solicitacao", sa.Column("entomologia_solicitacao_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_limpeza_solicitacao_entomologia", "limpeza_solicitacao",
                              "entomologia_solicitacao", ["entomologia_solicitacao_id"], ["id"])
        op.create_unique_constraint("uq_limpeza_solicitacao_entomologia", "limpeza_solicitacao",
                                    ["entomologia_solicitacao_id"])


def downgrade():
    op.drop_constraint("uq_limpeza_solicitacao_entomologia", "limpeza_solicitacao", type_="unique")
    op.drop_constraint("fk_limpeza_solicitacao_entomologia", "limpeza_solicitacao", type_="foreignkey")
    op.drop_column("limpeza_solicitacao", "entomologia_solicitacao_id")
