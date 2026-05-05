"""link bicheira protocol to canonical meds

Revision ID: c7d4e2f1a9b3
Revises: b4c8d1e2f6a9, 0f7aae77ce3d
Create Date: 2026-05-04 22:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7d4e2f1a9b3'
down_revision = ('b4c8d1e2f6a9', '0f7aae77ce3d')
branch_labels = None
depends_on = None


def _buscar_medicamento_id(bind, termo_principal: str, like_termo: str | None = None) -> int | None:
    row = bind.execute(
        sa.text(
            """
            SELECT id
            FROM medicamento
            WHERE lower(nome) = lower(:termo_principal)
               OR (:like_termo IS NOT NULL AND lower(nome) LIKE lower(:like_termo))
            ORDER BY
                CASE WHEN lower(nome) = lower(:termo_principal) THEN 0 ELSE 1 END,
                char_length(nome)
            LIMIT 1
            """
        ),
        {'termo_principal': termo_principal, 'like_termo': like_termo},
    ).first()
    return row[0] if row else None


def _upsert_alias(bind, nome_prescrito: str, medicamento_id: int | None) -> None:
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

    protocolo = bind.execute(
        sa.text(
            """
            SELECT id
            FROM protocolo_clinico
            WHERE nome = :nome
              AND suspeita_principal = :suspeita
              AND clinica_id IS NULL
            LIMIT 1
            """
        ),
        {'nome': 'Protocolo Inicial para Bicheira', 'suspeita': 'bicheira'},
    ).first()
    if not protocolo:
        return

    protocolo_id = protocolo[0]
    mapeamento = {
        'Cefalexina': _buscar_medicamento_id(bind, 'Cefalexina'),
        'Capstar': _buscar_medicamento_id(bind, 'Capstar', 'Capstar%'),
        'Meloxicam': _buscar_medicamento_id(bind, 'Meloxicam'),
        'Pomada de sulfadiazina de prata': _buscar_medicamento_id(
            bind,
            'Sulfadiazina de Prata',
            'Sulfadiazina de Prata%',
        ),
    }

    for nome_medicamento, medicamento_id in mapeamento.items():
        if medicamento_id is None:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET medicamento_id = :medicamento_id
                WHERE protocolo_id = :protocolo_id
                  AND nome_medicamento = :nome_medicamento
                """
            ),
            {
                'medicamento_id': medicamento_id,
                'protocolo_id': protocolo_id,
                'nome_medicamento': nome_medicamento,
            },
        )
        _upsert_alias(bind, nome_medicamento, medicamento_id)


def downgrade() -> None:
    bind = op.get_bind()

    protocolo = bind.execute(
        sa.text(
            """
            SELECT id
            FROM protocolo_clinico
            WHERE nome = :nome
              AND suspeita_principal = :suspeita
              AND clinica_id IS NULL
            LIMIT 1
            """
        ),
        {'nome': 'Protocolo Inicial para Bicheira', 'suspeita': 'bicheira'},
    ).first()
    if protocolo:
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET medicamento_id = NULL
                WHERE protocolo_id = :protocolo_id
                  AND nome_medicamento IN (
                    'Cefalexina',
                    'Capstar',
                    'Meloxicam',
                    'Pomada de sulfadiazina de prata'
                  )
                """
            ),
            {'protocolo_id': protocolo[0]},
        )

    bind.execute(
        sa.text(
            """
            DELETE FROM prescricao_alias_medicamento
            WHERE nome_prescrito IN (
                'Cefalexina',
                'Capstar',
                'Meloxicam',
                'Pomada de sulfadiazina de prata'
            )
              AND confianca = 'manual'
            """
        )
    )
