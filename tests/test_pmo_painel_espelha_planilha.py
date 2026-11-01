"""O painel /vacina-pmo precisa espelhar a aba da planilha.

Em 29/09/2026 a Maria Clara apareceu duas vezes no painel. O sync casava cada
visita só pelo número da linha: quando uma linha mudava de lugar, a visita da
linha antiga recebia os dados de outra pessoa (herdando os status de vacina
dela) e o registro de quem mudou sobrava no banco — estacionado com
``source_row`` negativo, mas ainda listado no painel. Estes testes garantem
que o registro acompanha a pessoa e que o painel mostra uma linha por linha
da aba.
"""

from __future__ import annotations

import pytest

from extensions import db
from models import PmoVaccinationVisit, User
from services import vacina_pmo_service as servico
from services.vacina_pmo_service import (
    PmoSyncResult,
    get_saved_vacina_pmo_rows,
    persist_vacina_pmo_rows,
)

PLANILHA = "plan-espelho"
ABA_GID = "2909"
ABA_TITULO = "29/09/2026"


@pytest.fixture(autouse=True)
def sem_geocodificar(monkeypatch):
    monkeypatch.setattr(servico, "_pmo_geocode_address", lambda address: None)


def _linha(source_row, tutor, telefone, endereco, animal, especie="cao"):
    return {
        "sourceRow": source_row,
        "tutor": tutor,
        "address": endereco,
        "phone1": telefone,
        "phone2": "",
        "dogs": 1 if especie == "cao" else 0,
        "cats": 1 if especie == "gato" else 0,
        "animals": [{"name": animal, "species": especie}],
        "note": "",
        "date": "2026-09-29",
        "shift": "Manha",
        "password": "PMOTESTE",
    }


ANA = ("Ana Souza", "5516991110001", "Rua A, 10, Centro", "Rex")
MARIA = ("Maria Clara", "5516991110002", "Rua B, 20, Centro", "Mel")
BRUNO = ("Bruno Lima", "5516991110003", "Rua C, 30, Centro", "Thor")
CARLA = ("Carla Dias", "5516991110004", "Rua D, 40, Centro", "Nina")


def _gravar(linhas, **kwargs):
    kwargs.setdefault("spreadsheet_id", PLANILHA)
    kwargs.setdefault("sheet_gid", ABA_GID)
    kwargs.setdefault("sheet_title", ABA_TITULO)
    return persist_vacina_pmo_rows(linhas, **kwargs)


def _visita_de(tutor, **filtro):
    filtro.setdefault("sheet_gid", ABA_GID)
    return PmoVaccinationVisit.query.filter_by(tutor_name=tutor, **filtro).all()


def _vacinar(visita):
    for animal in visita.animals:
        animal.status = "vacinado"
    db.session.commit()


def _painel():
    return get_saved_vacina_pmo_rows(sheet_gid=ABA_GID)["rows"]


def test_tutor_empurrado_por_linha_inserida_leva_a_vacina_junto(app):
    _gravar([_linha(3, *ANA), _linha(4, *MARIA), _linha(5, *BRUNO)])
    maria = _visita_de("Maria Clara")[0]
    _vacinar(maria)
    maria_id, maria_token = maria.id, maria.public_token

    # Alguém inseriu uma casa no topo: todo mundo desceu uma linha.
    _gravar(
        [_linha(3, *CARLA), _linha(4, *ANA), _linha(5, *MARIA), _linha(6, *BRUNO)],
        prune_orphans=True,
    )

    linhas = {row["tutor"]: row for row in _painel()}
    assert [row["tutor"] for row in _painel()] == [
        "Carla Dias", "Ana Souza", "Maria Clara", "Bruno Lima",
    ]
    assert linhas["Maria Clara"]["visitId"] == maria_id
    assert linhas["Maria Clara"]["sourceRow"] == 5
    assert linhas["Maria Clara"]["animals"][0]["status"] == "vacinado"
    # Ninguém herda a vacina que ficou na linha 4.
    assert linhas["Ana Souza"]["animals"][0]["status"] == "pendente"
    assert linhas["Carla Dias"]["animals"][0]["status"] == "pendente"
    assert db.session.get(PmoVaccinationVisit, maria_id).public_token == maria_token


