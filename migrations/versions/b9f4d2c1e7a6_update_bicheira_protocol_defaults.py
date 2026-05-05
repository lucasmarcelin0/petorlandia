"""update bicheira protocol defaults

Revision ID: b9f4d2c1e7a6
Revises: a6d9e2c4b7f1
Create Date: 2026-05-04 23:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9f4d2c1e7a6'
down_revision = 'a6d9e2c4b7f1'
branch_labels = None
depends_on = None


ATUALIZACOES = {
    'Cefalexina': {
        'frequencia_texto': 'a cada 12 horas',
        'duracao_texto': 'por 10 dias',
    },
    'Capstar': {
        'frequencia_texto': 'Dose unica',
        'duracao_texto': 'Dose unica',
    },
    'Meloxicam': {
        'frequencia_texto': 'a cada 24 horas',
        'duracao_texto': 'por 5 dias',
    },
    'Pomada de sulfadiazina de prata': {
        'frequencia_texto': 'a cada 12 horas',
        'duracao_texto': 'por 10 dias',
    },
}


def _protocolo_ids_bicheira(bind) -> list[int]:
    rows = bind.execute(
        sa.text(
            """
            SELECT id
            FROM protocolo_clinico
            WHERE lower(suspeita_principal) = 'bicheira'
            """
        )
    ).fetchall()
    return [int(row[0]) for row in rows]


def upgrade() -> None:
    bind = op.get_bind()
    protocolo_ids = _protocolo_ids_bicheira(bind)
    if not protocolo_ids:
        return

    for protocolo_id in protocolo_ids:
        for nome_medicamento, payload in ATUALIZACOES.items():
            bind.execute(
                sa.text(
                    """
                    UPDATE protocolo_clinico_medicamento
                    SET frequencia_texto = :frequencia_texto,
                        duracao_texto = :duracao_texto
                    WHERE protocolo_id = :protocolo_id
                      AND nome_medicamento = :nome_medicamento
                    """
                ),
                {
                    'protocolo_id': protocolo_id,
                    'nome_medicamento': nome_medicamento,
                    **payload,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    protocolo_ids = _protocolo_ids_bicheira(bind)
    if not protocolo_ids:
        return

    for protocolo_id in protocolo_ids:
        for nome_medicamento in ATUALIZACOES:
            bind.execute(
                sa.text(
                    """
                    UPDATE protocolo_clinico_medicamento
                    SET frequencia_texto = NULL,
                        duracao_texto = NULL
                    WHERE protocolo_id = :protocolo_id
                      AND nome_medicamento = :nome_medicamento
                    """
                ),
                {
                    'protocolo_id': protocolo_id,
                    'nome_medicamento': nome_medicamento,
                },
            )
