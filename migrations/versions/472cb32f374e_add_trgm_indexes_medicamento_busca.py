"""add trigram indexes to speed up medication search

Revision ID: 472cb32f374e
Revises: e4f5a6b7c8d9
Create Date: 2026-07-01
"""
from alembic import op


revision = "472cb32f374e"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    # /buscar_medicamentos fazia Seq Scan em toda a tabela (12k+ linhas) a
    # cada tecla digitada, incluindo CAST(conteudo_estruturado AS TEXT) —
    # medido em ~6.4s por request em produção. Índices GIN trigram permitem
    # que o ILIKE '%termo%' use índice em vez de escanear a tabela inteira.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_medicamento_nome_trgm ON medicamento "
        "USING gin (nome gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_medicamento_principio_ativo_trgm ON medicamento "
        "USING gin (principio_ativo gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_medicamento_conteudo_estruturado_trgm ON medicamento "
        "USING gin (CAST(conteudo_estruturado AS text) gin_trgm_ops)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_medicamento_conteudo_estruturado_trgm")
    op.execute("DROP INDEX IF EXISTS ix_medicamento_principio_ativo_trgm")
    op.execute("DROP INDEX IF EXISTS ix_medicamento_nome_trgm")
