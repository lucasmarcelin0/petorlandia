import csv
import io
import json
from datetime import datetime
from types import SimpleNamespace

from services.sfa_service import (
    carregar_t10_form_schema,
    gerar_csv_assinaturas_tcle,
    gerar_csv_exportacao_analitica,
    gerar_csv_exportacao_cadastro,
    montar_analise_respostas,
    montar_registro_assinatura_tcle,
    montar_visao_resposta_formulario,
)


def _fake_response(payload, when=None):
    return SimpleNamespace(
        timestamp=when or datetime(2026, 3, 23, 10, 30, 0),
        dados_json=json.dumps(payload, ensure_ascii=False),
    )


def _fake_patient():
    return SimpleNamespace(
        id_estudo="SFA-123",
        ficha_sinan="3032976",
        nome="Lucilene Alves da Silva",
        data_nascimento="01/11/1976",
        telefone="5516993271961",
        bairro="Jardim Teixeira",
        endereco="Avenida 4 2067",
        grupo="B",
        status_t0="T0_Completo",
        status_t10="T10_Completo",
        status_t30="Aguardando",
        status_geral="Em_Andamento",
        data_t0="18/03/2026",
        data_t10="28/03/2026",
        data_t30="17/04/2026",
        fase_atual="Entre T0 e T10",
        proxima_fase="T10",
        proxima_acao="Aguardar T10",
        prioridade_operacional="Baixa",
        dias_para_acao=10,
        data_proxima_acao="28/03/2026",
        status_whatsapp="NAO_ENVIADO",
        retorno_contato="PENDENTE",
        timestamp_cadastro=datetime(2026, 3, 18, 9, 0, 0),
        updated_at=datetime(2026, 3, 23, 11, 0, 0),
        resposta_t0=_fake_response(
            {
                "_instrument_version": "collective-v2",
                "_submitted_stage": "t0",
                "respondent_role": "A propria pessoa",
                "aceite_tcle": [
                    "Confirmo que li o TCLE e aceito participar voluntariamente do estudo."
                ],
                "tcle_assinado_por": "Lucilene Alves da Silva",
                "consentimento_registrado_em": "2026-03-18T11:43:54Z",
                "data_inicio_sintomas": "11/03/2026",
                "outras_pessoas_com_sintomas": "Nao",
                "exposicao_animal": ["Nenhum contato animal relevante"],
                "exposicao_ambiental": ["Nenhuma exposicao ambiental"],
                "exposicao_alimentar": ["Nenhuma dessas"],
                "diagnostico_medico": "Nao",
                "dias_incap": "2",
                "houve_gasto": "Nao",
            }
        ),
        respostas_t10=[
            _fake_response(
                {
                    "_instrument_version": "collective-v2",
                    "_submitted_stage": "t10",
                    "classificacao_melhora": "Melhorando",
                    "sinais_alerta_atuais": ["Nenhum destes sinais agora"],
                    "novos_casos_semelhantes": "Nao",
                    "dias_incap_novos": "3",
                    "houve_novos_gastos": "Sim",
                    "custo_outros": "18.50",
                }
            )
        ],
        respostas_t30=[],
    )


def test_montar_visao_resposta_formulario_agrupar_campos_e_listas():
    response = _fake_response(
        {
            "_instrument_version": "collective-v2",
            "classificacao_melhora": "Melhorando",
            "sinais_alerta_atuais": [
                "Falta de ar importante",
                "Sangramento importante",
            ],
        }
    )

    view = montar_visao_resposta_formulario(
        "t10", response, schema=carregar_t10_form_schema()
    )

    assert view["stage"] == "t10"
    assert view["instrument_version"] == "collective-v2"
    assert view["submitted_at"] == "23/03/2026 10:30"
    alertas_field = next(
        field
        for section in view["sections"]
        for field in section["fields"]
        if field["key"] == "sinais_alerta_atuais"
    )
    assert alertas_field["value"] == "Falta de ar importante | Sangramento importante"
    assert alertas_field["has_value"] is True


