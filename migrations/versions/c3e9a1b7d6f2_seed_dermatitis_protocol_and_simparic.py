"""seed dermatitis protocol and consolidate Simparic

Revision ID: c3e9a1b7d6f2
Revises: 1a2b3c4d5e6f
Create Date: 2026-05-12 09:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c3e9a1b7d6f2'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


protocolo_clinico = sa.table(
    'protocolo_clinico',
    sa.column('id', sa.Integer()),
    sa.column('nome', sa.String(length=120)),
    sa.column('suspeita_principal', sa.String(length=160)),
    sa.column('especie', sa.String(length=40)),
    sa.column('sinais_gatilho', sa.Text()),
    sa.column('conduta_sugerida', sa.Text()),
    sa.column('orientacoes_tutor', sa.Text()),
    sa.column('alertas', sa.Text()),
    sa.column('prioridade', sa.Integer()),
    sa.column('versao', sa.Integer()),
    sa.column('ativo', sa.Boolean()),
    sa.column('clinica_id', sa.Integer()),
)

protocolo_clinico_medicamento = sa.table(
    'protocolo_clinico_medicamento',
    sa.column('id', sa.Integer()),
    sa.column('protocolo_id', sa.Integer()),
    sa.column('medicamento_id', sa.Integer()),
    sa.column('nome_medicamento', sa.String(length=120)),
    sa.column('justificativa', sa.Text()),
    sa.column('dosagem_texto', sa.Text()),
    sa.column('frequencia_texto', sa.Text()),
    sa.column('duracao_texto', sa.Text()),
    sa.column('observacoes', sa.Text()),
    sa.column('indicacao', sa.String(length=120)),
    sa.column('prioridade', sa.Integer()),
)


def _buscar_medicamento_id(bind, termo_principal: str, like_termo: str | None = None) -> int | None:
    row = bind.execute(
        sa.text(
            """
            SELECT id
            FROM medicamento
            WHERE lower(nome) = lower(:termo_principal)
               OR lower(principio_ativo) = lower(:termo_principal)
               OR (:like_termo IS NOT NULL AND lower(nome) LIKE lower(:like_termo))
               OR (:like_termo IS NOT NULL AND lower(principio_ativo) LIKE lower(:like_termo))
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


