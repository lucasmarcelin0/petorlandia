import csv
import io
import json
from datetime import datetime
from types import SimpleNamespace

from services.sfa_service import (
    carregar_t10_form_schema,
    gerar_csv_exportacao_analitica,
    gerar_csv_exportacao_cadastro,
    gerar_csv_assinaturas_tcle,
    montar_visao_resposta_formulario,
    montar_registro_assinatura_tcle,
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
                "cpf": "12345678900",
                "ficha_sinan": "3032976",
                "nome": "Lucilene Alves da Silva",
                "aceite_tcle": ["Confirmo que li o TCLE e aceito participar voluntariamente do estudo."],
                "tcle_assinado_por": "Lucilene Alves da Silva",
                "consentimento_registrado_em": "2026-03-18T11:43:54Z",
                "tipo_residencia": "Casa urbana",
                "data_inicio_sintomas": "11/03/2026",
                "dias_incap": "2",
            }
        ),
        respostas_t10=[
            _fake_response(
                {
                    "cpf": "12345678900",
                    "nome": "Lucilene Alves da Silva",
                    "classificacao_melhora": "Melhorando - Sintomas leves, em recuperacao",
                    "sintomas_persistentes": ["Cansaco extremo/fadiga", "Dor de cabeca"],
                    "dias_incap_novos": "3",
                }
            )
        ],
        respostas_t30=[],
    )


def test_montar_visao_resposta_formulario_agrupar_campos_e_listas():
    response = _fake_response(
        {
            "cpf": "12345678900",
            "classificacao_melhora": "Melhorando - Sintomas leves, em recuperacao",
            "sintomas_persistentes": ["Cansaco extremo/fadiga", "Dor de cabeca"],
        }
    )

    view = montar_visao_resposta_formulario("t10", response, schema=carregar_t10_form_schema())

    assert view["stage"] == "t10"
    assert view["submitted_at"] == "23/03/2026 10:30"
    sintomas_field = next(
        field
        for section in view["sections"]
        for field in section["fields"]
        if field["key"] == "sintomas_persistentes"
    )
    assert sintomas_field["value"] == "Cansaco extremo/fadiga | Dor de cabeca"
    assert sintomas_field["has_value"] is True


def test_gerar_csv_exportacao_cadastro_inclui_colunas_operacionais():
    csv_text = gerar_csv_exportacao_cadastro([_fake_patient()])
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert rows[0]["id_estudo"] == "SFA-123"
    assert rows[0]["status_geral"] == "Em_Andamento"
    assert rows[0]["proxima_acao"] == "Aguardar T10"


def test_gerar_csv_exportacao_analitica_achata_respostas():
    csv_text = gerar_csv_exportacao_analitica([_fake_patient()])
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert rows[0]["id_estudo"] == "SFA-123"
    assert rows[0]["t0__cpf"] == "12345678900"
    assert rows[0]["t10__classificacao_melhora"] == "Melhorando - Sintomas leves, em recuperacao"
    assert rows[0]["t10__sintomas_persistentes"] == "Cansaco extremo/fadiga | Dor de cabeca"


def test_montar_registro_assinatura_tcle_extrai_nome_e_metadados():
    resposta = _fake_response(
        {
            "nome": "Lucilene Alves da Silva",
            "ficha_sinan": "3032976",
            "aceite_tcle": ["Confirmo que li o TCLE e aceito participar voluntariamente do estudo."],
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