def test_tutor_que_mudou_de_linha_nao_aparece_duas_vezes(app):
    """O caso da Maria Clara: vacinada, a linha dela foi para outro bloco."""
    _gravar([_linha(3, *ANA), _linha(4, *MARIA), _linha(12, *BRUNO)])
    maria = _visita_de("Maria Clara")[0]
    _vacinar(maria)

    # A linha 4 ficou vazia e a Maria foi parar na 13 (bloco da tarde).
    _gravar(
        [_linha(3, *ANA), _linha(12, *BRUNO), _linha(13, *MARIA)],
        prune_orphans=True,
    )

    tutores = [row["tutor"] for row in _painel()]
    assert tutores.count("Maria Clara") == 1
    assert len(_visita_de("Maria Clara")) == 1, "nenhuma cópia estacionada sobra"
    linha = next(row for row in _painel() if row["tutor"] == "Maria Clara")
    assert linha["sourceRow"] == 13
    assert linha["animals"][0]["status"] == "vacinado"


def test_painel_nao_lista_visita_estacionada(app):
    """Duplicata já gravada pelo código antigo: some do painel, fica no banco."""
    _gravar([_linha(3, *ANA), _linha(7, *MARIA)])
    estacionada = PmoVaccinationVisit(
        spreadsheet_id=PLANILHA, sheet_gid=ABA_GID, sheet_title=ABA_TITULO,
        source_row=9, tutor_name="Maria Clara", address=MARIA[2],
        phone1=MARIA[1], dogs=1, cats=0, password="PMOTESTE",
    )
    db.session.add(estacionada)
    db.session.flush()
    estacionada.source_row = -estacionada.id
    db.session.commit()

    tutores = [row["tutor"] for row in _painel()]

    assert tutores == ["Ana Souza", "Maria Clara"]
    assert db.session.get(PmoVaccinationVisit, estacionada.id) is not None


def test_familias_com_o_mesmo_telefone_trocando_de_linha(app):
    telefone = "5516988014004"
    maria = ("Maria Silva", telefone, "Rua A, 1, Centro", "Rex")
    joao = ("Joao Silva", telefone, "Rua A, 3, Centro", "Mel")
    _gravar([_linha(4, *maria), _linha(5, *joao)])
    _vacinar(_visita_de("Maria Silva")[0])

    _gravar([_linha(4, *joao), _linha(5, *maria)], prune_orphans=True)

    linhas = {row["tutor"]: row for row in _painel()}
    assert linhas["Maria Silva"]["sourceRow"] == 5
    assert linhas["Maria Silva"]["animals"][0]["status"] == "vacinado"
    assert linhas["Joao Silva"]["sourceRow"] == 4
    assert linhas["Joao Silva"]["animals"][0]["status"] == "pendente"


def test_outra_pessoa_na_linha_nao_herda_a_vacina(app):
    _gravar([_linha(4, *MARIA)])
    maria = _visita_de("Maria Clara")[0]
    _vacinar(maria)
    maria_id = maria.id

    _gravar([_linha(4, *CARLA)])

    linhas = _painel()
    assert [row["tutor"] for row in linhas] == ["Carla Dias"]
    assert linhas[0]["animals"][0]["status"] == "pendente"
    assert linhas[0]["visitId"] != maria_id
    guardada = db.session.get(PmoVaccinationVisit, maria_id)
    assert guardada.source_row < 0, "sai da lista do dia, mas o registro fica"
    assert guardada.animals[0].status == "vacinado"


def test_outra_pessoa_nao_reaproveita_visita_sem_trabalho_de_campo(app):
    """O token e os vínculos também pertencem à pessoa original."""
    _gravar([_linha(4, *MARIA)])
    visita_id = _visita_de("Maria Clara")[0].id

    _gravar([_linha(4, *CARLA)])

    assert _visita_de("Carla Dias")[0].id != visita_id
    assert db.session.get(PmoVaccinationVisit, visita_id).source_row < 0


def test_nome_corrigido_na_mesma_linha_mantem_o_registro(app):
    _gravar([_linha(4, "Maria Clar", *MARIA[1:])])
    visita = _visita_de("Maria Clar")[0]
    _vacinar(visita)
    visita_id = visita.id

    _gravar([_linha(4, *MARIA)], prune_orphans=True)

    linhas = _painel()
    assert [row["tutor"] for row in linhas] == ["Maria Clara"]
    assert linhas[0]["visitId"] == visita_id
    assert linhas[0]["animals"][0]["status"] == "vacinado"


def test_pessoa_que_volta_para_a_aba_recupera_o_registro_estacionado(app):
    _gravar([_linha(3, *ANA), _linha(4, *MARIA)])
    maria = _visita_de("Maria Clara")[0]
    _vacinar(maria)
    maria_id = maria.id

    _gravar([_linha(3, *ANA)], prune_orphans=True)
    assert db.session.get(PmoVaccinationVisit, maria_id).source_row < 0

    _gravar([_linha(3, *ANA), _linha(8, *MARIA)], prune_orphans=True)

    linha = next(row for row in _painel() if row["tutor"] == "Maria Clara")
    assert linha["visitId"] == maria_id
    assert linha["sourceRow"] == 8
    assert linha["animals"][0]["status"] == "vacinado"


