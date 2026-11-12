"""Identificador idempotente para comunicação de limpeza.

Revision ID: b8e1c4d7f901
Revises: a4c7e2b9d5f1
"""
from alembic import op
import sqlalchemy as sa

revision = "b8e1c4d7f901"
down_revision = "a4c7e2b9d5f1"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("limpeza_solicitacao", sa.Column("chave_envio", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_limpeza_solicitacao_chave_envio", "limpeza_solicitacao", ["chave_envio"])

def downgrade():
    op.drop_constraint("uq_limpeza_solicitacao_chave_envio", "limpeza_solicitacao", type_="unique")
    op.drop_column("limpeza_solicitacao", "chave_envio")
