"""rename capstar protocol item to nitenpiram

Revision ID: f4b2c8d1e7a9
Revises: e1f4c7b2a9d6
Create Date: 2026-05-04 23:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4b2c8d1e7a9'
down_revision = 'e1f4c7b2a9d6'
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


def _upsert_alias(bind, nome_prescrito: str, medicamento_id: int) -> None:
    existente = bind.execute(
        sa.text(
            "SELECT id FROM prescricao_alias_medicamento WHERE nome_prescrito = :nome_prescrito"
        ),
        {'nome_prescrito': nome_prescrito},
    ).first()
    if existente:
        bind.execute(
            sa.text(
                """
                UPDATE prescricao_alias_medicamento
                SET medicamento_id = :medicamento_id,
                    confianca = 'manual'
                WHERE id = :alias_id
                """
            ),
            {'medicamento_id': medicamento_id, 'alias_id': existente[0]},
        )
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO prescricao_alias_medicamento (nome_prescrito, medicamento_id, confianca)
            VALUES (:nome_prescrito, :medicamento_id, 'manual')
            """
        ),
        {'nome_prescrito': nome_prescrito, 'medicamento_id': medicamento_id},
    )


def upgrade() -> None:
    bind = op.get_bind()
    medicamento_id = _buscar_nitenpiram_id(bind)
    if medicamento_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET nome_medicamento = 'Nitenpiram',
                medicamento_id = :medicamento_id
            WHERE nome_medicamento = 'Capstar'
            """
        ),
        {'medicamento_id': medicamento_id},
    )

    _upsert_alias(bind, 'Capstar', medicamento_id)
    _upsert_alias(bind, 'Nitenpiram', medicamento_id)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET nome_medicamento = 'Capstar',
                medicamento_id = NULL
            WHERE nome_medicamento = 'Nitenpiram'
            """
        )
    )
