"""Cadastro de casa nova durante a rota do vacinador.

A casa que aparece no meio da rota — o vizinho que viu a equipe, o tutor que
chegou depois — precisava esperar a proxima campanha. Estes testes fixam a
decisao central: a linha vai para a planilha PRIMEIRO, porque o sync apaga
toda visita cujo ``source_row`` sumiu de la, e o registro local so nasce com o
numero de linha que o Sheets devolveu.
"""

from __future__ import annotations

import pytest

from extensions import db
from models import PmoVaccinationVisit
from services import vacina_pmo_service as servico
from services.vacina_pmo_service import create_vacina_pmo_visit


class _SheetsFalso:
    """Planilha falsa que registra o append e devolve o intervalo criado."""

    def __init__(self, *, proxima_linha=27, falha=None):
        self.appends: list[dict] = []
        self.proxima_linha = proxima_linha
        self.falha = falha

    # A API do Google encadeia spreadsheets().values().append().execute()
    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        self._resposta = {"sheets": [{"properties": {"sheetId": 0, "title": "25/08/2026"}}]}
        return self

    def append(self, *, spreadsheetId, range, valueInputOption, insertDataOption, body):
        if self.falha:
            raise self.falha
        self.appends.append({
            "spreadsheetId": spreadsheetId, "range": range,
            "valueInputOption": valueInputOption,
            "insertDataOption": insertDataOption, "body": body,
        })
        self._resposta = {
            "updates": {"updatedRange": f"'25/08/2026'!A{self.proxima_linha}:R{self.proxima_linha}"}
        }
        return self

    def execute(self):
        return self._resposta


@pytest.fixture()
def planilha(monkeypatch):
    falsa = _SheetsFalso()
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: falsa)
    monkeypatch.setattr(servico, "_resolve_sheet_title_by_gid",
                        lambda service, spreadsheet_id, gid: "25/08/2026")
    return falsa


def _payload(**overrides):
    dados = {
        "sheet_gid": "0",
        "tutor": "Marina Alves Prado",
        "street": "Rua 12",
        "number": "480",
        "complement": "Fundos",
        "neighborhood": "Centro",
        "phone1": "16991234567",
        "phone2": "",
        "shift": "Tarde",
        "note": "Cachorro bravo, ligar antes",
        "animals": [
            {"name": "Bidu", "species": "cao"},
            {"name": "Nina", "species": "gato"},
        ],
    }
    dados.update(overrides)
    return dados


# --------------------------------------------------------------------------
# Caminho feliz
# --------------------------------------------------------------------------

def test_cadastra_a_casa_na_planilha_e_no_banco(app, planilha):
    with app.test_request_context():
        linha = create_vacina_pmo_visit(_payload())

    assert len(planilha.appends) == 1, "a planilha precisa receber a linha"
    valores = planilha.appends[0]["body"]["values"][0]
    assert valores[0] == "Marina Alves Prado"
    assert valores[1:5] == ["Rua 12", "480", "Fundos", "Centro"]
    assert valores[7] == "1" and valores[8] == "1", "contagem por espécie"
    assert valores[9] == "Bidu, Nina"
    assert valores[17] == "Tarde"
    assert planilha.appends[0]["insertDataOption"] == "INSERT_ROWS"

    visita = PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").one()
    assert visita.source_row == 27, "usa a linha que o Sheets devolveu"
    assert visita.sheet_title == "25/08/2026"
    assert visita.dogs == 1 and visita.cats == 1
    assert visita.address == "Rua 12, 480, Fundos, Centro"
    assert visita.password and visita.public_token
    assert [a.name for a in visita.animals] == ["Bidu", "Nina"]
    assert all(a.status == "pendente" for a in visita.animals)
    assert linha["tutor"] == "Marina Alves Prado"
    assert len(linha["animals"]) == 2


def test_a_visita_nasce_com_a_data_da_aba(app, planilha):
    from datetime import date

    with app.test_request_context():
        create_vacina_pmo_visit(_payload())

    visita = PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").one()
    assert visita.vaccine_date == date(2026, 8, 25)


def test_observacao_registra_que_veio_da_rota(app, planilha):
    with app.test_request_context():
        create_vacina_pmo_visit(_payload())

    visita = PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").one()
    assert "cadastrada durante a rota" in (visita.note or "")
    assert "Cachorro bravo" in (visita.note or "")


