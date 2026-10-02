"""Quem herda a linha da planilha não herda a vacina de quem estava nela.

Em 28/09/2026 a linha de uma casa vacinada em 17/09 passou a ser de outra
tutora. O registro foi reaproveitado, os animais foram renomeados e ficaram
com o status "ja imunizado" e a data da dose da casa anterior: a tela passou a
dizer "Vacinado em 17/09/2026" para cinco cães que nunca foram vacinados, e a
data falsa ainda contaminou a lista do dia seguinte da nova tutora.
"""

from __future__ import annotations

from datetime import date

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services import vacina_pmo_service as servico
from services.vacina_pmo_service import persist_vacina_pmo_rows


def _sem_efeitos_externos(monkeypatch):
    monkeypatch.setattr(servico, "_ensure_visit_records", lambda visit: None)
    monkeypatch.setattr(servico, "_pmo_geocode_address", lambda address: None)


def _visita_imunizada(gid, *, tutor, phone, address, nomes):
    visita = PmoVaccinationVisit(
        spreadsheet_id="plan-1", sheet_gid=gid, sheet_title="Inscrição a agendar",
        source_row=7, tutor_name=tutor, address=address, phone1=phone,
        dogs=len(nomes), cats=0, password="PMOTESTE",
    )
    db.session.add(visita)
    db.session.flush()
    for posicao, nome in enumerate(nomes, start=1):
        db.session.add(PmoVaccinationAnimal(
            visit=visita, position=posicao, name=nome, species="cao",
            status="imunizado", immune_since=date(2026, 9, 17),
        ))
    db.session.commit()
    return visita.id


def _linha(*, tutor, phone, address, nomes):
    return {
        "sourceRow": 7, "tutor": tutor, "address": address, "phone1": phone,
        "phone2": "", "dogs": len(nomes), "cats": 0,
        "animals": [{"name": nome, "species": "cao"} for nome in nomes],
        "note": "", "date": "", "shift": "", "password": "PMOAAAAA",
    }


def test_outra_casa_na_linha_comeca_pendente(app, monkeypatch):
    """Casamento só pela linha (sem gid): foi assim que o erro aconteceu."""
    _sem_efeitos_externos(monkeypatch)
    visita_id = _visita_imunizada(
        "", tutor="Carla Fernanda Silva", phone="5516990000001",
        address="Rua 3, 10", nomes=("Palhaco", "Pandora"),
    )

    persist_vacina_pmo_rows(
        [_linha(tutor="Agatha Crissy Luciano", phone="5516991019539",
                address="Avenida J, 648", nomes=("Meg", "Amora"))],
        spreadsheet_id="plan-1", sheet_gid="", sheet_title="Inscrição a agendar",
    )

    visita = db.session.get(PmoVaccinationVisit, visita_id)
    assert visita.tutor_name == "Agatha Crissy Luciano"
    for animal in visita.animals:
        assert animal.status == "pendente", animal.name
        assert animal.immune_since is None, animal.name


def test_animal_trocado_na_mesma_casa_perde_a_data_do_anterior(app, monkeypatch):
    _sem_efeitos_externos(monkeypatch)
    visita_id = _visita_imunizada(
        "", tutor="Carla Fernanda Silva", phone="5516990000001",
        address="Rua 3, 10", nomes=("Palhaco", "Pandora"),
    )

    persist_vacina_pmo_rows(
        [_linha(tutor="Carla Fernanda Silva", phone="5516990000001",
                address="Rua 3, 10", nomes=("Palhaco", "Rex"))],
        spreadsheet_id="plan-1", sheet_gid="", sheet_title="Inscrição a agendar",
    )

    visita = db.session.get(PmoVaccinationVisit, visita_id)
    por_nome = {animal.name: animal for animal in visita.animals}
    assert por_nome["Palhaco"].status == "imunizado"
    assert por_nome["Palhaco"].immune_since == date(2026, 9, 17)
    assert por_nome["Rex"].status == "pendente"
    assert por_nome["Rex"].immune_since is None
