import csv
import io
import json
from datetime import datetime
from types import SimpleNamespace

from services.sfa_service import (
    gerar_csv_exportacao_analitica,
    listar_historico_instrumentos,
    montar_visao_resposta_formulario,
)


def _response(payload):
    return SimpleNamespace(
        id=1,
        id_estudo="SFA-VERSION",
        nome="Pessoa Teste",
        timestamp=datetime(2026, 8, 24, 9, 30),
        dados_json=json.dumps(payload, ensure_ascii=False),
    )


def _patient(response):
    return SimpleNamespace(
        id_estudo="SFA-VERSION",
        ficha_sinan="12345",
        nome="Pessoa Teste",
        resposta_t0=response,
        respostas_t10=[],
        respostas_t30=[],
    )


def test_resposta_sem_versao_continua_legivel_pelo_schema_arquivado():
    view = montar_visao_resposta_formulario(
        "t0",
        _response({"nome": "Pessoa Teste", "vacinas_12_meses": ["Nenhuma"]}),
    )

    keys = {
        field["key"]
        for section in view["sections"]
        for field in section["fields"]
    }
    assert view["instrument_version"] == "legacy-2026-08-24"
    assert view["title"] == "T0 Atualizacao Forms Codex - SFA Orlandia"
    assert {"nome", "vacinas_12_meses"} <= keys


def test_resposta_collective_v2_usa_instrumento_essencial():
    view = montar_visao_resposta_formulario(
        "t0",
        _response(
            {
                "_instrument_version": "collective-v2",
                "respondent_role": "A propria pessoa",
            }
        ),
    )

    keys = {
        field["key"]
        for section in view["sections"]
        for field in section["fields"]
    }
    assert view["instrument_version"] == "collective-v2"
    assert view["title"] == "T0 - Exposicoes coletivas e prevencao"
    assert "respondent_role" in keys
    assert "vacinas_12_meses" not in keys


def test_csv_analitico_exporta_uniao_do_atual_e_do_historico():
    response = _response(
        {
            "_instrument_version": "collective-v2",
            "respondent_role": "A propria pessoa",
        }
    )
    rows = list(csv.DictReader(io.StringIO(gerar_csv_exportacao_analitica([_patient(response)]))))

    assert len(rows) == 1
    assert rows[0]["t0__instrument_version"] == "collective-v2"
    assert rows[0]["t0__respondent_role"] == "A propria pessoa"
    assert "t0__cpf" in rows[0]


def test_manifesto_historico_preserva_contagens_exatas():
    versions = listar_historico_instrumentos()
    archived = next(version for version in versions if version["id"] == "legacy-2026-08-24")

    assert archived["stages"]["t0"]["field_count"] == 36
    assert archived["stages"]["t10"]["field_count"] == 25
    assert archived["stages"]["t30"]["field_count"] == 24


def test_historico_e_interno_get_only_e_fica_abaixo_do_cadastro_manual(
    app,
    client,
    monkeypatch,
):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "1")

    response = client.get("/sfa/instrumentos/historico")

    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Arquivo somente para consulta" in html
    assert "T0 Atualizacao Forms Codex - SFA Orlandia" in html
    assert "Historico de instrumentos" in html
    assert html.index("#cadastro-manual") < html.index("/sfa/instrumentos/historico")
    assert client.post("/sfa/instrumentos/historico").status_code == 405


def test_historico_recusa_versao_ou_etapa_fora_do_manifesto(
    app,
    client,
    monkeypatch,
):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "1")

    assert (
        client.get("/sfa/instrumentos/historico?versao=../../config&etapa=t0").status_code
        == 404
    )
    assert (
        client.get(
            "/sfa/instrumentos/historico?versao=legacy-2026-08-24&etapa=t99"
        ).status_code
        == 404
    )
