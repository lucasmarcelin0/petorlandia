"""restore capstar display name

Revision ID: a6d9e2c4b7f1
Revises: f4b2c8d1e7a9
Create Date: 2026-05-04 23:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a6d9e2c4b7f1'
down_revision = 'f4b2c8d1e7a9'
branch_labels = None
depends_on = None


def _buscar_nitenpiram_id(bind) -> int | None:
    row = bind.execute(
        sa.text(
            """
            SELECT id
            FROM medicamento
            WHERE lower(nome) = 'nitenpiram'
            LIMIT 1
            """
        )
    ).first()
    return row[0] if row else None


def upgrade() -> None:
    bind = op.get_bind()
    medicamento_id = _buscar_nitenpiram_id(bind)
    if medicamento_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET nome_medicamento = 'Capstar',
                medicamento_id = :medicamento_id
            WHERE nome_medicamento = 'Nitenpiram'
              AND medicamento_id = :medicamento_id
            """
        ),
        {'medicamento_id': medicamento_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    medicamento_id = _buscar_nitenpiram_id(bind)
    if medicamento_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET nome_medicamento = 'Nitenpiram'
            WHERE nome_medicamento = 'Capstar'
              AND medicamento_id = :medicamento_id
            """
        ),
        {'medicamento_id': medicamento_id},
    )