def test_gerar_csv_exportacao_cadastro_inclui_colunas_operacionais():
    csv_text = gerar_csv_exportacao_cadastro([_fake_patient()])
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert rows[0]["id_estudo"] == "SFA-123"
    assert rows[0]["status_geral"] == "Em_Andamento"
    assert rows[0]["proxima_acao"] == "Aguardar T10"


def test_gerar_csv_exportacao_analitica_achata_instrumento_atual_sem_repetir_importados():
    csv_text = gerar_csv_exportacao_analitica([_fake_patient()])
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert rows[0]["id_estudo"] == "SFA-123"
    assert rows[0]["t0__instrument_version"] == "collective-v2"
    assert rows[0]["t10__instrument_version"] == "collective-v2"
    assert rows[0]["t0__respondent_role"] == "A propria pessoa"
    assert rows[0].get("t0__cpf", "") == ""
    assert rows[0]["t10__classificacao_melhora"] == "Melhorando"
    assert rows[0]["t10__custo_outros"] == "18.50"


def _chart_value(chart, label):
    values = dict(zip(chart["labels"], chart["data"]))
    return values.get(label, 0)


def test_montar_analise_respostas_agrega_exposicoes_coletivas_e_dias_da_doenca():
    paciente_exposto = SimpleNamespace(
        id_estudo="SFA-201",
        nome="Paciente Exposto",
        resposta_t0=_fake_response(
            {
                "_instrument_version": "collective-v2",
                "data_inicio_sintomas": "2026-03-01",
                "outras_pessoas_com_sintomas": "Sim",
                "exposicao_animal": ["Caes", "Carrapato"],
                "exposicao_alimentar": ["Leite cru/queijo nao pasteurizado"],
                "exposicao_ambiental": [
                    "Agua suja/lama/enchente",
                    "Area rural/chacara",
                ],
            },
            when=datetime(2026, 3, 3, 9, 0, 0),
        ),
        respostas_t10=[
            _fake_response({}, when=datetime(2026, 3, 12, 9, 0, 0))
        ],
        respostas_t30=[
            _fake_response({}, when=datetime(2026, 3, 31, 9, 0, 0))
        ],
    )
    paciente_sem_risco = SimpleNamespace(
        id_estudo="SFA-202",
        nome="Paciente Sem Risco",
        resposta_t0=_fake_response(
            {
                "_instrument_version": "collective-v2",
                "data_inicio_sintomas": "01/03/2026",
                "outras_pessoas_com_sintomas": "Nao",
                "exposicao_animal": ["Nenhum contato animal relevante"],
                "exposicao_alimentar": ["Nenhuma dessas"],
                "exposicao_ambiental": ["Nenhuma exposicao ambiental"],
            },
            when=datetime(2026, 3, 20, 9, 0, 0),
        ),
        respostas_t10=[],
        respostas_t30=[],
    )

    analise = montar_analise_respostas([paciente_exposto, paciente_sem_risco])

    kpis = {item["label"]: item["value"] for item in analise["kpis"]}
    assert kpis["Participantes"] == 2
    assert kpis["Com inicio dos sintomas"] == 2
    assert kpis["Risco animal"] == 1
    assert kpis["Risco ambiental"] == 1
    assert kpis["Risco alimentar"] == 1
    assert _chart_value(analise["charts"]["animal"], "Caes") == 1
    assert _chart_value(analise["charts"]["animal"], "Carrapato") == 1
    assert _chart_value(
        analise["charts"]["food"], "Leite cru/queijo nao pasteurizado"
    ) == 1
    assert _chart_value(
        analise["charts"]["environmental"], "Agua suja/lama/enchente"
    ) == 1
    assert _chart_value(
        analise["charts"]["environmental"], "Area rural/chacara"
    ) == 1

    t0_dataset = next(
        dataset
        for dataset in analise["charts"]["timing"]["datasets"]
        if dataset["label"] == "T0"
    )
    labels = analise["charts"]["timing"]["labels"]
    assert t0_dataset["data"][labels.index("D0-D2")] == 1
    assert t0_dataset["data"][labels.index("D15-D30")] == 1
    assert analise["timeline"][0]["inicio_sintomas"] == "01/03/2026"
    assert analise["timeline"][0]["t0_dia_doenca"] == "D+2"