def test_aba_mestre_acompanha_a_pessoa_ao_trocar_linhas(app):
    """A aba mestre também precisa preservar a identidade nas trocas."""
    mestre = servico.PMO_MASTER_SHEET_TITLE
    _gravar([_linha(4, *ANA), _linha(5, *BRUNO)], sheet_gid="mestre", sheet_title=mestre)
    linha_4 = PmoVaccinationVisit.query.filter_by(sheet_gid="mestre", source_row=4).one().id

    _gravar([_linha(4, *BRUNO), _linha(5, *ANA)], sheet_gid="mestre", sheet_title=mestre)

    assert PmoVaccinationVisit.query.filter_by(sheet_gid="mestre", source_row=5).one().id == linha_4


def _login_admin(client):
    admin = User(name="Admin PMO", email="admin-espelho@example.com", role="admin")
    admin.set_password("senha")
    db.session.add(admin)
    db.session.commit()
    with client.session_transaction() as session:
        session["_user_id"] = str(admin.id)
        session["_fresh"] = True


def test_sincronizar_no_painel_tira_da_lista_quem_saiu_da_aba_sem_apagar(app, client, monkeypatch):
    _gravar([_linha(3, *ANA), _linha(4, *MARIA), _linha(5, *BRUNO)])
    bruno = _visita_de("Bruno Lima")[0]
    bruno_id, bruno_token = bruno.id, bruno.public_token
    _login_admin(client)

    linhas_da_aba = [_linha(3, *ANA), _linha(4, *MARIA)]
    monkeypatch.setattr(servico, "sync_vacina_pmo_sheet", lambda **_kwargs: PmoSyncResult(
        rows=linhas_da_aba, spreadsheet_id=PLANILHA, sheet_range="A:T",
        sheet_gid=ABA_GID, sheet_title=ABA_TITULO,
    ))

    resposta = client.post("/vacina-pmo/sync", json={"sheet_gid": ABA_GID, "sheet_title": ABA_TITULO})
    assert resposta.status_code == 200
    estado = client.get(f"/vacina-pmo/state?sheet_gid={ABA_GID}").get_json()

    assert [row["tutor"] for row in resposta.get_json()["rows"]] == ["Ana Souza", "Maria Clara"]
    assert [row["tutor"] for row in estado["rows"]] == ["Ana Souza", "Maria Clara"]
    assert db.session.get(PmoVaccinationVisit, bruno_id) is not None, "o painel nunca apaga"

    # A linha do Bruno voltou (ex.: recortar/colar pego no meio): mesmo registro, mesmo link.
    linhas_da_aba.append(_linha(6, *BRUNO))
    client.post("/vacina-pmo/sync", json={"sheet_gid": ABA_GID, "sheet_title": ABA_TITULO})
    volta = db.session.get(PmoVaccinationVisit, bruno_id)
    assert volta.source_row == 6
    assert volta.public_token == bruno_token


@pytest.mark.parametrize("coluna, texto", [
    (9, "Cachorros: Rex / Gatos: Mimi"),
    (10, "Gatos: tomar cuidado com a Mimi"),
    (10, "sem perdas"),
    (10, "dar as sobras de ração"),
])
def test_casa_com_texto_de_totais_nos_nomes_ou_na_observacao_continua_na_lista(coluna, texto):
    """A casa da Ângela sumia: "Gatos:" nos nomes a fazia passar por linha de totais."""
    linha = [
        "Ângela Souza", "Rua X", "100", "", "Centro", "16991112222", "",
        "1", "1", "Rex, Mimi", "", "", "", "", "", "", "29/09/2026", "Tarde",
    ]
    linha[coluna] = texto

    parsed = servico.parse_vacina_pmo_rows([linha])

    assert [row["tutor"] for row in parsed] == ["Ângela Souza"]


@pytest.mark.parametrize("linha", [
    ["Total de animais", "", "", "", "", "", "", "10", "3"],
    ["Cachorros: 10", "", "", "", "", "", "", "", "", "", "", "", "0", "0"],
    ["Nome completo do tutor", "Endereço", "Número", "", "Bairro", "Telefone"],
    ["Manhã", "", "", "", "", "", "", "", "", "", "", "", "Sobras", "", "0"],
])
def test_linhas_de_totais_e_cabecalho_continuam_fora(linha):
    assert servico._is_summary_or_header(linha)


