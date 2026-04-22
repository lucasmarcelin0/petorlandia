"""fix fiscal schema drift source_type index enum

Revision ID: f3b9a2c7d4e6
Revises: f9a7b3c2d8e1
Create Date: 2026-04-22 06:39:02.484023

Contexto:
    Auditoria Fase 1 detectou que os índices `ix_fiscal_documents_source`
    e `ix_fiscal_documents_related`, definidos em
    `FiscalDocument.__table_args__` e criados pela migration
    `a2c4f8d1e0b7_add_fiscal_document_context`, NÃO existem em todos os
    ambientes. Isso faz dois estragos:

      1. Performance: queries por (clinic_id, source_type, source_id) —
         usadas toda vez que o front busca "tem NF-e pra esse orçamento?"
         — fazem seq scan em fiscal_documents inteiro.
      2. `flask db check` reporta drift, bloqueando CI em modo strict.

    A migration `a2c4f8d1e0b7` é IDEMPOTENTE (checa se o índice existe
    antes de criar), então simplesmente re-rodá-la não adianta para bancos
    que foram marcados como upgraded sem ter os índices. Esta migration
    cria-os explicitamente em qualquer ambiente onde faltem.

    Também garante que source_type/source_id/related_type/related_id
    existem como colunas — defensiva para ambientes que podem ter sido
    restaurados de um dump anterior à a2c4f8d1e0b7.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3b9a2c7d4e6'
down_revision = 'f9a7b3c2d8e1'
branch_labels = None
depends_on = None


TABLE = "fiscal_documents"

# (nome_indice, colunas)
EXPECTED_INDEXES = (
    ("ix_fiscal_documents_source", ("clinic_id", "source_type", "source_id")),
    ("ix_fiscal_documents_related", ("clinic_id", "related_type", "related_id")),
)

EXPECTED_COLUMNS = (
    ("source_type", sa.String(length=40)),
    ("source_id", sa.Integer()),
    ("related_type", sa.String(length=40)),
    ("related_id", sa.Integer()),
    ("human_reference", sa.String(length=255)),
    ("animal_name", sa.String(length=120)),
    ("tutor_name", sa.String(length=120)),
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns(TABLE)}
    existing_idx = {i["name"] for i in inspector.get_indexes(TABLE)}

    # 1. Colunas — defensivo (quase sempre já existem via a2c4f8d1e0b7).
    for col_name, col_type in EXPECTED_COLUMNS:
        if col_name not in existing_cols:
            op.add_column(TABLE, sa.Column(col_name, col_type))

    # 2. Índices — o verdadeiro foco desta migration.
    for idx_name, cols in EXPECTED_INDEXES:
        if idx_name not in existing_idx:
            op.create_index(idx_name, TABLE, list(cols))


def downgrade():
    # Idempotente: só dropa se existir. NÃO removemos colunas aqui
    # porque a2c4f8d1e0b7 é quem as adicionou — remover aqui deixaria
    # o downgrade inconsistente se alguém voltar até lá.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_idx = {i["name"] for i in inspector.get_indexes(TABLE)}

    for idx_name, _ in EXPECTED_INDEXES:
        if idx_name in existing_idx:
            op.drop_index(idx_name, table_name=TABLE)
