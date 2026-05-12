"""refine dermatitis protocol defaults

Revision ID: f1b4d7c8e2a3
Revises: e4a1c9d2b6f7
Create Date: 2026-05-12 12:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f1b4d7c8e2a3'
down_revision = 'e4a1c9d2b6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    protocolo_id = bind.execute(
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
        {'nome': 'Protocolo Inicial para Dermatites', 'suspeita': 'dermatite'},
    ).scalar_one_or_none()
    if protocolo_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET dosagem_texto = 'Aplicar sobre a pelagem umedecida, massagear e deixar agir por 5 a 10 minutos; enxaguar bem e repetir o processo uma vez.',
                frequencia_texto = '1 vez por semana',
                duracao_texto = '3 meses'
            WHERE protocolo_id = :protocolo_id
              AND lower(nome_medicamento) like '%clorexidina%'
            """
        ),
        {'protocolo_id': protocolo_id},
    )
    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET indicacao = 'Alergia',
                duracao_texto = '5 dias',
                observacoes = 'Calcular dose automaticamente pelo peso do animal usando a dose minima e revisar contraindicacoes clinicas.'
            WHERE protocolo_id = :protocolo_id
              AND lower(nome_medicamento) = 'prednisona'
            """
        ),
        {'protocolo_id': protocolo_id},
    )
    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET frequencia_texto = 'a cada 30 dias',
                duracao_texto = 'conforme protocolo mensal'
            WHERE protocolo_id = :protocolo_id
              AND lower(nome_medicamento) = 'simparic'
            """
        ),
        {'protocolo_id': protocolo_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    protocolo_id = bind.execute(
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
        {'nome': 'Protocolo Inicial para Dermatites', 'suspeita': 'dermatite'},
    ).scalar_one_or_none()
    if protocolo_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE protocolo_clinico_medicamento
            SET duracao_texto = '',
                observacoes = 'Calcular dose automaticamente pelo peso do animal e revisar contraindicacoes clinicas.'
            WHERE protocolo_id = :protocolo_id
              AND lower(nome_medicamento) = 'prednisona'
            """
        ),
        {'protocolo_id': protocolo_id},
    )
