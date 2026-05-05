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


def _buscar_capstar_id(bind) -> int | None:
    row = bind.execute(
        sa.text(
            """
            SELECT id
            FROM medicamento
            WHERE lower(nome) = lower(:nome_exato)
               OR lower(nome) LIKE lower(:nome_like)
            ORDER BY
                CASE WHEN lower(nome) = lower(:nome_exato) THEN 0 ELSE 1 END,
                char_length(nome)
            LIMIT 1
            """
        ),
        {
            'nome_exato': 'Capstar',
            'nome_like': 'Capstar%',
        },
    ).first()
    return row[0] if row else None


def upgrade() -> None:
    bind = op.get_bind()
    nitenpiram_id = _buscar_nitenpiram_id(bind)
    capstar_id = _buscar_capstar_id(bind)
    if nitenpiram_id is None or capstar_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET nome_medicamento = 'Capstar',
                medicamento_id = :capstar_id
            WHERE nome_medicamento = 'Nitenpiram'
              AND medicamento_id = :nitenpiram_id
            """
        ),
        {'capstar_id': capstar_id, 'nitenpiram_id': nitenpiram_id},
    )
    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET medicamento_id = :capstar_id
            WHERE nome_medicamento = 'Capstar'
            """
        ),
        {'capstar_id': capstar_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    nitenpiram_id = _buscar_nitenpiram_id(bind)
    capstar_id = _buscar_capstar_id(bind)
    if nitenpiram_id is None or capstar_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET nome_medicamento = 'Nitenpiram'
            WHERE nome_medicamento = 'Capstar'
              AND medicamento_id = :capstar_id
            """
        ),
        {'capstar_id': capstar_id},
    )
    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET medicamento_id = :nitenpiram_id
            WHERE nome_medicamento = 'Nitenpiram'
            """
        ),
        {'nitenpiram_id': nitenpiram_id},
    )
