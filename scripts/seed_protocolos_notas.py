# -*- coding: utf-8 -*-
"""Seed dos protocolos clínicos curados das notas de atendimento do veterinário.

Conteúdo transcrito das notas pessoais (PDF, out/2025) — doses e condutas são
as anotadas pelo próprio veterinário; campos sem informação nas notas ficam
como "conforme avaliação clínica" em vez de inventados.

Idempotente: protocolos são identificados por nome global (clinica_id NULL);
se já existirem, não duplica. Padrão é SIMULAÇÃO; use --apply para gravar.

Ex.: heroku run "python scripts/seed_protocolos_notas.py --apply"
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PROTOCOLS = [
    {
        "nome": "Fratura / Trauma ortopédico",
        "suspeita_principal": "fratura",
        "especie": None,
        "sinais_gatilho": "Trauma, atropelamento, claudicação, dor intensa, deformidade de membro.",
        "conduta_sugerida": (
            "Analgesia antes de tudo; confirmar com Raio-X nas projeções adequadas "
            "(laterolateral LL e craniocaudal CrCa / médio-lateral ML). Em politrauma/"
            "atropelamento, considerar ultrassom abdominal. Sedação para manejo do animal "
            "agressivo ou politraumatizado: xilazina 0,5 ml/10 kg + cetamina 0,5 ml/10 kg "
            "(antagonista da xilazina: ioimbina)."
        ),
        "orientacoes_tutor": "Restringir movimento do animal; analgesia em casa conforme receita.",
        "alertas": (
            "Opioide: completar a seringa com soro para reduzir o risco de vômito. "
            "AINE sempre após alimentação; não associar AINE com corticoide."
        ),
        "prioridade": 2,
        "medicamentos": [
            {
                "nome_medicamento": "Metadona",
                "dosagem_texto": "0,2 a 0,5 mg/kg (fratura: 0,5 mg/kg)",
                "frequencia_texto": "na clínica, conforme dor",
                "duracao_texto": "uso na clínica",
                "observacoes": "Completar a seringa com soro para reduzir vômito. Alternativa: morfina 0,2–0,5 mg/kg (0,1 ml/10 kg).",
                "justificativa": "Analgesia de dor intensa (fratura) na clínica.",
                "indicacao": "Analgesia (clínica)",
            },
            {
                "nome_medicamento": "Meloxicam",
                "dosagem_texto": "0,1 mg/kg",
                "frequencia_texto": "a cada 24 horas",
                "duracao_texto": "por 5 dias",
                "observacoes": "Sempre após alimentação.",
                "justificativa": "Anti-inflamatório não esteroidal para trauma.",
                "indicacao": "Anti-inflamatório",
            },
            {
                "nome_medicamento": "Dipirona",
                "dosagem_texto": "25 mg/kg (1 ml = 500 mg = 20 gotas)",
                "frequencia_texto": "a cada 8 horas",
                "duracao_texto": "por 3 dias",
                "observacoes": None,
                "justificativa": "Analgesia de manutenção em casa.",
                "indicacao": "Analgesia (casa)",
            },
            {
                "nome_medicamento": "Tramadol",
                "dosagem_texto": "comprimido conforme peso (ex.: 40 mg)",
                "frequencia_texto": "a cada 8 horas",
                "duracao_texto": "por 4 dias",
                "observacoes": None,
                "justificativa": "Analgesia complementar em casa.",
                "indicacao": "Analgesia (casa)",
            },
        ],
        "exames": [
            {
                "nome": "Raio-X",
                "justificativa": "Projeções: laterolateral (LL) e craniocaudal (CrCa) / médio-lateral (ML) do membro acometido.",
            },
            {
                "nome": "Ultrassom abdominal",
                "justificativa": "Em trauma/atropelamento, avaliar lesões internas.",
            },
        ],
        "retornos": [],
    },
    {
        "nome": "Ferida / Lesão de pele",
        "suspeita_principal": "ferida",
        "especie": None,
        "sinais_gatilho": "Ferida cutânea, escoriação, lesão traumática, lesão com secreção.",
        "conduta_sugerida": (
            "Limpeza com soro fisiológico e curativo tópico até a cura. "
            "Se houver infecção bacteriana, associar antibiótico sistêmico."
        ),
        "orientacoes_tutor": "Limpeza e pomada conforme receita; impedir lambedura da lesão.",
        "alertas": "Antibiótico sempre após alimentação.",
        "prioridade": 2,
        "medicamentos": [
            {
                "nome_medicamento": "Furanil (clorexidina) pomada",
                "dosagem_texto": "aplicar na lesão após limpeza com soro",
                "frequencia_texto": "a cada 12 horas",
                "duracao_texto": "até a cura",
                "observacoes": None,
                "justificativa": "Antisséptico tópico de eleição.",
                "indicacao": "Uso tópico",
            },
            {
                "nome_medicamento": "Rifocina spray",
                "dosagem_texto": "aplicar na lesão",
                "frequencia_texto": "conforme prescrição",
                "duracao_texto": "conforme prescrição",
                "observacoes": "Alternativa tópica (ou Dermotrat).",
                "justificativa": "Antisséptico tópico alternativo.",
                "indicacao": "Uso tópico",
            },
            {
                "nome_medicamento": "Cefalexina",
                "dosagem_texto": "conforme peso/bula",
                "frequencia_texto": "a cada 12 horas",
                "duracao_texto": "por 7 dias",
                "observacoes": "Se lesão bacteriana de pele. Sempre após alimentação.",
                "justificativa": "Antibiótico sistêmico para lesão bacteriana de pele.",
                "indicacao": "Antibiótico",
            },
            {
                "nome_medicamento": "Amoxicilina (Agemox)",
                "dosagem_texto": "conforme peso/bula",
                "frequencia_texto": "a cada 12 horas",
                "duracao_texto": "por 10 dias",
                "observacoes": "Alternativa para infecção em geral. Sempre após alimentação.",
                "justificativa": "Antibiótico sistêmico alternativo.",
                "indicacao": "Antibiótico",
            },
        ],
        "exames": [],
        "retornos": [],
    },
    {
        "nome": "Otohematoma",
        "suspeita_principal": "otohematoma",
        "especie": None,
        "sinais_gatilho": "Aumento de volume flutuante no pavilhão auricular, chacoalhar de cabeça, prurido auricular.",
        "conduta_sugerida": (
            "Avaliar drenagem conforme o caso. Investigar e tratar a otite de base "
            "(ver protocolo de otite) — o trauma por chacoalhar a cabeça costuma ser a causa. "
            "Corticoide para reduzir edema/inflamação."
        ),
        "orientacoes_tutor": "Corticoide sempre após alimentação; não interromper o desmame por conta própria.",
        "alertas": (
            "Corticoide acima de 5 dias precisa de desmame. Em gato, preferir prednisolona "
            "(não prednisona). Não associar corticoide com AINE. Uso prolongado: associar omeprazol."
        ),
        "prioridade": 2,
        "medicamentos": [
            {
                "nome_medicamento": "Prednisona (cão)",
                "dosagem_texto": "1 mg/kg/dia",
                "frequencia_texto": "a cada 24 horas",
                "duracao_texto": "5 dias (até 14)",
                "observacoes": "Acima de 5 dias, desmame: 0,5 mg/kg a cada 48 h. Sempre após alimentação.",
                "justificativa": "Reduzir edema e inflamação do pavilhão.",
                "indicacao": "Corticoide (casa)",
            },
            {
                "nome_medicamento": "Prednisolona (gato)",
                "dosagem_texto": "2 mg/kg/dia",
                "frequencia_texto": "a cada 24 horas",
                "duracao_texto": "pelo menor tempo possível",
                "observacoes": "Gatos adquirem tolerância; usar por menos tempo.",
                "justificativa": "Corticoide de escolha em felinos.",
                "indicacao": "Corticoide (casa)",
            },
            {
                "nome_medicamento": "Omeprazol",
                "dosagem_texto": "conforme peso/bula",
                "frequencia_texto": "a cada 24 horas",
                "duracao_texto": "durante o corticoide prolongado",
                "observacoes": None,
                "justificativa": "Protetor gástrico quando corticoide prolongado.",
                "indicacao": "Protetor gástrico",
            },
        ],
        "exames": [],
        "retornos": [
            {
                "prazo_min_dias": 5,
                "prazo_max_dias": 7,
                "tipo_retorno": "retorno",
                "objetivo": "Reavaliar o edema e iniciar/ajustar o desmame do corticoide.",
            }
        ],
    },
    {
        "nome": "Otite externa",
        "suspeita_principal": "otite",
        "especie": None,
        "sinais_gatilho": "Secreção e odor no conduto auditivo, prurido auricular, chacoalhar de cabeça.",
        "conduta_sugerida": "Limpeza do conduto e tratamento tópico otológico.",
        "orientacoes_tutor": "Aplicar o otológico conforme receita; não usar cotonete no conduto.",
        "alertas": None,
        "prioridade": 2,
        "medicamentos": [
            {
                "nome_medicamento": "Otoguard",
                "dosagem_texto": "conforme bula",
                "frequencia_texto": "conforme bula",
                "duracao_texto": "conforme bula",
                "observacoes": None,
                "justificativa": "Otológico tópico.",
                "indicacao": "Uso tópico otológico",
            },
            {
                "nome_medicamento": "Posatex",
                "dosagem_texto": "conforme bula",
                "frequencia_texto": "conforme bula",
                "duracao_texto": "conforme bula",
                "observacoes": "Alternativa ao Otoguard.",
                "justificativa": "Otológico tópico alternativo.",
                "indicacao": "Uso tópico otológico",
            },
        ],
        "exames": [],
        "retornos": [],
    },
    {
        "nome": "Sarna / Ectoparasitas (carrapatos e pulgas)",
        "suspeita_principal": "sarna",
        "especie": None,
        "sinais_gatilho": "Prurido intenso, alopecia, crostas, presença de carrapatos ou pulgas.",
        "conduta_sugerida": "Isoxazolina (ou fipronil) conforme peso; reavaliar lesões de pele associadas.",
        "orientacoes_tutor": "Tratar o ambiente e os contactantes; repetir o antiparasitário conforme o produto.",
        "alertas": "Carrapatos: ficar atento a sinais de hemoparasitose (ver protocolo de erliquiose/babesiose).",
        "prioridade": 2,
        "medicamentos": [
            {
                "nome_medicamento": "Simparic (sarolaner)",
                "dosagem_texto": "comprimido conforme faixa de peso",
                "frequencia_texto": "dose única (mensal)",
                "duracao_texto": "conforme produto",
                "observacoes": "Indicado para sarna e carrapatos.",
                "justificativa": "Isoxazolina para sarna e ectoparasitas.",
                "indicacao": "Antiparasitário",
            },
            {
                "nome_medicamento": "Fipronil (Frontline)",
                "dosagem_texto": "pipeta conforme faixa de peso",
                "frequencia_texto": "dose única (mensal)",
                "duracao_texto": "conforme produto",
                "observacoes": "Alternativa tópica; outras opções: Bravecto, Nexgard.",
                "justificativa": "Ectoparasiticida tópico alternativo.",
                "indicacao": "Antiparasitário",
            },
        ],
        "exames": [],
        "retornos": [],
    },
    {
        "nome": "Erliquiose / Babesiose (hemoparasitose)",
        "suspeita_principal": "erliquiose",
        "especie": None,
        "sinais_gatilho": "Histórico de carrapatos, apatia, anemia, petéquias, febre.",
        "conduta_sugerida": (
            "Coleta de sangue: hemograma (tubo roxo/EDTA — encher primeiro) e "
            "bioquímico/pesquisa (tubo vermelho — babesiose, erliquia, leishmania). "
            "Iniciar doxiciclina conforme suspeita."
        ),
        "orientacoes_tutor": "Completar todo o período do antibiótico mesmo com melhora; controle de carrapatos contínuo.",
        "alertas": (
            "Hemorragia/anemia grave: considerar vitamina K, ferro, Transamin e eritropoetina "
            "conforme o caso. Leptospirose: doxiciclina + azitromicina."
        ),
        "prioridade": 2,
        "medicamentos": [
            {
                "nome_medicamento": "Doxiciclina",
                "dosagem_texto": "comprimido conforme peso (25/50/100/300 mg)",
                "frequencia_texto": "a cada 12 horas",
                "duracao_texto": "por 28 dias",
                "observacoes": "Erliquia, babesia; leptospirose: associar azitromicina.",
                "justificativa": "Antibiótico de eleição para hemoparasitose.",
                "indicacao": "Antibiótico",
            },
        ],
        "exames": [
            {
                "nome": "Hemograma",
                "justificativa": "Tubo roxo (EDTA) — encher primeiro na coleta.",
            },
            {
                "nome": "Bioquímico / pesquisa de hemoparasitas",
                "justificativa": "Tubo vermelho — babesiose, erliquia, leishmania.",
            },
        ],
        "retornos": [],
    },
    {
        "nome": "Obstrução urinária felina",
        "suspeita_principal": "obstrucao uretral",
        "especie": "gato",
        "sinais_gatilho": "Gato sem urinar, esforço miccional improdutivo, vocalização, bexiga repleta e dolorosa.",
        "conduta_sugerida": (
            "Sedação: metadona 0,5 mg/kg + xilazina 1 ml/20 kg. Expor o pênis com a mão em "
            "formato de pinça; passar sonda uretral nº 4 com gel de lidocaína. Fluidoterapia "
            "conforme hidratação (40–70 ml/kg/24 h)."
        ),
        "orientacoes_tutor": "Observar se o gato volta a urinar normalmente; retorno imediato se parar de urinar de novo.",
        "alertas": "Antagonista da xilazina: ioimbina. Obstrução recorrente: reavaliar conduta.",
        "prioridade": 1,
        "medicamentos": [
            {
                "nome_medicamento": "Metadona",
                "dosagem_texto": "0,5 mg/kg",
                "frequencia_texto": "sedação para o procedimento",
                "duracao_texto": "uso na clínica",
                "observacoes": None,
                "justificativa": "Sedação/analgesia para desobstrução.",
                "indicacao": "Sedação (clínica)",
            },
            {
                "nome_medicamento": "Xilazina",
                "dosagem_texto": "1 ml/20 kg",
                "frequencia_texto": "sedação para o procedimento",
                "duracao_texto": "uso na clínica",
                "observacoes": "Antagonista: ioimbina.",
                "justificativa": "Sedação associada para desobstrução.",
                "indicacao": "Sedação (clínica)",
            },
            {
                "nome_medicamento": "Gel de lidocaína",
                "dosagem_texto": "na sonda uretral nº 4",
                "frequencia_texto": "durante o procedimento",
                "duracao_texto": "uso na clínica",
                "observacoes": None,
                "justificativa": "Lubrificação/anestesia da sondagem.",
                "indicacao": "Procedimento",
            },
        ],
        "exames": [],
        "retornos": [],
    },
    {
        "nome": "Gastroenterite (vômito/diarreia)",
        "suspeita_principal": "gastroenterite",
        "especie": None,
        "sinais_gatilho": "Vômito, diarreia, desidratação, anorexia.",
        "conduta_sugerida": (
            "Fluidoterapia: 40 ml/kg/24 h sem vômito/diarreia; 50 ml/kg/24 h com um deles; "
            "70 ml/kg/24 h com ambos (microgotas 60 gotas/ml; macrogotas 20 gotas/ml). "
            "Em casa: eletrolítico pet sachê 250 ml. Filhote: considerar teste de parvovirose."
        ),
        "orientacoes_tutor": "Oferecer eletrolítico conforme receita; retorno se prostração ou sangue nas fezes/vômito.",
        "alertas": "Anorexia persistente: Cobavital (cão) / Mirtazapina (gato) / Glicopan.",
        "prioridade": 2,
        "medicamentos": [
            {
                "nome_medicamento": "Cerenia (maropitant)",
                "dosagem_texto": "conforme peso/bula",
                "frequencia_texto": "a cada 24 horas",
                "duracao_texto": "conforme prescrição",
                "observacoes": "Antiemético mais eficaz; alternativas: ondansetrona, metoclopramida.",
                "justificativa": "Controle do vômito.",
                "indicacao": "Antiemético",
            },
            {
                "nome_medicamento": "Organew",
                "dosagem_texto": "conforme peso/bula",
                "frequencia_texto": "conforme bula",
                "duracao_texto": "conforme prescrição",
                "observacoes": "Vitamina, prebiótico e estimulador de apetite.",
                "justificativa": "Suporte para diarreia.",
                "indicacao": "Suporte",
            },
            {
                "nome_medicamento": "Eletrolítico pet (sachê 250 ml)",
                "dosagem_texto": "conforme orientação",
                "frequencia_texto": "ao longo do dia",
                "duracao_texto": "enquanto durar o quadro",
                "observacoes": "Soroterapia de casa.",
                "justificativa": "Hidratação oral em casa.",
                "indicacao": "Hidratação (casa)",
            },
        ],
        "exames": [
            {
                "nome": "Teste de parvovirose",
                "justificativa": "Suabe anal no diluente; 4 gotas no teste; leitura em 5–10 minutos.",
            },
        ],
        "retornos": [],
    },
    {
        "nome": "Mastite / Pseudociese em cadelas",
        "suspeita_principal": "mastite / pseudociese",
        "especie": "cao",
        "sinais_gatilho": (
            "Cadela com aumento mamário, produção de leite, comportamento maternal, "
            "dor mamária, calor local, mamas endurecidas ou secreção."
        ),
        "conduta_sugerida": (
            "Correlacionar o quadro mamário com pseudociese e avaliar a intensidade da mastite. "
            "Quando houver lactação importante e mastite sem sinais sistêmicos graves, considerar "
            "suporte com antigalactogênico, antimicrobiano e anti-inflamatório, com reavaliação clínica."
        ),
        "orientacoes_tutor": (
            "Evitar manipular ou estimular as mamas, impedir lambedura e retornar antes do prazo "
            "se houver febre, prostração, secreção purulenta, necrose ou piora importante da dor."
        ),
        "alertas": (
            "Reavaliar rapidamente se houver abscesso, secreção sanguinolenta, sinais sistêmicos "
            "ou suspeita de mastite grave. Não associar AINE com corticoide."
        ),
        "prioridade": 3,
        "medicamentos": [
            {
                "nome_medicamento": "Sec Lac",
                "dosagem_texto": "Calcular pelo peso e pela apresentação escolhida",
                "frequencia_texto": "a cada 12 horas",
                "duracao_texto": "por 4 a 8 dias",
                "observacoes": (
                    "Metergolina por via oral; o plano clínico converte automaticamente para comprimidos "
                    "conforme peso e apresentação compatível (Sec Lac 5 ou Sec Lac 20)."
                ),
                "justificativa": "Controle da lactação e suporte em quadro compatível com pseudociese.",
                "indicacao": "Antigalactogênico",
            },
            {
                "nome_medicamento": "Cefalexina",
                "dosagem_texto": "20 a 30 mg/kg",
                "frequencia_texto": "a cada 12 horas",
                "duracao_texto": "por 7 a 10 dias",
                "observacoes": "Calcular automaticamente pela faixa de peso e manter preferencialmente após alimentação.",
                "justificativa": "Cobertura antimicrobiana inicial quando houver mastite sem sinais de sepse.",
                "indicacao": "Antibiótico",
            },
            {
                "nome_medicamento": "Meloxicam",
                "dosagem_texto": "0,1 mg/kg",
                "frequencia_texto": "a cada 24 horas",
                "duracao_texto": "por 5 dias",
                "observacoes": "Usar com cautela gastrointestinal e sempre revisar hidratação e perfusão da paciente.",
                "justificativa": "Controle de dor e inflamação mamária.",
                "indicacao": "Anti-inflamatório",
            },
        ],
        "exames": [],
        "retornos": [
            {
                "prazo_min_dias": 3,
                "prazo_max_dias": 5,
                "tipo_retorno": "reavaliacao",
                "objetivo": "Reavaliar redução da lactação, dor mamária, calor local e resposta ao tratamento.",
            }
        ],
    },
]


def _sync_protocol_items(protocol, model, relation_name, rows):
    items = getattr(protocol, relation_name)
    items[:] = []
    for pos, row in enumerate(rows, 1):
        items.append(model(prioridade=pos, **row))


def _normalize_rows(rows, keys):
    normalized = []
    for row in rows:
        normalized.append({key: row.get(key) for key in keys})
    return normalized


def seed(session, *, apply: bool = False, only_names: list[str] | None = None) -> dict:
    """Cria ou atualiza protocolos globais identificados por nome."""
    from models import (
        ProtocoloClinico,
        ProtocoloClinicoExame,
        ProtocoloClinicoMedicamento,
        ProtocoloClinicoRetorno,
    )

    created, updated, skipped = [], [], []
    normalized_filter = {name.strip().lower() for name in (only_names or []) if str(name).strip()}
    for data in PROTOCOLS:
        if normalized_filter and data["nome"].strip().lower() not in normalized_filter:
            continue
        exists = (
            session.query(ProtocoloClinico)
            .filter(
                ProtocoloClinico.nome == data["nome"],
                ProtocoloClinico.clinica_id.is_(None),
            )
            .first()
        )
        if exists:
            changed = False
            scalar_fields = (
                "nome",
                "suspeita_principal",
                "especie",
                "sinais_gatilho",
                "conduta_sugerida",
                "orientacoes_tutor",
                "alertas",
                "prioridade",
            )
            for field in scalar_fields:
                new_value = data[field]
                if getattr(exists, field) != new_value:
                    setattr(exists, field, new_value)
                    changed = True

            current_meds = [
                {
                    "nome_medicamento": item.nome_medicamento,
                    "dosagem_texto": item.dosagem_texto,
                    "frequencia_texto": item.frequencia_texto,
                    "duracao_texto": item.duracao_texto,
                    "observacoes": item.observacoes,
                    "justificativa": item.justificativa,
                    "indicacao": item.indicacao,
                }
                for item in exists.medicamentos_sugeridos
            ]
            current_exams = [
                {
                    "nome": item.nome,
                    "justificativa": item.justificativa,
                }
                for item in exists.exames_sugeridos
            ]
            current_returns = [
                {
                    "prazo_min_dias": item.prazo_min_dias,
                    "prazo_max_dias": item.prazo_max_dias,
                    "tipo_retorno": item.tipo_retorno,
                    "objetivo": item.objetivo,
                    "gatilhos_antecipacao": item.gatilhos_antecipacao,
                }
                for item in exists.retornos_sugeridos
            ]

            expected_meds = _normalize_rows(
                data["medicamentos"],
                (
                    "nome_medicamento",
                    "dosagem_texto",
                    "frequencia_texto",
                    "duracao_texto",
                    "observacoes",
                    "justificativa",
                    "indicacao",
                ),
            )
            expected_exams = _normalize_rows(data["exames"], ("nome", "justificativa"))
            expected_returns = _normalize_rows(
                data["retornos"],
                ("prazo_min_dias", "prazo_max_dias", "tipo_retorno", "objetivo", "gatilhos_antecipacao"),
            )

            if current_meds != expected_meds:
                _sync_protocol_items(
                    exists,
                    ProtocoloClinicoMedicamento,
                    "medicamentos_sugeridos",
                    data["medicamentos"],
                )
                changed = True
            if current_exams != expected_exams:
                _sync_protocol_items(
                    exists,
                    ProtocoloClinicoExame,
                    "exames_sugeridos",
                    data["exames"],
                )
                changed = True
            if current_returns != expected_returns:
                _sync_protocol_items(
                    exists,
                    ProtocoloClinicoRetorno,
                    "retornos_sugeridos",
                    data["retornos"],
                )
                changed = True

            if changed:
                exists.versao = (exists.versao or 1) + 1
                exists.ativo = True
                updated.append(data["nome"])
            else:
                skipped.append(data["nome"])
            continue
        protocol = ProtocoloClinico(
            nome=data["nome"],
            suspeita_principal=data["suspeita_principal"],
            especie=data["especie"],
            sinais_gatilho=data["sinais_gatilho"],
            conduta_sugerida=data["conduta_sugerida"],
            orientacoes_tutor=data["orientacoes_tutor"],
            alertas=data["alertas"],
            prioridade=data["prioridade"],
            versao=1,
            ativo=True,
            clinica_id=None,
        )
        for pos, med in enumerate(data["medicamentos"], 1):
            protocol.medicamentos_sugeridos.append(
                ProtocoloClinicoMedicamento(prioridade=pos, **med)
            )
        for pos, exame in enumerate(data["exames"], 1):
            protocol.exames_sugeridos.append(
                ProtocoloClinicoExame(prioridade=pos, **exame)
            )
        for pos, retorno in enumerate(data["retornos"], 1):
            protocol.retornos_sugeridos.append(
                ProtocoloClinicoRetorno(prioridade=pos, **retorno)
            )
        session.add(protocol)
        created.append(data["nome"])

    if apply:
        session.commit()
    else:
        session.rollback()
    return {"created": created, "updated": updated, "skipped": skipped, "applied": apply}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="grava de verdade (padrão: simulação)")
    parser.add_argument(
        "--only-name",
        action="append",
        dest="only_names",
        help="limita a execucao ao nome exato do protocolo informado; pode repetir a flag",
    )
    args = parser.parse_args()

    from app import app
    from extensions import db

    with app.app_context():
        result = seed(db.session, apply=args.apply, only_names=args.only_names)
    label = "CRIADOS" if result["applied"] else "SERIAM CRIADOS (simulação)"
    print(f"{label}: {len(result['created'])}")
    for nome in result["created"]:
        print(f"  + {nome}")
    if result["skipped"]:
        print(f"JÁ EXISTIAM: {', '.join(result['skipped'])}")


if __name__ == "__main__":
    main()
