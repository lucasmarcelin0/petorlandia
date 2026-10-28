"""Corrige a validade do lote da vacina antirrábica da campanha PMO.

As doses da campanha eram gravadas com o lote padrão
"Fab. 09/2024 - Val. 09/2026", e a carteirinha (tela e PDF) passou a mostrar a
vacina como vencida. O lote em uso vence em 01/2027. Só altera registros que
ainda têm exatamente o texto padrão antigo; lotes digitados à mão ficam como
estão.

Revision ID: d4b8f2a6c1e3
Revises: c7e1a9b3d5f2
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4b8f2a6c1e3'
down_revision = 'c7e1a9b3d5f2'
branch_labels = None
depends_on = None

_LOTE_ANTIGO = 'Fab. 09/2024 - Val. 09/2026'
_LOTE_NOVO = 'Val. 01/2027'


def _trocar_lote(de, para):
    conn = op.get_bind()
    if 'vacina' not in sa.inspect(conn).get_table_names():
        return
    conn.execute(
        sa.text("UPDATE vacina SET lote = :para WHERE lote = :de"),
        {'de': de, 'para': para},
    )


def upgrade():
    _trocar_lote(_LOTE_ANTIGO, _LOTE_NOVO)


def downgrade():
    _trocar_lote(_LOTE_NOVO, _LOTE_ANTIGO)
