"""fix dermatitis protocol prescription precision

Revision ID: e4a1c9d2b6f7
Revises: c3e9a1b7d6f2
Create Date: 2026-05-12 12:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e4a1c9d2b6f7'
down_revision = 'c3e9a1b7d6f2'
branch_labels = None
depends_on = None


def _find_protocol_id(bind) -> int | None:
    return bind.execute(
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


def _find_simparic_id(bind) -> int | None:
    return bind.execute(
        sa.text(
            """
            SELECT id
            FROM medicamento
            WHERE lower(nome) = 'simparic'
               OR lower(principio_ativo) = 'sarolaner'
            ORDER BY CASE WHEN lower(nome) = 'simparic' THEN 0 ELSE 1 END, id
            LIMIT 1
            """
        )
    ).scalar_one_or_none()


def upgrade() -> None:
    bind = op.get_bind()
    protocolo_id = _find_protocol_id(bind)

    if protocolo_id is not None:
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET nome_medicamento = 'Shampoo de clorexidina - 0,20%, frasco (500mL)',
                    dosagem_texto = 'Aplicar sobre a pelagem umedecida, massagear e deixar agir por 5 a 10 minutos; enxaguar bem e repetir o processo uma vez.',
                    frequencia_texto = '1 vez por semana',
                    duracao_texto = '3 meses',
                    observacoes = 'Banhos semanais.',
                    indicacao = 'Uso topico'
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
                SET nome_medicamento = 'Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g + Sulfato de Neomicina 2,5mg/g Generico C',
                    dosagem_texto = 'Aplicar uma camada fina sobre a area afetada',
                    frequencia_texto = '2 vezes ao dia',
                    duracao_texto = '10 dias',
                    observacoes = 'Aplicacao topica conforme orientacao do protocolo.',
                    indicacao = 'Uso topico dermatologico'
                WHERE protocolo_id = :protocolo_id
                  AND lower(nome_medicamento) like '%cetoconazol%'
                """
            ),
            {'protocolo_id': protocolo_id},
        )
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET dosagem_texto = '',
                    frequencia_texto = 'a cada 30 dias',
                    duracao_texto = 'conforme protocolo mensal',
                    observacoes = 'Ao aplicar na receita, usar a apresentacao final compativel com o peso do animal.',
                    indicacao = 'Controle de ectoparasitas'
                WHERE protocolo_id = :protocolo_id
                  AND lower(nome_medicamento) = 'simparic'
                """
            ),
            {'protocolo_id': protocolo_id},
        )
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET dosagem_texto = '',
                    frequencia_texto = '',
                    duracao_texto = '',
                    indicacao = 'Alergia',
                    observacoes = 'Calcular dose automaticamente pelo peso do animal e revisar contraindicacoes clinicas.'
                WHERE protocolo_id = :protocolo_id
                  AND lower(nome_medicamento) = 'prednisona'
                """
            ),
            {'protocolo_id': protocolo_id},
        )

    simparic_id = _find_simparic_id(bind)
    if simparic_id is None:
        return

    variantes = [
        (5, 1.3, 2.5, '1,3 a 2,5 Kg', 'Antipulgas Zoetis Simparic 5 mg para Caes 1,3 a 2,5 Kg'),
        (10, 2.6, 5.0, '2,6 a 5 Kg', 'Antipulgas Zoetis Simparic 10 mg para Caes 2,6 a 5 Kg'),
        (20, 5.1, 10.0, '5,1 a 10 Kg', 'Antipulgas Zoetis Simparic 20 mg para Caes 5,1 a 10 Kg'),
        (40, 10.1, 20.0, '10,1 a 20 Kg', 'Antipulgas Zoetis Simparic 40 mg para Caes 10,1 a 20 Kg'),
        (80, 20.1, 40.0, '20,1 a 40 Kg', 'Antipulgas Zoetis Simparic 80 mg para Caes 20,1 a 40 Kg'),
        (120, 40.1, 60.0, '40,1 a 60 Kg', 'Antipulgas Zoetis Simparic 120 mg para Caes 40,1 a 60 Kg'),
    ]
    for mg, peso_min, peso_max, faixa_label, nome_variante in variantes:
        bind.execute(
            sa.text(
                """
                UPDATE apresentacao_medicamento
                SET nome_variante = :nome_variante,
                    forma = 'Comprimido mastigavel',
                    fabricante = 'Zoetis'
                WHERE medicamento_id = :medicamento_id
                  AND concentracao_valor = :mg
                  AND lower(concentracao_unidade) = 'mg'
                """
            ),
            {'medicamento_id': simparic_id, 'mg': mg, 'nome_variante': nome_variante},
        )
        bind.execute(
            sa.text(
                """
                UPDATE dose_medicamento
                SET faixa_peso = :faixa_label,
                    frequencia = 'A cada 30 dias',
                    duracao = 'Conforme protocolo mensal',
                    intervalo_horas = NULL,
                    intervalo_min_horas = NULL,
                    intervalo_max_horas = NULL,
                    duracao_min_dias = NULL,
                    duracao_max_dias = NULL,
                    observacao = 'Selecionar a apresentacao compativel com a faixa de peso do animal.',
                    dose_raw_text = :dose_raw_text,
                    indicacao = 'Controle de ectoparasitas'
                WHERE medicamento_id = :medicamento_id
                  AND dose_unidade = 'COMPRIMIDOS_ANIMAL'
                  AND peso_min_kg = :peso_min
                  AND peso_max_kg = :peso_max
                """
            ),
            {
                'medicamento_id': simparic_id,
                'faixa_label': faixa_label,
                'peso_min': peso_min,
                'peso_max': peso_max,
                'dose_raw_text': f'{nome_variante}: 1 comprimido por administracao.',
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    protocolo_id = _find_protocol_id(bind)

    if protocolo_id is not None:
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET nome_medicamento = 'Shampoo de clorexidina',
                    dosagem_texto = NULL,
                    frequencia_texto = 'conforme avaliacao clinica',
                    duracao_texto = 'conforme evolucao da pele',
                    observacoes = 'Evitar contato com olhos e mucosas; orientar tempo de contato e enxague quando aplicavel.',
                    indicacao = 'Uso topico'
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
                SET nome_medicamento = 'Pomada de neomicina, betametasona e cetoconazol',
                    dosagem_texto = NULL,
                    frequencia_texto = 'conforme avaliacao clinica',
                    duracao_texto = 'conforme evolucao da lesao',
                    observacoes = 'Evitar uso em lesoes extensas, profundas ou ulceradas sem reavaliacao.',
                    indicacao = 'Uso topico dermatologico'
                WHERE protocolo_id = :protocolo_id
                  AND lower(nome_medicamento) like '%cetoconazol%'
                """
            ),
            {'protocolo_id': protocolo_id},
        )
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET dosagem_texto = 'Selecionar apresentacao conforme peso',
                    frequencia_texto = 'a cada 30 dias',
                    duracao_texto = 'conforme protocolo',
                    observacoes = 'Item consolidado: escolher a dosagem/apresentacao na prescricao de acordo com o peso.',
                    indicacao = 'Controle de ectoparasitas'
                WHERE protocolo_id = :protocolo_id
                  AND lower(nome_medicamento) = 'simparic'
                """
            ),
            {'protocolo_id': protocolo_id},
        )
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET indicacao = 'Controle de prurido',
                    observacoes = 'Reavaliar infeccao secundaria e evitar associacao com AINE sem criterio clinico.'
                WHERE protocolo_id = :protocolo_id
                  AND lower(nome_medicamento) = 'prednisona'
                """
            ),
            {'protocolo_id': protocolo_id},
        )

    simparic_id = _find_simparic_id(bind)
    if simparic_id is None:
        return

    bind.execute(
        sa.text(
            """
            UPDATE dose_medicamento
            SET frequencia = 'A cada 30 dias',
                duracao = 'Conforme protocolo e criterio do medico-veterinario',
                intervalo_horas = 720,
                intervalo_min_horas = 672,
                intervalo_max_horas = 720
            WHERE medicamento_id = :medicamento_id
              AND dose_unidade = 'COMPRIMIDOS_ANIMAL'
            """
        ),
        {'medicamento_id': simparic_id},
    )
