"""Validade do lote na carteirinha da campanha antirrábica.

Bug de campo (28/10/2026): as carteirinhas mostravam o lote
"Fab. 09/2024 - Val. 09/2026" e a vacina parecia vencida, mas o lote em uso
vence em 01/2027. As próximas doses saem com a validade certa e as já
gravadas com o texto padrão antigo são corrigidas (migration d4b8f2a6c1e3 e
ao reprocessar a dose); um lote digitado à mão não é tocado.
"""
from __future__ import annotations

from datetime import date

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit, Vacina
from services import vacina_pmo_service as servico


def _visita_vacinada(nome="Bidu", row=2):
    visita = PmoVaccinationVisit(
        spreadsheet_id="plan-1",
        sheet_gid="0",
        sheet_title="22/09/2026",
        source_row=row,
        tutor_name="Isabela da Silva Franks",
        address="Avenida 16, 1934, Jardim Cidade Alta",
        phone1="5516981817686",
        dogs=1,
        cats=0,
        vaccine_date=date(2026, 9, 22),
        password="PMOTESTE",
    )
    db.session.add(visita)
    db.session.flush()
    db.session.add(PmoVaccinationAnimal(
        visit=visita, position=1, name=nome, species="cao", status="vacinado",
    ))
    db.session.flush()
    return visita


def test_nova_dose_sai_com_validade_01_2027(app):
    visita = _visita_vacinada()
    servico._ensure_visit_records(visita)
    db.session.commit()

    vacina = visita.animals[0].vaccine
    assert vacina is not None
    assert vacina.lote == "Val. 01/2027"


def test_dose_gravada_com_lote_antigo_e_corrigida(app):
    visita = _visita_vacinada()
    servico._ensure_visit_records(visita)
    vacina = visita.animals[0].vaccine
    vacina.lote = "Fab. 09/2024 - Val. 09/2026"
    db.session.commit()

    servico._ensure_visit_records(visita)
    db.session.commit()

    assert db.session.get(Vacina, vacina.id).lote == "Val. 01/2027"


def test_lote_digitado_a_mao_nao_e_trocado(app):
    visita = _visita_vacinada()
    servico._ensure_visit_records(visita)
    vacina = visita.animals[0].vaccine
    vacina.lote = "ABC123 - Val. 03/2027"
    db.session.commit()

    servico._ensure_visit_records(visita)
    db.session.commit()

    assert db.session.get(Vacina, vacina.id).lote == "ABC123 - Val. 03/2027"


def test_carteirinha_nao_mostra_validade_vencida(app, client):
    visita = _visita_vacinada()
    servico._ensure_visit_records(visita)
    servico._ensure_visit_public_token(visita)
    db.session.commit()

    html = client.get(
        f"/vacina-pmo/c/{visita.public_token}/pet/{visita.animals[0].id}"
    ).get_data(as_text=True)

    assert "Val. 01/2027" in html
    assert "Val. 09/2026" not in html
