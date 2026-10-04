"""Cliente do Google Sheets: mesmas requisições, sem o texto de ajuda que estourava a memória."""

import json
import tracemalloc
from urllib.parse import parse_qs, unquote, urlparse

import pytest

pytest.importorskip("googleapiclient")
from google.auth.credentials import AnonymousCredentials  # noqa: E402

from services.google_sheets_client import build_sheets  # noqa: E402


@pytest.fixture
def service():
    return build_sheets(AnonymousCredentials())


def test_requisicoes_continuam_identicas(service):
    leitura = service.spreadsheets().values().get(spreadsheetId="abc", range="'Dia 01/10'!A:T")
    assert leitura.method == "GET"
    assert unquote(urlparse(leitura.uri).path) == "/v4/spreadsheets/abc/values/'Dia 01/10'!A:T"

    grade = service.spreadsheets().get(
        spreadsheetId="abc",
        ranges=["'Encaixes'!A:T"],
        includeGridData=True,
        fields="sheets(data(rowData(values(formattedValue))))",
    )
    query = parse_qs(urlparse(grade.uri).query)
    assert grade.method == "GET"
    assert query["includeGridData"] == ["true"]
    assert query["fields"] == ["sheets(data(rowData(values(formattedValue))))"]
    assert query["ranges"] == ["'Encaixes'!A:T"]

    escrita = service.spreadsheets().batchUpdate(spreadsheetId="abc", body={"requests": [{"x": 1}]})
    assert escrita.method == "POST"
    assert urlparse(escrita.uri).path == "/v4/spreadsheets/abc:batchUpdate"
    assert json.loads(escrita.body) == {"requests": [{"x": 1}]}

    with pytest.raises(TypeError):                   # a validação de parâmetros continua valendo
        service.spreadsheets().values().get(spreadsheetId="abc")


def test_sem_texto_de_ajuda_gigante(service):
    planilhas = service.spreadsheets()
    assert len(planilhas.batchUpdate.__doc__) < 20_000          # era ~4,8 MB
    assert "spreadsheetId" in planilhas.batchUpdate.__doc__    # parâmetros seguem documentados


def test_cada_uso_do_recurso_custa_pouca_memoria(service):
    service.spreadsheets().values()                  # aquece caches da biblioteca
    tracemalloc.start()
    try:
        for _ in range(3):
            service.spreadsheets().values().get(spreadsheetId="abc", range="A:T")
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert pico < 25 * 1024 * 1024, pico              # antes: ~68 MB por chamada


@pytest.mark.parametrize("modulo, funcao, escopo", [
    ("services.vacina_pmo_service", "_get_sheets_service_rw", "https://www.googleapis.com/auth/spreadsheets"),
    ("services.sfa_service", "_get_sheets_service", "https://www.googleapis.com/auth/spreadsheets.readonly"),
])
def test_servicos_do_app_usam_o_cliente_leve(monkeypatch, modulo, funcao, escopo):
    import importlib

    from google.oauth2 import service_account

    from services import google_sheets_client

    mod = importlib.import_module(modulo)
    vistos = {}
    monkeypatch.setattr(mod, "_load_google_credentials_info", lambda: {"fake": True})
    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_info",
        classmethod(lambda cls, info, scopes: vistos.setdefault("scopes", scopes) and "creds"),
    )
    monkeypatch.setattr(google_sheets_client, "build_sheets", lambda creds: ("leve", creds))
    assert getattr(mod, funcao)() == ("leve", "creds")
    assert vistos["scopes"] == [escopo]


def test_leitura_com_cores_pede_so_os_campos_usados():
    from scripts.audit_pmo_sheet_status_colors import _fetch_sheet_rows

    pedidos = []

    class Pedido:
        def execute(self):
            return {"sheets": [{"data": [{"rowData": [{"values": [{"formattedValue": "Ana", "note": "n"}]}]}]}]}

    class Planilhas:
        def get(self, **kwargs):
            pedidos.append(kwargs)
            return Pedido()

    class Servico:
        def spreadsheets(self):
            return Planilhas()

    linhas = _fetch_sheet_rows(Servico(), "abc", "Encaixes", "")
    assert linhas == [[{"formattedValue": "Ana", "note": "n"}]]
    campos = pedidos[0]["fields"]
    for usado in ("formattedValue", "note", "effectiveFormat(backgroundColor)", "userEnteredFormat(backgroundColor)"):
        assert usado in campos
    assert pedidos[0]["includeGridData"] is True
