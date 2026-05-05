"""enrich silver sulfadiazine topical dosing

Revision ID: e1f4c7b2a9d6
Revises: d8e2f4a1b6c7
Create Date: 2026-05-04 22:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1f4c7b2a9d6'
down_revision = 'd8e2f4a1b6c7'
branch_labels = None
depends_on = None


def _buscar_medicamento_id(bind) -> int | None:
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
            'nome_exato': 'Sulfadiazina de Prata',
            'nome_like': 'Sulfadiazina de Prata%',
        },
    ).first()
    return row[0] if row else None


def upgrade() -> None:
    bind = op.get_bind()
    medicamento_id = _buscar_medicamento_id(bind)
    if medicamento_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE medicamento
            SET classificacao = :classificacao,
                via_administracao = :via_administracao,
                dosagem_recomendada = :dosagem_recomendada,
                frequencia = :frequencia,
                duracao_tratamento = :duracao_tratamento,
                observacoes = :observacoes,
                conteudo_estruturado = CAST(:conteudo_estruturado AS JSON)
            WHERE id = :medicamento_id
            """
        ),
        {
            'medicamento_id': medicamento_id,
            'classificacao': 'Dermatologico / Antibacteriano topico',
            'via_administracao': 'Topica',
            'dosagem_recomendada': 'Aplicar fina camada sobre a regiao acometida a cada 12 horas.',
            'frequencia': 'A cada 8-12 horas.',
            'duracao_tratamento': 'Conforme evolucao da lesao e criterio do medico-veterinario.',
            'observacoes': (
                'Aplicar fina camada sobre a lesao apos limpeza local. '
                'Uso topico em regiao acometida.'
            ),
            'conteudo_estruturado': """
            {
              "indicacoes": {
                "itens": [
                  "Uso topico em lesoes cutaneas.",
                  "Apoio local apos limpeza da regiao acometida."
                ],
                "texto": "Aplicar camada fina sobre a regiao acometida como apoio topico local."
              },
              "administracao": {
                "itens": [
                  "Aplicar fina camada na lesao.",
                  "Via topica.",
                  "Repetir a cada 12 horas."
                ],
                "texto": "Aplicar fina camada por via topica na lesao, repetindo a cada 12 horas."
              },
              "observacoes": {
                "itens": [
                  "Frequencia usual entre 8 e 12 horas.",
                  "Manter limpeza local antes da aplicacao."
                ],
                "texto": "A frequencia usual fica entre 8 e 12 horas, com limpeza local previa."
              }
            }
            """,
        },
    )

    existente = bind.execute(
        sa.text(
            """
            SELECT id
            FROM dose_medicamento
            WHERE medicamento_id = :medicamento_id
              AND dose_unidade = 'CAMADA_TOPICA'
              AND indicacao = 'Uso topico em lesao'
            LIMIT 1
            """
        ),
        {'medicamento_id': medicamento_id},
    ).first()

    payload = {
        'medicamento_id': medicamento_id,
        'especie': 'Caes e Gatos',
        'faixa_peso': 'Qualquer peso',
        'via': 'Topica',
        'dose': 'Aplicar fina camada sobre a regiao acometida',
        'frequencia': 'A cada 12 horas',
        'duracao': 'Conforme evolucao da lesao e criterio do medico-veterinario',
        'especie_code': 'AMBOS',
        'peso_min_kg': None,
        'peso_max_kg': None,
        'dose_min': 1,
        'dose_max': 1,
        'dose_unidade': 'CAMADA_TOPICA',
        'intervalo_horas': 12,
        'intervalo_min_horas': 8,
        'intervalo_max_horas': 12,
        'duracao_min_dias': None,
        'duracao_max_dias': None,
        'dose_raw_text': 'Aplicar fina camada na lesao.',
        'observacao': 'Aplicar fina camada sobre a regiao acometida apos limpeza local.',
        'indicacao': 'Uso topico em lesao',
        'fonte': 'HUMANO',
        'confianca': 'ALTA',
    }

    if existente:
        bind.execute(
            sa.text(
                """
                UPDATE dose_medicamento
                SET especie = :especie,
                    faixa_peso = :faixa_peso,
                    via = :via,
                    dose = :dose,
                    frequencia = :frequencia,
                    duracao = :duracao,
                    especie_code = :especie_code,
                    peso_min_kg = :peso_min_kg,
                    peso_max_kg = :peso_max_kg,
                    dose_min = :dose_min,
                    dose_max = :dose_max,
                    dose_unidade = :dose_unidade,
                    intervalo_horas = :intervalo_horas,
                    intervalo_min_horas = :intervalo_min_horas,
                    intervalo_max_horas = :intervalo_max_horas,
                    duracao_min_dias = :duracao_min_dias,
                    duracao_max_dias = :duracao_max_dias,
                    dose_raw_text = :dose_raw_text,
                    observacao = :observacao,
                    indicacao = :indicacao,
                    fonte = :fonte,
                    confianca = :confianca
                WHERE id = :id
                """
            ),
            {**payload, 'id': existente[0]},
        )
    else:
        bind.execute(
            sa.text(
                """
                INSERT INTO dose_medicamento (
                    medicamento_id,
                    especie,
                    faixa_peso,
                    via,
                    dose,
                    frequencia,
                    duracao,
                    especie_code,
                    peso_min_kg,
                    peso_max_kg,
                    dose_min,
                    dose_max,
                    dose_unidade,
                    intervalo_horas,
                    intervalo_min_horas,
                    intervalo_max_horas,
                    duracao_min_dias,
                    duracao_max_dias,
                    dose_raw_text,
                    observacao,
                    indicacao,
                    fonte,
                    confianca
                ) VALUES (
                    :medicamento_id,
                    :especie,
                    :faixa_peso,
                    :via,
                    :dose,
                    :frequencia,
                    :duracao,
                    :especie_code,
                    :peso_min_kg,
                    :peso_max_kg,
                    :dose_min,
                    :dose_max,
                    :dose_unidade,
                    :intervalo_horas,
                    :intervalo_min_horas,
                    :intervalo_max_horas,
                    :duracao_min_dias,
                    :duracao_max_dias,
                    :dose_raw_text,
                    :observacao,
                    :indicacao,
                    :fonte,
                    :confianca
                )
                """
            ),
            payload,
        )


def downgrade() -> None:
    bind = op.get_bind()
    medicamento_id = _buscar_medicamento_id(bind)
    if medicamento_id is None:
        return

    bind.execute(
        sa.text(
            """
            DELETE FROM dose_medicamento
            WHERE medicamento_id = :medicamento_id
              AND dose_unidade = 'CAMADA_TOPICA'
              AND indicacao = 'Uso topico em lesao'
            """
        ),
        {'medicamento_id': medicamento_id},
    )