def _consolidar_simparic(bind) -> int | None:
    rows = bind.execute(
        sa.text(
            """
            SELECT id
            FROM medicamento
            WHERE lower(nome) = 'simparic'
               OR lower(nome) LIKE 'simparic%'
               OR lower(principio_ativo) = 'sarolaner'
            ORDER BY
                CASE WHEN lower(nome) = 'simparic' THEN 0 ELSE 1 END,
                char_length(nome),
                id
            """
        )
    ).fetchall()
    if not rows:
        seed_user_id = bind.execute(sa.text('SELECT id FROM "user" ORDER BY id LIMIT 1')).scalar_one_or_none()
        if seed_user_id is None:
            return None
        canonical_id = bind.execute(
            sa.text(
                """
                INSERT INTO medicamento (
                    nome,
                    classificacao,
                    principio_ativo,
                    via_administracao,
                    dosagem_recomendada,
                    frequencia,
                    duracao_tratamento,
                    observacoes,
                    species_scope,
                    created_by
                ) VALUES (
                    'Simparic',
                    'Ectoparasiticida',
                    'Sarolaner',
                    'Oral',
                    'Escolher apresentacao conforme peso. Dose minima de sarolaner: 2 mg/kg.',
                    'A cada 30 dias',
                    'Conforme protocolo e criterio do medico-veterinario',
                    'Item consolidado para permitir que o veterinario selecione a apresentacao adequada conforme peso do animal.',
                    'CG',
                    :seed_user_id
                )
                RETURNING id
                """
            ),
            {'seed_user_id': seed_user_id},
        ).scalar_one()
        _upsert_alias(bind, 'Simparic', canonical_id)
        _upsert_alias(bind, 'Sarolaner', canonical_id)
        _upsert_simparic_apresentacoes(bind, canonical_id)
        _upsert_simparic_doses(bind, canonical_id)
        return canonical_id

    canonical_id = rows[0][0]
    duplicate_ids = [row[0] for row in rows[1:]]

    bind.execute(
        sa.text(
            """
            UPDATE medicamento
            SET nome = 'Simparic',
                classificacao = 'Ectoparasiticida',
                principio_ativo = 'Sarolaner',
                via_administracao = 'Oral',
                dosagem_recomendada = 'Escolher apresentacao conforme peso. Dose minima de sarolaner: 2 mg/kg.',
                frequencia = 'A cada 30 dias',
                duracao_tratamento = 'Conforme protocolo e criterio do medico-veterinario',
                observacoes = :observacoes,
                species_scope = 'CG'
            WHERE id = :canonical_id
            """
        ),
        {
            'canonical_id': canonical_id,
            'observacoes': (
                'Item consolidado para permitir que o veterinario selecione a apresentacao '
                'adequada conforme peso do animal no momento da prescricao.'
            ),
        },
    )

    if duplicate_ids:
        bind.execute(
            sa.text(
                """
                UPDATE apresentacao_medicamento
                SET medicamento_id = :canonical_id
                WHERE medicamento_id IN :duplicate_ids
                """
            ).bindparams(sa.bindparam('duplicate_ids', expanding=True)),
            {'canonical_id': canonical_id, 'duplicate_ids': duplicate_ids},
        )
        bind.execute(
            sa.text(
                """
                UPDATE dose_medicamento
                SET medicamento_id = :canonical_id
                WHERE medicamento_id IN :duplicate_ids
                """
            ).bindparams(sa.bindparam('duplicate_ids', expanding=True)),
            {'canonical_id': canonical_id, 'duplicate_ids': duplicate_ids},
        )
        bind.execute(
            sa.text(
                """
                UPDATE prescricao_alias_medicamento
                SET medicamento_id = :canonical_id,
                    confianca = 'manual'
                WHERE medicamento_id IN :duplicate_ids
                """
            ).bindparams(sa.bindparam('duplicate_ids', expanding=True)),
            {'canonical_id': canonical_id, 'duplicate_ids': duplicate_ids},
        )
        bind.execute(
            sa.text(
                """
                UPDATE protocolo_clinico_medicamento
                SET medicamento_id = :canonical_id
                WHERE medicamento_id IN :duplicate_ids
                """
            ).bindparams(sa.bindparam('duplicate_ids', expanding=True)),
            {'canonical_id': canonical_id, 'duplicate_ids': duplicate_ids},
        )
        bind.execute(
            sa.text(
                """
                DELETE FROM medicamento_favorito
                WHERE medicamento_id IN :duplicate_ids
                  AND EXISTS (
                    SELECT 1
                    FROM medicamento_favorito fav_canonico
                    WHERE fav_canonico.user_id = medicamento_favorito.user_id
                      AND fav_canonico.medicamento_id = :canonical_id
                  )
                """
            ).bindparams(sa.bindparam('duplicate_ids', expanding=True)),
            {'canonical_id': canonical_id, 'duplicate_ids': duplicate_ids},
        )
        bind.execute(
            sa.text(
                """
                UPDATE medicamento_favorito
                SET medicamento_id = :canonical_id
                WHERE medicamento_id IN :duplicate_ids
                """
            ).bindparams(sa.bindparam('duplicate_ids', expanding=True)),
            {'canonical_id': canonical_id, 'duplicate_ids': duplicate_ids},
        )
        bind.execute(
            sa.text(
                "DELETE FROM medicamento WHERE id IN :duplicate_ids"
            ).bindparams(sa.bindparam('duplicate_ids', expanding=True)),
            {'duplicate_ids': duplicate_ids},
        )

    _upsert_alias(bind, 'Simparic', canonical_id)
    _upsert_alias(bind, 'Sarolaner', canonical_id)
    _upsert_simparic_apresentacoes(bind, canonical_id)
    _upsert_simparic_doses(bind, canonical_id)
    return canonical_id


