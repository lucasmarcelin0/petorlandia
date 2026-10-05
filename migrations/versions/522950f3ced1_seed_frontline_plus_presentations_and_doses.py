"""seed frontline plus presentations and doses

Revision ID: 522950f3ced1
Revises: f4e8b2c6a901
Create Date: 2026-10-05 11:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '522950f3ced1'
down_revision = 'a7d3c1e9f4b2'
branch_labels = None
depends_on = None


APRESENTACOES_FRONTLINE = [
    {
        "forma": "Pipeta",
        "concentracao": "Gatos até 10 Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus gatos até 10 Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 0.50,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães até 10 Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães até 10 Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 0.67,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães de 10 Kg a 20Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães de 10 Kg a 20Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 1.34,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães de 20 Kg a 40Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães de 20 Kg a 40Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 2.68,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães de 40 Kg a 60Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães de 40 Kg a 60Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 4.02,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
]

DOSES_FRONTLINE = [
    {
        "especie": "Gatos",
        "especie_code": "GATOS",
        "faixa_peso": "Até 10 kg",
        "peso_min_kg": 0.00,
        "peso_max_kg": 10.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (0,5 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Gatos até 10 kg: 1 pipeta (0,5 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca do felino, afastando os pelos para evitar lambedura.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "Até 10 kg",
        "peso_min_kg": 0.00,
        "peso_max_kg": 10.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (0,67 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães até 10 kg: 1 pipeta (0,67 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "10 a 20 kg",
        "peso_min_kg": 10.01,
        "peso_max_kg": 20.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (1,34 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães de 10 a 20 kg: 1 pipeta (1,34 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "20 a 40 kg",
        "peso_min_kg": 20.01,
        "peso_max_kg": 40.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (2,68 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães de 20 a 40 kg: 1 pipeta (2,68 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "40 a 60 kg",
        "peso_min_kg": 40.01,
        "peso_max_kg": 60.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (4,02 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães de 40 a 60 kg: 1 pipeta (4,02 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
]

ALIASES_FRONTLINE = [
    "Frontline",
    "Frontline Plus",
    "Frontline® Plus",
    "Fipronil",
    "Fipronil + (S)-Metopreno",
    "Frontline Plus Cães",
    "Frontline Plus Gatos",
    "Frontline Plus – Gatos até 10 Kg, pipeta (1 un)",
    "Frontline Plus – Cães até 10 Kg, pipeta (1 un)",
    "Frontline Plus – Cães de 10 Kg a 20Kg, pipeta (1 un)",
    "Frontline Plus – Cães de 20 Kg a 40Kg, pipeta (1 un)",
    "Frontline Plus – Cães de 40 Kg a 60Kg, pipeta (1 un)",
]


def upgrade():
    bind = op.get_bind()

    # 1. Encontra usuário criador
    user_row = bind.execute(sa.text('SELECT id FROM "user" ORDER BY id LIMIT 1')).first()
    if not user_row:
        return
    seed_user_id = user_row[0]

    # 2. Busca ou cria medicamento
    med_row = bind.execute(
        sa.text(
            """
            SELECT id FROM medicamento
            WHERE lower(nome) = 'frontline plus'
               OR lower(nome) = 'frontline'
               OR vetsmart_produto_id = 63
            ORDER BY id
            LIMIT 1
            """
        )
    ).first()

    if med_row:
        med_id = med_row[0]
        bind.execute(
            sa.text(
                """
                UPDATE medicamento
                SET nome = 'Frontline Plus',
                    classificacao = 'Ectoparasiticida',
                    principio_ativo = 'Fipronil + (S)-Metopreno',
                    via_administracao = 'Tópica',
                    species_scope = 'CG',
                    vetsmart_produto_id = 63
                WHERE id = :med_id
                """
            ),
            {"med_id": med_id},
        )
    else:
        med_id = bind.execute(
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
                    vetsmart_produto_id,
                    created_by
                ) VALUES (
                    'Frontline Plus',
                    'Ectoparasiticida',
                    'Fipronil + (S)-Metopreno',
                    'Tópica',
                    '1 pipeta / animal conforme a espécie e faixa de peso',
                    'A cada 30 dias',
                    'Dose única (repetir mensalmente para controle contínuo)',
                    'Afaste os pelos do animal na região da nuca ou entre as escápulas até que a pele fique visível. Aplique todo o conteúdo da pipeta diretamente sobre a pele seca. Evitar banhos ou natação 48 horas antes e após a aplicação.',
                    'CG',
                    63,
                    :created_by
                )
                """
            ),
            {"created_by": seed_user_id},
        ).lastrowid

        if not med_id:
            row = bind.execute(sa.text("SELECT id FROM medicamento WHERE lower(nome) = 'frontline plus'")).first()
            med_id = row[0] if row else None

    if not med_id:
        return

    # 3. Apresentações
    for item in APRESENTACOES_FRONTLINE:
        existente = bind.execute(
            sa.text(
                """
                SELECT id FROM apresentacao_medicamento
                WHERE medicamento_id = :med_id
                  AND (concentracao = :conc OR nome_variante = :var)
                LIMIT 1
                """
            ),
            {"med_id": med_id, "conc": item["concentracao"], "var": item["nome_variante"]},
        ).first()

        params = {**item, "med_id": med_id}
        if existente:
            bind.execute(
                sa.text(
                    """
                    UPDATE apresentacao_medicamento
                    SET forma = :forma,
                        concentracao = :concentracao,
                        nome_variante = :nome_variante,
                        nome_comercial = :nome_comercial,
                        volume_valor = :volume_valor,
                        volume_unidade = :volume_unidade,
                        fabricante = :fabricante,
                        vetsmart_produto_id = :vetsmart_produto_id
                    WHERE id = :id
                    """
                ),
                {**params, "id": existente[0]},
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
                        nome_comercial,
                        volume_valor,
                        volume_unidade,
                        fabricante,
                        vetsmart_produto_id
                    ) VALUES (
                        :med_id,
                        :forma,
                        :concentracao,
                        :nome_variante,
                        :nome_comercial,
                        :volume_valor,
                        :volume_unidade,
                        :fabricante,
                        :vetsmart_produto_id
                    )
                    """
                ),
                params,
            )

    # 4. Doses
    for item in DOSES_FRONTLINE:
        existente = bind.execute(
            sa.text(
                """
                SELECT id FROM dose_medicamento
                WHERE medicamento_id = :med_id
                  AND especie_code = :especie_code
                  AND faixa_peso = :faixa_peso
                  AND dose_unidade = :dose_unidade
                LIMIT 1
                """
            ),
            {
                "med_id": med_id,
                "especie_code": item["especie_code"],
                "faixa_peso": item["faixa_peso"],
                "dose_unidade": item["dose_unidade"],
            },
        ).first()

        params = {**item, "med_id": med_id}
        if existente:
            bind.execute(
                sa.text(
                    """
                    UPDATE dose_medicamento
                    SET especie = :especie,
                        especie_code = :especie_code,
                        faixa_peso = :faixa_peso,
                        peso_min_kg = :peso_min_kg,
                        peso_max_kg = :peso_max_kg,
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
                        dose_raw_text = :dose_raw_text,
                        observacao = :observacao,
                        indicacao = :indicacao,
                        fonte = :fonte,
                        confianca = :confianca
                    WHERE id = :id
                    """
                ),
                {**params, "id": existente[0]},
            )
        else:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO dose_medicamento (
                        medicamento_id,
                        especie,
                        especie_code,
                        faixa_peso,
                        peso_min_kg,
                        peso_max_kg,
                        via,
                        dose,
                        frequencia,
                        duracao,
                        dose_min,
                        dose_max,
                        dose_unidade,
                        intervalo_horas,
                        intervalo_min_horas,
                        intervalo_max_horas,
                        dose_raw_text,
                        observacao,
                        indicacao,
                        fonte,
                        confianca
                    ) VALUES (
                        :med_id,
                        :especie,
                        :especie_code,
                        :faixa_peso,
                        :peso_min_kg,
                        :peso_max_kg,
                        :via,
                        :dose,
                        :frequencia,
                        :duracao,
                        :dose_min,
                        :dose_max,
                        :dose_unidade,
                        :intervalo_horas,
                        :intervalo_min_horas,
                        :intervalo_max_horas,
                        :dose_raw_text,
                        :observacao,
                        :indicacao,
                        :fonte,
                        :confianca
                    )
                    """
                ),
                params,
            )

    # 5. Aliases
    for alias_nome in ALIASES_FRONTLINE:
        existente = bind.execute(
            sa.text("SELECT id FROM prescricao_alias_medicamento WHERE nome_prescrito = :nome"),
            {"nome": alias_nome},
        ).first()

        if existente:
            bind.execute(
                sa.text("UPDATE prescricao_alias_medicamento SET medicamento_id = :med_id, confianca = 'manual' WHERE id = :id"),
                {"med_id": med_id, "id": existente[0]},
            )
        else:
            bind.execute(
                sa.text("INSERT INTO prescricao_alias_medicamento (nome_prescrito, medicamento_id, confianca) VALUES (:nome, :med_id, 'manual')"),
                {"nome": alias_nome, "med_id": med_id},
            )


def downgrade():
    bind = op.get_bind()
    med_row = bind.execute(sa.text("SELECT id FROM medicamento WHERE lower(nome) = 'frontline plus'")).first()
    if med_row:
        med_id = med_row[0]
        bind.execute(sa.text("DELETE FROM prescricao_alias_medicamento WHERE medicamento_id = :med_id"), {"med_id": med_id})
        bind.execute(sa.text("DELETE FROM dose_medicamento WHERE medicamento_id = :med_id"), {"med_id": med_id})
        bind.execute(sa.text("DELETE FROM apresentacao_medicamento WHERE medicamento_id = :med_id"), {"med_id": med_id})
        bind.execute(sa.text("DELETE FROM medicamento WHERE id = :med_id"), {"med_id": med_id})
