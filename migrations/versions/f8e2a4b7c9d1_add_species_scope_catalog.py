"""add species_scope to catalog tables (medicamento, vacina_modelo, exame_modelo, tipo_racao)

Revision ID: f8e2a4b7c9d1
Revises: d6f4696c11ff
Create Date: 2026-05-05

Sinaliza para qual conjunto de espécies cada item de catálogo é mais relevante.
Valores convencionais:
  - 'CG'    : cães e/ou gatos
  - 'BE'    : bovinos e/ou equinos
  - 'AMBOS' : aplicável a múltiplos grupos
  - 'OUTRO' : aves, exóticos etc.

Coluna NULL = scope desconhecido. O ranking de busca usa este campo apenas para
priorizar resultados — nenhum item é escondido. Isso garante que a feature seja
puramente aditiva e que itens existentes continuem funcionando enquanto não são
classificados.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f8e2a4b7c9d1'
down_revision = 'd6f4696c11ff'
branch_labels = None
depends_on = None


_TABLES = (
    ('medicamento',     'ix_medicamento_species_scope'),
    ('vacina_modelo',   'ix_vacina_modelo_species_scope'),
    ('exame_modelo',    'ix_exame_modelo_species_scope'),
    ('tipo_racao',      'ix_tipo_racao_species_scope'),
)


def _has_table(bind, name: str) -> bool:
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    cols = {c['name'] for c in inspector.get_columns(table)}
    return column in cols


def _has_index(bind, table: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(ix.get('name') == index_name for ix in inspector.get_indexes(table))


def upgrade():
    bind = op.get_bind()

    for table, index_name in _TABLES:
        if not _has_table(bind, table):
            continue
        if not _has_column(bind, table, 'species_scope'):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column('species_scope', sa.String(length=20), nullable=True))
        if not _has_index(bind, table, index_name):
            op.create_index(index_name, table, ['species_scope'])


def downgrade():
    bind = op.get_bind()

    for table, index_name in _TABLES:
        if not _has_table(bind, table):
            continue
        if _has_index(bind, table, index_name):
            op.drop_index(index_name, table_name=table)
        if _has_column(bind, table, 'species_scope'):
            with op.batch_alter_table(table) as batch:
                batch.drop_column('species_scope')