def test_montar_registro_assinatura_tcle_extrai_nome_e_metadados():
    resposta = _fake_response(
        {
            "nome": "Lucilene Alves da Silva",
            "ficha_sinan": "3032976",
            "aceite_tcle": [
                "Confirmo que li o TCLE e aceito participar voluntariamente do estudo."
            ],
            "tcle_assinado_por": "Lucilene Alves da Silva",
            "consentimento_registrado_em": "2026-03-18T11:43:54Z",
            "consentimento_ip": "203.0.113.9",
            "consentimento_user_agent": "pytest-agent",
        }
    )
    resposta.id_estudo = "SFA-123"

    registro = montar_registro_assinatura_tcle(resposta)

    assert registro["id_estudo"] == "SFA-123"
    assert registro["ficha_sinan"] == "3032976"
    assert registro["nome_assinatura"] == "Lucilene Alves da Silva"
    assert registro["assinado_em"] == "18/03/2026 11:43"
    assert registro["ip"] == "203.0.113.9"


def test_gerar_csv_assinaturas_tcle_exporta_registros():
    csv_text = gerar_csv_assinaturas_tcle(
        [
            {
                "assinado_em": "18/03/2026 11:43",
                "id_estudo": "SFA-123",
                "ficha_sinan": "3032976",
                "participante": "Lucilene Alves da Silva",
                "nome_assinatura": "Lucilene Alves da Silva",
                "data_nascimento": "01/11/1976",
                "ip": "203.0.113.9",
                "user_agent": "pytest-agent",
            }
        ]
    )
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert rows[0]["id_estudo"] == "SFA-123"
    assert rows[0]["nome_assinatura"] == "Lucilene Alves da Silva"
    assert rows[0]["ip"] == "203.0.113.9"


def test_gerar_csv_sfa_escapes_formula_cells():
    paciente_formula = _fake_patient()
    paciente_formula.nome = "=CMD()"
    paciente_formula.bairro = "+EvilBairro"
    paciente_formula.endereco = "-EvilAddr"
    paciente_formula.proxima_acao = "@EvilAction"

    cadastro_csv = gerar_csv_exportacao_cadastro([paciente_formula])
    rows_cad = list(csv.DictReader(io.StringIO(cadastro_csv)))
    assert rows_cad[0]["nome"].startswith("'=")
    assert rows_cad[0]["bairro"].startswith("'+")
    assert rows_cad[0]["endereco"].startswith("'-")
    assert rows_cad[0]["proxima_acao"].startswith("'@")

    analitica_csv = gerar_csv_exportacao_analitica([paciente_formula])
    rows_ana = list(csv.DictReader(io.StringIO(analitica_csv)))
    assert rows_ana[0]["nome"].startswith("'=")
    assert rows_ana[0]["bairro"].startswith("'+")

    tcle_csv = gerar_csv_assinaturas_tcle(
        [
            {
                "assinado_em": "18/03/2026 11:43",
                "id_estudo": "=SFA-123",
                "ficha_sinan": "3032976",
                "participante": "+Attacker Name",
                "nome_assinatura": "@Attacker Signature",
                "data_nascimento": "01/11/1976",
                "ip": "-127.0.0.1",
                "user_agent": "pytest-agent",
            }
        ]
    )
    rows_tcle = list(csv.DictReader(io.StringIO(tcle_csv)))
    assert rows_tcle[0]["id_estudo"].startswith("'=")
    assert rows_tcle[0]["participante"].startswith("'+")
    assert rows_tcle[0]["nome_assinatura"].startswith("'@")
    assert rows_tcle[0]["ip"].startswith("'-")
