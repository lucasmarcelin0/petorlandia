"""O "Sincronizar planilha" não pode apagar o que o painel registrou.

Em 05/11/2026 a linha do César foi editada à mão na aba; a partir daí o painel
não conseguia mais gravar nela (a trava de identidade recusava). O sync
seguinte copiou a aba por cima do banco: o Thor, incluído e vacinado no
painel, sumiu da lista; a Luquinha virou um "luquinho" novo, sem a vacina; e
as anotações "HH:MM - ...: vacinado." e o nome de quem atendeu foram apagados.
"""

from __future__ import annotations

from datetime import date

import pytest

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services import vacina_pmo_service as servico
from services.vacina_pmo_service import persist_vacina_pmo_rows

ABA = dict(spreadsheet_id="plan-1", sheet_gid="20261104", sheet_title="05/11/2026")


@pytest.fixture()
def planilha(monkeypatch):
    """Registra o que o sync tentaria devolver para a aba, sem chamar o Google."""
    enviados = []
    monkeypatch.setattr(servico, "_pmo_push_panel_to_sheet", lambda visit: enviados.append(visit.id))
    return enviados


def _visita_do_cesar(animais, note="", attended_by=None):
    visita = PmoVaccinationVisit(
        source_row=8, tutor_name="César Augusto gouveia", address="Rua 3, 360, Posto kory, Centro",
        phone1="99953452", phone2="99953452", dogs=3, cats=0, password="PMOTESTE",
        vaccine_date=date(2026, 11, 5), note=note, attended_by=attended_by, **ABA,
    )
    db.session.add(visita)
    db.session.flush()
    for posicao, (nome, status) in enumerate(animais, start=1):
        db.session.add(PmoVaccinationAnimal(
            visit=visita, position=posicao, name=nome, species="cao", status=status,
        ))
    db.session.commit()
    return visita.id


def _linha(nomes, note="2 cachorro é em outro endereço", attended_by=""):
    return {
        "sourceRow": 8, "tutor": "César Augusto gouveia",
        "address": "Rua 3, 360, Posto kory, Centro",
        "phone1": "99953452", "phone2": "99953452", "dogs": len(nomes), "cats": 0,
        "animals": [{"name": nome, "species": "cao"} for nome in nomes],
        "note": note, "attendedBy": attended_by, "date": "2026-11-05", "shift": "Manhã",
    }


def _sincroniza(linha):
    persist_vacina_pmo_rows([linha], park_orphans=True, **ABA)


def _animais(visita_id):
    visita = db.session.get(PmoVaccinationVisit, visita_id)
    return [(a.name, a.status) for a in sorted(visita.animals, key=lambda a: a.position)]


def test_animal_vacinado_no_painel_nao_some_no_sync(app, planilha):
    visita_id = _visita_do_cesar([
        ("Carrapicho", "vacinado"), ("julio", "vacinado"),
        ("Luquinha", "vacinado"), ("Thor", "vacinado"),
    ])

    _sincroniza(_linha(["Carrapicho", "julio", "luquinho"]))

    assert _animais(visita_id) == [
        ("Carrapicho", "vacinado"), ("julio", "vacinado"),
        ("Luquinha", "vacinado"), ("Thor", "vacinado"),
    ]
    assert db.session.get(PmoVaccinationVisit, visita_id).dogs == 4
    assert planilha == [visita_id], "a aba precisa receber os 4 nomes de volta"


def test_vacinado_mantem_o_vinculo_quando_a_aba_grafa_diferente(app, planilha):
    visita_id = _visita_do_cesar([("Luquinha", "vacinado")])
    animal = db.session.get(PmoVaccinationVisit, visita_id).animals[0]
    animal.vaccinated_at = servico.utcnow()
    db.session.commit()

    _sincroniza(_linha(["luquinho"]))

    animal = db.session.get(PmoVaccinationVisit, visita_id).animals[0]
    assert (animal.name, animal.status) == ("Luquinha", "vacinado")
    assert animal.vaccinated_at is not None, "não pode virar outro animal sem a dose"


def test_vacinado_trocado_por_outro_nome_fica_e_o_novo_entra(app, planilha):
    visita_id = _visita_do_cesar([("Rex", "vacinado")])

    _sincroniza(_linha(["Bidu"]))

    assert _animais(visita_id) == [("Bidu", "pendente"), ("Rex", "vacinado")]


def test_pendente_continua_seguindo_a_planilha(app, planilha):
    visita_id = _visita_do_cesar([("Rex", "pendente"), ("Bidu", "pendente")])

    _sincroniza(_linha(["Toby"]))

    assert _animais(visita_id) == [("Toby", "pendente")]
    assert planilha == []


def test_anotacoes_do_painel_e_quem_atendeu_sobrevivem(app, planilha):
    nota_painel = "2 cachorro é em outro endereço | 08:53 - julio: vacinado. | 09:10 - Portão azul"
    visita_id = _visita_do_cesar([("julio", "vacinado")], note=nota_painel, attended_by="Dona Maria")

    _sincroniza(_linha(["julio"]))

    visita = db.session.get(PmoVaccinationVisit, visita_id)
    assert visita.note == nota_painel
    assert visita.attended_by == "Dona Maria"
    assert planilha == [visita_id]


def test_nota_ja_copiada_para_a_aba_nao_duplica(app, planilha):
    nota = "Avisar quando chegar | 09:25 - julio: vacinado."
    visita_id = _visita_do_cesar([("julio", "vacinado")], note=nota, attended_by="César")

    _sincroniza(_linha(["julio"], note=nota, attended_by="César"))

    assert db.session.get(PmoVaccinationVisit, visita_id).note == nota
    assert planilha == []


def test_linha_que_passou_para_outra_casa_nao_herda_nada(app, planilha):
    visita_id = _visita_do_cesar(
        [("Thor", "vacinado")], note="08:53 - Thor: vacinado.", attended_by="Dona Maria",
    )
    linha = _linha(["Bidu"], note="")
    linha.update(tutor="Outra Pessoa", phone1="16999998888", phone2="", address="Rua 9, 99")

    _sincroniza(linha)

    nova = PmoVaccinationVisit.query.filter_by(source_row=8, **ABA).one()
    assert nova.id != visita_id
    assert (nova.note, nova.attended_by) == ("", None)
    assert [(a.name, a.status) for a in nova.animals] == [("Bidu", "pendente")]
    antiga = db.session.get(PmoVaccinationVisit, visita_id)
    assert [(a.name, a.status) for a in antiga.animals] == [("Thor", "vacinado")]
