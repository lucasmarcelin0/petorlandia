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


# Layout real de uma aba do dia (25/08/2026): bloco da manha, totais no meio,
# cabecalho de novo e bloco da tarde. Cada vaga ja vem com data (Q) e turno (R)
# preenchidos pelo modelo; as linhas de totais tambem tem data, mas tem L..O
# preenchidos. Colunas: 0=tutor .. 10=obs, 11..14=execucao, 16=data, 17=turno.
def _aba_do_dia():
    def linha(**kw):
        base = [""] * 18
        for indice, valor in kw.items():
            base[int(indice[1:])] = valor
        return base

    vazia_manha = linha(c16="25/08/2026", c17="Manha")
    vazia_tarde = linha(c16="25/08/2026", c17="Tarde")
    return [
        linha(c0="Nome completo do tutor", c17="Turno"),                 # 1 cabecalho
        linha(c0="Jose Mauro", c5="16993331592", c7="1", c9="Bob",
              c12="1", c16="25/08/2026", c17="Manha"),                   # 2 casa
        linha(c0="Ariadne", c5="16991982037", c7="1", c9="Mavi",
              c12="1", c16="25/08/2026", c17="Manha"),                   # 3 casa
        list(vazia_manha),                                               # 4 VAGA manha
        list(vazia_manha),                                               # 5 VAGA manha
        linha(c12="11", c13="5"),                                        # 6 totais
        linha(c11="25/08/2026", c12="Perdas", c16="25/08/2026",
              c17="Manha"),                                              # 7 resumo com data
        linha(c0="Nome completo do tutor", c17="Turno"),                 # 8 cabecalho tarde
        linha(c0="Jessica", c5="16991579001", c7="1", c9="Mel",
              c12="1", c16="25/08/2026", c17="Tarde"),                   # 9 casa
        list(vazia_tarde),                                               # 10 VAGA tarde
        list(vazia_tarde),                                               # 11 VAGA tarde
        linha(c12="2", c13="3"),                                         # 12 totais
    ]


class _SheetsFalso:
    """Planilha falsa com o layout de blocos que a aba do dia realmente tem."""

    def __init__(self, *, valores=None, falha=None):
        self.updates: list[dict] = []
        self.valores = valores if valores is not None else _aba_do_dia()
        self.falha = falha

    # A API do Google encadeia spreadsheets().values().<op>().execute()
    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        self._resposta = {"values": [list(linha) for linha in self.valores]}
        return self

    def update(self, *, spreadsheetId, range, valueInputOption, body):
        if self.falha:
            raise self.falha
        self.updates.append({
            "spreadsheetId": spreadsheetId, "range": range,
            "valueInputOption": valueInputOption, "body": body,
        })
        self._resposta = {}
        return self

    def batchUpdate(self, **kwargs):
        self._resposta = {}
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

    assert len(planilha.updates) == 1, "a planilha precisa receber a linha"
    escrita = planilha.updates[0]
    valores = escrita["body"]["values"][0]
    assert valores[0] == "Marina Alves Prado"
    assert valores[1:5] == ["Rua 12", "480", "Fundos", "Centro"]
    assert valores[7] == "1" and valores[8] == "1", "contagem por espécie"
    assert valores[9] == "Bidu, Nina"
    assert len(valores) == 11, "só as colunas A..K: data e turno são do modelo"
    assert escrita["range"] == "'25/08/2026'!A10:K10", (
        "escreve na primeira vaga livre da tarde, sem deslocar ninguém"
    )

    visita = PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").one()
    assert visita.source_row == 10, "a linha e a vaga escolhida"
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


def test_aba_lotada_recusa_em_vez_de_inventar_linha(app, monkeypatch):
    """Sem vaga, e melhor recusar do que empurrar as casas para baixo."""
    aba = _aba_do_dia()
    for linha in aba:
        if not linha[0] and linha[16]:
            linha[0] = "Ocupada"  # tira todas as vagas
    falsa = _SheetsFalso(valores=aba)
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: falsa)
    monkeypatch.setattr(servico, "_resolve_sheet_title_by_gid",
                        lambda service, spreadsheet_id, gid: "25/08/2026")

    with app.test_request_context():
        with pytest.raises(ValueError, match="vaga livre"):
            create_vacina_pmo_visit(_payload())

    assert not falsa.updates
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
    assert not planilha.updates, "nada vai para a planilha antes de validar"


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
    assert not planilha.updates


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


# --------------------------------------------------------------------------
# A vaga certa (o bug de 25/08/2026)
# --------------------------------------------------------------------------
# A primeira versao usava values().append e deixava o Google adivinhar onde a
# tabela terminava. Nessa aba, que tem dois blocos e totais no meio, ele
# inseriu no topo: as casas desceram duas linhas e o source_row de todas ficou
# apontando para a pessoa errada. Estes testes fixam o comportamento correto.

def test_escreve_na_vaga_do_turno_pedido(app, planilha):
    with app.test_request_context():
        create_vacina_pmo_visit(_payload(shift="Manhã"))

    assert planilha.updates[0]["range"] == "'25/08/2026'!A4:K4", (
        "vaga da manhã é a linha 4; a da tarde seria a 10"
    )
    visita = PmoVaccinationVisit.query.filter_by(tutor_name="Marina Alves Prado").one()
    assert visita.source_row == 4


def test_nunca_escreve_numa_linha_de_totais(app, planilha):
    """A linha 7 tem data e turno como uma vaga, mas é resumo (L..O preenchidos)."""
    aba = _aba_do_dia()
    for indice in (3, 4):          # tira as vagas reais da manha (linhas 4 e 5)
        aba[indice][0] = "Ocupada"
    falsa = _SheetsFalso(valores=aba)
    import services.vacina_pmo_service as s
    original = s._get_sheets_service_rw
    s._get_sheets_service_rw = lambda: falsa
    try:
        with app.test_request_context():
            with pytest.raises(ValueError, match="vaga livre"):
                create_vacina_pmo_visit(_payload(shift="Manhã"))
    finally:
        s._get_sheets_service_rw = original
    assert not falsa.updates, "a linha de resumo não pode ser usada como vaga"


def test_nao_desloca_as_casas_que_ja_estavam_na_aba(app, planilha):
    """Escrever numa vaga vazia mantém o source_row de todo mundo."""
    with app.test_request_context():
        create_vacina_pmo_visit(_payload())

    assert len(planilha.updates) == 1
    intervalo = planilha.updates[0]["range"]
    assert ":K" in intervalo, "escreve só as colunas da casa"
    # Nenhuma operacao de insercao de linha foi pedida.
    assert all("insertDataOption" not in escrita for escrita in planilha.updates)


def test_recusa_quando_o_banco_ja_tem_casa_naquela_linha(app, planilha):
    """Planilha e banco discordando: melhor parar do que sobrescrever alguém."""
    existente = PmoVaccinationVisit(
        spreadsheet_id="1oN74lysYpQOIYgS9nlyrQUgxa0w1FHS7yGVftpzbqAk",
        sheet_gid="0",
        sheet_title="25/08/2026",
        source_row=10,
        tutor_name="Moradora Anterior",
        password="PMOZZZZZ",
    )
    db.session.add(existente)
    db.session.commit()

    with app.test_request_context():
        with pytest.raises(ValueError, match="Moradora Anterior"):
            create_vacina_pmo_visit(_payload())

    assert not planilha.updates