def _upsert_simparic_apresentacoes(bind, medicamento_id: int) -> None:
    variantes = [
        (5, 'Antipulgas Zoetis Simparic 5 mg para Caes 1,3 a 2,5 Kg'),
        (10, 'Antipulgas Zoetis Simparic 10 mg para Caes 2,6 a 5 Kg'),
        (20, 'Antipulgas Zoetis Simparic 20 mg para Caes 5,1 a 10 Kg'),
        (40, 'Antipulgas Zoetis Simparic 40 mg para Caes 10,1 a 20 Kg'),
        (80, 'Antipulgas Zoetis Simparic 80 mg para Caes 20,1 a 40 Kg'),
        (120, 'Antipulgas Zoetis Simparic 120 mg para Caes 40,1 a 60 Kg'),
    ]
    for mg, nome_variante in variantes:
        existente = bind.execute(
            sa.text(
                """
                SELECT id
                FROM apresentacao_medicamento
                WHERE medicamento_id = :medicamento_id
                  AND lower(forma) = 'comprimido mastigavel'
                  AND concentracao = :concentracao
                LIMIT 1
                """
            ),
            {'medicamento_id': medicamento_id, 'concentracao': f'{mg} mg'},
        ).first()
        payload = {
            'medicamento_id': medicamento_id,
            'forma': 'Comprimido mastigavel',
            'concentracao': f'{mg} mg',
            'nome_variante': nome_variante,
            'concentracao_valor': mg,
            'concentracao_unidade': 'mg',
            'volume_valor': 1,
            'volume_unidade': 'un',
            'fabricante': 'Zoetis',
        }
        if existente:
            bind.execute(
                sa.text(
                    """
                    UPDATE apresentacao_medicamento
                    SET nome_variante = :nome_variante,
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
        else:
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


def _upsert_simparic_doses(bind, medicamento_id: int) -> None:
    faixas = [
        (1.30, 2.50, 5),
        (2.60, 5.00, 10),
        (5.10, 10.00, 20),
        (10.10, 20.00, 40),
        (20.10, 40.00, 80),
        (40.10, 60.00, 120),
    ]
    for peso_min, peso_max, mg in faixas:
        existente = bind.execute(
            sa.text(
                """
                SELECT id
                FROM dose_medicamento
                WHERE medicamento_id = :medicamento_id
                  AND dose_unidade = 'COMPRIMIDOS_ANIMAL'
                  AND peso_min_kg = :peso_min
                  AND peso_max_kg = :peso_max
                LIMIT 1
                """
            ),
            {'medicamento_id': medicamento_id, 'peso_min': peso_min, 'peso_max': peso_max},
        ).first()
        payload = {
            'medicamento_id': medicamento_id,
            'especie': 'Caes',
            'faixa_peso': f'{peso_min:g} a {peso_max:g} kg',
            'via': 'Oral',
            'dose': f'1 comprimido / animal ({mg} mg)',
            'frequencia': 'A cada 30 dias',
            'duracao': 'Conforme protocolo e criterio do medico-veterinario',
            'especie_code': 'CAES',
            'peso_min_kg': peso_min,
            'peso_max_kg': peso_max,
            'dose_min': 1,
            'dose_max': 1,
            'dose_unidade': 'COMPRIMIDOS_ANIMAL',
            'intervalo_horas': 720,
            'intervalo_min_horas': 672,
            'intervalo_max_horas': 720,
            'duracao_min_dias': None,
            'duracao_max_dias': None,
            'dose_raw_text': f'Simparic {mg} mg: 1 comprimido para caes de {peso_min:g} a {peso_max:g} kg.',
            'observacao': 'Selecionar a apresentacao conforme peso atual do animal.',
            'indicacao': 'Controle de ectoparasitas',
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
                        dose_min = :dose_min,
                        dose_max = :dose_max,
                        intervalo_horas = :intervalo_horas,
                        intervalo_min_horas = :intervalo_min_horas,
                        intervalo_max_horas = :intervalo_max_horas,
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


def upgrade() -> None:
    bind = op.get_bind()
    simparic_id = _consolidar_simparic(bind)

    medicamentos = {
        'Shampoo de clorexidina': _buscar_medicamento_id(bind, 'Clorexidina', '%clorexidina%'),
        'Pomada de neomicina, betametasona e cetoconazol': _buscar_medicamento_id(
            bind,
            'Cetoconazol + Betametasona + Neomicina',
            '%cetoconazol%neomicina%',
        ),
        'Simparic': simparic_id,
        'Prednisona': _buscar_medicamento_id(bind, 'Prednisona', 'Prednisona%'),
    }

    existing_protocol = bind.execute(
        sa.select(sa.column('id'))
        .select_from(sa.text('protocolo_clinico'))
        .where(
            sa.text(
                "nome = :nome AND suspeita_principal = :suspeita_principal AND clinica_id IS NULL"
            )
        ),
        {
            'nome': 'Protocolo Inicial para Dermatites',
            'suspeita_principal': 'dermatite',
        },
    ).first()
    if existing_protocol:
        protocol_id = existing_protocol[0]
    else:
        protocol_id = bind.execute(
            sa.insert(protocolo_clinico).returning(sa.column('id')),
            {
                'nome': 'Protocolo Inicial para Dermatites',
                'suspeita_principal': 'dermatite',
                'especie': 'cao',
                'sinais_gatilho': (
                    'Prurido, coceira, eritema, alopecia, descamacao, crostas, lesoes cutaneas, '
                    'otite associada, suspeita de dermatite alergica ou infeccao secundaria.'
                ),
                'conduta_sugerida': (
                    'Avaliar distribuicao das lesoes, intensidade do prurido, ectoparasitas e sinais de '
                    'infeccao secundaria. Limpar a pele quando indicado e revisar necessidade de exames '
                    'complementares antes de manter corticoide ou antimicrobiano.'
                ),
                'orientacoes_tutor': (
                    'Evitar automedicacao e retorno se houver piora, apatia, secrecao, feridas extensas '
                    'ou ausencia de resposta ao tratamento inicial.'
                ),
                'alertas': (
                    'Prednisona deve ser usada apenas apos avaliacao do medico-veterinario, com cautela '
                    'em infeccao ativa, diabetes, gestacao, doenca hepatica/renal ou uso concomitante de AINE.'
                ),
                'prioridade': 3,
                'versao': 1,
                'ativo': True,
                'clinica_id': None,
            },
        ).scalar_one()

    bind.execute(
        sa.text('DELETE FROM protocolo_clinico_medicamento WHERE protocolo_id = :protocol_id'),
        {'protocol_id': protocol_id},
    )
    bind.execute(
        sa.insert(protocolo_clinico_medicamento),
        [
            {
                'protocolo_id': protocol_id,
                'medicamento_id': medicamentos['Shampoo de clorexidina'],
                'nome_medicamento': 'Shampoo de clorexidina - 0,20%, frasco (500mL)',
                'justificativa': 'Higienizacao e apoio topico em dermatites com suspeita de infeccao secundaria.',
                'dosagem_texto': 'Aplicar sobre a pelagem umedecida, massagear e deixar agir por 5 a 10 minutos; enxaguar bem e repetir o processo uma vez.',
                'frequencia_texto': '1 vez por semana',
                'duracao_texto': '3 meses',
                'observacoes': 'Banhos semanais.',
                'indicacao': 'Uso topico',
                'prioridade': 1,
            },
            {
                'protocolo_id': protocol_id,
                'medicamento_id': medicamentos['Pomada de neomicina, betametasona e cetoconazol'],
                'nome_medicamento': 'Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g + Sulfato de Neomicina 2,5mg/g Generico C',
                'justificativa': 'Uso topico em lesoes localizadas quando houver indicacao clinica.',
                'dosagem_texto': 'Aplicar uma camada fina sobre a area afetada',
                'frequencia_texto': '2 vezes ao dia',
                'duracao_texto': '10 dias',
                'observacoes': 'Aplicacao topica conforme orientacao do protocolo.',
                'indicacao': 'Uso topico dermatologico',
                'prioridade': 2,
            },
            {
                'protocolo_id': protocol_id,
                'medicamento_id': medicamentos['Simparic'],
                'nome_medicamento': 'Simparic',
                'justificativa': 'Controle de ectoparasitas conforme peso do animal quando indicado.',
                'dosagem_texto': '',
                'frequencia_texto': 'a cada 30 dias',
                'duracao_texto': 'conforme protocolo',
                'observacoes': 'Item consolidado: escolher a dosagem/apresentacao na prescricao de acordo com o peso.',
                'indicacao': 'Controle de ectoparasitas',
                'prioridade': 3,
            },
            {
                'protocolo_id': protocol_id,
                'medicamento_id': medicamentos['Prednisona'],
                'nome_medicamento': 'Prednisona',
                'justificativa': 'Controle de prurido/inflamacao quando indicado e sem contraindicacoes relevantes.',
                'dosagem_texto': '',
                'frequencia_texto': '',
                'duracao_texto': '',
                'observacoes': 'Reavaliar infeccao secundaria e evitar associacao com AINE sem criterio clinico.',
                'indicacao': 'Controle de prurido',
                'prioridade': 4,
            },
        ],
    )

    for nome, medicamento_id in medicamentos.items():
        _upsert_alias(bind, nome, medicamento_id)
    _upsert_alias(bind, 'Pomada de neomicina betametasona cetoconazol', medicamentos['Pomada de neomicina, betametasona e cetoconazol'])
    _upsert_alias(bind, 'Shampoo clorexidina', medicamentos['Shampoo de clorexidina'])
    _upsert_alias(bind, 'Shampoo de clorexidina - 0,20%, frasco (500mL)', medicamentos['Shampoo de clorexidina'])
    _upsert_alias(bind, 'Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g + Sulfato de Neomicina 2,5mg/g Generico C', medicamentos['Pomada de neomicina, betametasona e cetoconazol'])


def downgrade() -> None:
    bind = op.get_bind()
    protocol_id = bind.execute(
        sa.select(sa.column('id'))
        .select_from(sa.text('protocolo_clinico'))
        .where(
            sa.text(
                "nome = :nome AND suspeita_principal = :suspeita_principal AND clinica_id IS NULL"
            )
        ),
        {
            'nome': 'Protocolo Inicial para Dermatites',
            'suspeita_principal': 'dermatite',
        },
    ).scalar_one_or_none()
    if protocol_id is not None:
        bind.execute(
            sa.text('DELETE FROM protocolo_clinico_medicamento WHERE protocolo_id = :protocol_id'),
            {'protocol_id': protocol_id},
        )
        bind.execute(
            sa.text('DELETE FROM protocolo_clinico WHERE id = :protocol_id'),
            {'protocol_id': protocol_id},
        )

    bind.execute(
        sa.text(
            """
            DELETE FROM prescricao_alias_medicamento
            WHERE nome_prescrito IN (
                'Shampoo de clorexidina',
                'Shampoo clorexidina',
                'Shampoo de clorexidina - 0,20%, frasco (500mL)',
                'Pomada de neomicina, betametasona e cetoconazol',
                'Pomada de neomicina betametasona cetoconazol',
                'Cetoconazol 20mg/g + Dipropionato de Betametasona 0,64mg/g + Sulfato de Neomicina 2,5mg/g Generico C',
                'Simparic',
                'Sarolaner',
                'Prednisona'
            )
              AND confianca = 'manual'
            """
        )
    )
