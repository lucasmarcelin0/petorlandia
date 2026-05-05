"""enrich capstar structured dosing

Revision ID: d8e2f4a1b6c7
Revises: c7d4e2f1a9b3
Create Date: 2026-05-04 22:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8e2f4a1b6c7'
down_revision = 'c7d4e2f1a9b3'
branch_labels = None
depends_on = None


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


def _upsert_apresentacao(bind, medicamento_id: int, *, nome_variante: str, concentracao_texto: str,
                         concentracao_valor: float, especie_texto: str) -> None:
    existente = bind.execute(
        sa.text(
            """
            SELECT id
            FROM apresentacao_medicamento
            WHERE medicamento_id = :medicamento_id
              AND nome_variante = :nome_variante
            LIMIT 1
            """
        ),
        {
            'medicamento_id': medicamento_id,
            'nome_variante': nome_variante,
        },
    ).first()

    payload = {
        'medicamento_id': medicamento_id,
        'forma': 'comprimido',
        'concentracao': concentracao_texto,
        'nome_variante': nome_variante,
        'concentracao_valor': concentracao_valor,
        'concentracao_unidade': 'mg',
        'volume_valor': 1,
        'volume_unidade': 'un',
        'fabricante': 'Elanco',
    }
    if existente:
        bind.execute(
            sa.text(
                """
                UPDATE apresentacao_medicamento
                SET forma = :forma,
                    concentracao = :concentracao,
                    concentracao_valor = :concentracao_valor,
                    concentracao_unidade = :concentracao_unidade,
                    volume_valor = :volume_valor,
                    volume_unidade = :volume_unidade,
                    fabricante = :fabricante
                WHERE id = :id
                """
            ),
            {**payload, 'id': existente[0]},
        )
        return

    bind.execute(
        sa.text(
            """
            INSERT INTO apresentacao_medicamento (
                medicamento_id,
                forma,
                concentracao,
                nome_variante,
                concentracao_valor,
                concentracao_unidade,
                volume_valor,
                volume_unidade,
                fabricante
            ) VALUES (
                :medicamento_id,
                :forma,
                :concentracao,
                :nome_variante,
                :concentracao_valor,
                :concentracao_unidade,
                :volume_valor,
                :volume_unidade,
                :fabricante
            )
            """
        ),
        payload,
    )


def _upsert_dose(bind, medicamento_id: int, *, especie_code: str, especie: str, peso_min_kg: float | None,
                 peso_max_kg: float | None, faixa_peso: str, dose: str, observacao: str) -> None:
    existente = bind.execute(
        sa.text(
            """
            SELECT id
            FROM dose_medicamento
            WHERE medicamento_id = :medicamento_id
              AND especie_code = :especie_code
              AND coalesce(peso_min_kg, -1) = coalesce(:peso_min_kg, -1)
              AND coalesce(peso_max_kg, -1) = coalesce(:peso_max_kg, -1)
            LIMIT 1
            """
        ),
        {
            'medicamento_id': medicamento_id,
            'especie_code': especie_code,
            'peso_min_kg': peso_min_kg,
            'peso_max_kg': peso_max_kg,
        },
    ).first()

    payload = {
        'medicamento_id': medicamento_id,
        'especie': especie,
        'especie_code': especie_code,
        'faixa_peso': faixa_peso,
        'via': 'Oral',
        'dose': dose,
        'frequencia': 'Dose única; pode ser repetida a cada 24 horas com segurança, quando clinicamente indicado.',
        'duracao': 'Dose única; repetir conforme necessidade e critério do médico-veterinário.',
        'peso_min_kg': peso_min_kg,
        'peso_max_kg': peso_max_kg,
        'dose_min': 1,
        'dose_max': 1,
        'dose_unidade': 'COMPRIMIDOS_ANIMAL',
        'intervalo_horas': 24,
        'intervalo_min_horas': 24,
        'intervalo_max_horas': 24,
        'duracao_min_dias': 1,
        'duracao_max_dias': 1,
        'dose_raw_text': dose,
        'observacao': observacao,
        'indicacao': 'Controle de pulgas e miiase',
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
        return

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


def upgrade() -> None:
    bind = op.get_bind()
    medicamento_id = _buscar_capstar_id(bind)
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
            'classificacao': 'Ectoparasiticida',
            'via_administracao': 'Oral',
            'dosagem_recomendada': (
                'Dose terapêutica de 1 mg/kg por via oral. Gatos e cães até 11,4 kg: '
                '1 comprimido de 11,4 mg por animal. Cães de 11,4 a 57 kg: '
                '1 comprimido de 57 mg por animal.'
            ),
            'frequencia': 'Dose única; pode ser repetida a cada 24 horas com segurança, conforme necessidade clínica.',
            'duracao_tratamento': (
                'Dose única. Pode ser readministrado a cada 24 horas conforme necessidade e critério do médico-veterinário. '
                'Permanece por até 24 horas em cães e até 72 horas em gatos.'
            ),
            'observacoes': (
                'Início de ação a partir de 15 minutos, com eliminação rápida de pulgas adultas. '
                'Também pode ser utilizado como apoio no controle de miíase em cães. '
                'Não administrar mais de uma dose por dia.'
            ),
            'conteudo_estruturado': """
            {
              "indicacoes": {
                "itens": [
                  "Controle rápido de pulgas em cães e gatos.",
                  "Apoio no controle de miíase em cães."
                ],
                "texto": "Capstar pode ser usado para controle rápido de pulgas em cães e gatos e como apoio no controle de miíase em cães."
              },
              "administracao": {
                "itens": [
                  "Administrar por via oral em dose única.",
                  "Pode ser oferecido com ou sem alimento.",
                  "Repetir somente a cada 24 horas, se clinicamente necessário."
                ],
                "texto": "Administrar por via oral em dose única, com ou sem alimento. A repetição deve respeitar intervalo mínimo de 24 horas."
              },
              "observacoes": {
                "itens": [
                  "Início de ação a partir de 15 minutos.",
                  "Pulgas adultas são eliminadas em até 6 horas.",
                  "Não usar mais de uma dose diária."
                ],
                "texto": "Capstar inicia ação rapidamente e não deve ser utilizado mais de uma vez ao dia."
              }
            }
            """,
        },
    )

    _upsert_apresentacao(
        bind,
        medicamento_id,
        nome_variante='Capstar 11,4 mg - Cães e gatos',
        concentracao_texto='11,4 mg',
        concentracao_valor=11.4,
        especie_texto='Cães e Gatos',
    )
    _upsert_apresentacao(
        bind,
        medicamento_id,
        nome_variante='Capstar 57 mg - Cães',
        concentracao_texto='57 mg',
        concentracao_valor=57,
        especie_texto='Cães',
    )

    observacao_dose = (
        'Pode ser repetido a cada 24 horas quando necessário. '
        'Início de ação em cerca de 15 minutos; não administrar mais de uma dose diária.'
    )
    _upsert_dose(
        bind,
        medicamento_id,
        especie_code='AMBOS',
        especie='Cães e Gatos',
        peso_min_kg=None,
        peso_max_kg=11.4,
        faixa_peso='Até 11,4 kg',
        dose='1 comprimido / animal (11,4 mg)',
        observacao=observacao_dose,
    )
    _upsert_dose(
        bind,
        medicamento_id,
        especie_code='CAES',
        especie='Cães',
        peso_min_kg=11.41,
        peso_max_kg=57.0,
        faixa_peso='De 11,4 a 57 kg',
        dose='1 comprimido / animal (57 mg)',
        observacao=observacao_dose,
    )


def downgrade() -> None:
    bind = op.get_bind()
    medicamento_id = _buscar_capstar_id(bind)
    if medicamento_id is None:
        return

    bind.execute(
        sa.text(
            """
            DELETE FROM dose_medicamento
            WHERE medicamento_id = :medicamento_id
              AND indicacao = 'Controle de pulgas e miiase'
            """
        ),
        {'medicamento_id': medicamento_id},
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM apresentacao_medicamento
            WHERE medicamento_id = :medicamento_id
              AND nome_variante IN (
                'Capstar 11,4 mg - Cães e gatos',
                'Capstar 57 mg - Cães'
              )
            """
        ),
        {'medicamento_id': medicamento_id},
    )