def test_telefone_e_normalizado(app, planilha):
    with app.test_request_context():
        create_vacina_pmo_visit(_payload(phone1="(16) 99123-4567"))

    visita = PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").one()
    assert visita.phone1 == "5516991234567"


# --------------------------------------------------------------------------
# Nada é criado pela metade
# --------------------------------------------------------------------------

def test_falha_na_planilha_nao_deixa_visita_orfa(app, monkeypatch):
    """Sem linha na planilha, o sync apagaria a visita: melhor nem criar."""
    falsa = _SheetsFalso(falha=RuntimeError("Google fora do ar"))
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: falsa)
    monkeypatch.setattr(servico, "_resolve_sheet_title_by_gid",
                        lambda service, spreadsheet_id, gid: "25/08/2026")

    with app.test_request_context():
        with pytest.raises(RuntimeError, match="Google fora do ar"):
            create_vacina_pmo_visit(_payload())

    assert PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").count() == 0


def test_planilha_sem_intervalo_de_volta_e_erro_claro(app, monkeypatch):
    class _SemIntervalo(_SheetsFalso):
        def execute(self):
            return {}

    falsa = _SemIntervalo()
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: falsa)
    monkeypatch.setattr(servico, "_resolve_sheet_title_by_gid",
                        lambda service, spreadsheet_id, gid: "25/08/2026")

    with app.test_request_context():
        with pytest.raises(RuntimeError, match="não informou onde ela ficou"):
            create_vacina_pmo_visit(_payload())

    assert PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").count() == 0


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mudanca, mensagem", [
    ({"tutor": ""}, "nome do tutor"),
    ({"animals": []}, "pelo menos um animal"),
    ({"animals": [{"name": "Bidu", "species": "papagaio"}]}, "cão ou gato"),
    ({"animals": [{"name": "Bidu", "species": "cao"}, {"name": "bidu", "species": "gato"}]},
     "duas vezes"),
    ({"sheet_gid": ""}, "aba do dia"),
    ({"street": "", "number": "", "complement": "", "neighborhood": "", "phone1": "", "phone2": ""},
     "endereço ou um telefone"),
])
def test_recusa_cadastro_incompleto(app, planilha, mudanca, mensagem):
    with app.test_request_context():
        with pytest.raises(ValueError, match=mensagem):
            create_vacina_pmo_visit(_payload(**mudanca))
    assert not planilha.appends, "nada vai para a planilha antes de validar"


def test_nome_de_animal_com_virgula_e_recusado(app, planilha):
    """A célula J é reimportada separando por vírgula: viraria dois animais."""
    with app.test_request_context():
        with pytest.raises(ValueError, match="sem vírgulas"):
            create_vacina_pmo_visit(_payload(animals=[{"name": "Bidu, Nina", "species": "cao"}]))


def test_limite_de_animais_por_casa(app, planilha):
    demais = [{"name": f"Pet{i}", "species": "cao"}
              for i in range(servico.PMO_VISIT_ANIMALS_MAX + 1)]
    with app.test_request_context():
        with pytest.raises(ValueError, match="no máximo"):
            create_vacina_pmo_visit(_payload(animals=demais))


def test_so_endereco_sem_telefone_e_aceito(app, planilha):
    with app.test_request_context():
        create_vacina_pmo_visit(_payload(phone1="", phone2=""))
    assert PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").count() == 1


def test_so_telefone_sem_endereco_e_aceito(app, planilha):
    with app.test_request_context():
        create_vacina_pmo_visit(_payload(
            street="", number="", complement="", neighborhood=""))
    assert PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").count() == 1


# --------------------------------------------------------------------------
# Rota HTTP
# --------------------------------------------------------------------------

def test_rota_exige_perfil_de_vacinador(app, client, planilha):
    resposta = client.post('/vacina-pmo/visit', json=_payload())
    assert resposta.status_code in (302, 401, 403), resposta.status_code
    assert not planilha.appends


def test_rota_devolve_400_com_mensagem_para_o_vacinador(app, client, planilha, monkeypatch):
    from flask_login import login_user
    from models import User

    vacinador = User(name="Vacinador", email="vac@example.com", role="vacinador", phone="")
    vacinador.set_password("PMOA1234")
    db.session.add(vacinador)
    db.session.commit()

    with client.session_transaction() as sessao:
        sessao['_user_id'] = str(vacinador.id)
        sessao['_fresh'] = True

    resposta = client.post('/vacina-pmo/visit', json=_payload(tutor=""))
    assert resposta.status_code == 400
    assert "nome do tutor" in resposta.get_json()["message"]