def test_troca_tutor_mesmo_telefone_e_endereco_nao_herda_conta(app):
    telefone = "5516991110001"
    _gravar([_linha(4, "Maria Silva", telefone, "Rua A, 10", "Rex")])
    original = _visita_de("Maria Silva")[0]
    original_id, dono_id = original.id, original.tutor_user_id
    _gravar([_linha(4, "Joana Silva", telefone, "Rua A, 10", "Mimi", "gato")])
    nova = _visita_de("Joana Silva")[0]
    assert nova.id != original_id
    assert nova.tutor_user_id != dono_id
    assert nova.animals[0].animal.user_id == nova.tutor_user_id
    assert db.session.get(PmoVaccinationVisit, original_id).source_row < 0


def test_homonimos_mesma_linha_com_telefone_e_endereco_diferentes(app):
    _gravar([_linha(4, "Ana Souza", "5516991110001", "Rua A, 10", "Rex")])
    original = _visita_de("Ana Souza")[0].id
    _gravar([_linha(4, "Ana Souza", "5516991110002", "Rua B, 20", "Mel")])
    assert PmoVaccinationVisit.query.filter_by(sheet_gid=ABA_GID, source_row=4).one().id != original
    assert db.session.get(PmoVaccinationVisit, original).source_row < 0


@pytest.mark.parametrize("writer", ["write_note_to_sheet", "write_vaccinated_counts_to_sheet", "write_animal_names_to_sheet", "write_animal_counts_to_sheet", "write_attended_by_to_sheet", "write_tutor_name_color_to_sheet"])
def test_gravacao_recusa_linha_que_mudou(app, monkeypatch, writer):
    from unittest.mock import MagicMock
    _gravar([_linha(4, *MARIA)])
    visita = _visita_de("Maria Clara")[0]
    service = MagicMock()
    service.spreadsheets().values().get().execute.return_value = {"values": [["Outra Pessoa", "Rua X", "1", "", "Centro", "16999999999"]]}
    service.reset_mock()
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: service)
    assert getattr(servico, writer)(visita) is False
    service.spreadsheets().values().update.assert_not_called()
    service.spreadsheets().batchUpdate.assert_not_called()


def test_gravacao_confere_identidade_e_permite_linha_correta(app, monkeypatch):
    from unittest.mock import MagicMock
    _gravar([_linha(4, *MARIA)])
    visita = _visita_de("Maria Clara")[0]
    service = MagicMock()
    service.spreadsheets().values().get().execute.return_value = {"values": [["Maria Clara", "Rua B", "20", "", "Centro", MARIA[1]]]}
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: service)
    assert servico.write_note_to_sheet(visita) is True
    service.spreadsheets().values().update.assert_called_once()


def test_animal_removido_nao_e_reaproveitado(app):
    from models import Animal
    from time_utils import utcnow
    _gravar([_linha(4, *MARIA)])
    visita = _visita_de("Maria Clara")[0]
    original = visita.animals[0].animal
    original.removido_em = utcnow()
    visita.animals[0].animal = None
    db.session.flush()
    servico._ensure_real_animal(visita.animals[0])
    db.session.flush()
    assert visita.animals[0].animal.id != original.id
    assert db.session.get(Animal, original.id).removido_em is not None


def test_visita_pendente_sai_e_volta_sem_perder_token(app):
    _gravar([_linha(3, *ANA), _linha(4, *MARIA)])
    visita = _visita_de("Maria Clara")[0]
    visita_id, token = visita.id, visita.public_token
    _gravar([_linha(3, *ANA)], prune_orphans=True)
    assert db.session.get(PmoVaccinationVisit, visita_id).source_row < 0
    _gravar([_linha(3, *ANA), _linha(8, *MARIA)], prune_orphans=True)
    volta = db.session.get(PmoVaccinationVisit, visita_id)
    assert volta.source_row == 8
    assert volta.public_token == token


def test_sync_sem_identificador_de_aba_falha_com_seguranca(app):
    with pytest.raises(ValueError, match="identificar a aba"):
        _gravar([_linha(4, *ANA)], sheet_gid="")
    assert PmoVaccinationVisit.query.count() == 0


def test_resolve_gid_pelo_nome_da_aba(monkeypatch):
    from unittest.mock import MagicMock
    service = MagicMock()
    service.spreadsheets().get().execute.return_value = {"sheets": [{"properties": {"title": "09/09/2026", "sheetId": 42}}]}
    result = servico._resolve_sheet_target(service, "https://docs.google.com/spreadsheets/d/planilha123/edit", "A:T", sheet_title="09/09/2026")
    assert result[2:] == ("42", "09/09/2026")
