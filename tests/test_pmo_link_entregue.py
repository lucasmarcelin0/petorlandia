"""Link de carteirinha entregue ao morador nunca vira 404.

O ``public_token`` muda quando a visita e recriada — foi o que aconteceu
quando duas linhas indevidas empurraram a aba de 25/08/2026 e o sync apagou e
refez os registros. So que o tutor ja tinha o link no WhatsApp, enviado em
nome da Prefeitura. Endereco publicado assim nao pode deixar de funcionar.
"""

from __future__ import annotations

from datetime import date

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit, PmoVaccinationVisitToken
from services import vacina_pmo_service as servico
from services.vacina_pmo_service import get_vacina_pmo_public_visit


def _visita(token=None, tutor="Jessica Poli vieira"):
    visita = PmoVaccinationVisit(
        spreadsheet_id="plan-1", sheet_gid="9", sheet_title="25/08/2026",
        source_row=18, tutor_name=tutor, address="Travessa 14, 1839",
        phone1="5516991579001", dogs=1, cats=0, password="PMOTESTE",
        vaccine_date=date(2026, 8, 25), public_token=token,
    )
    db.session.add(visita)
    db.session.flush()
    db.session.add(PmoVaccinationAnimal(
        visit=visita, position=1, name="Mel", species="cao", status="vacinado"))
    db.session.flush()
    return visita


def test_token_atual_e_guardado_no_primeiro_acesso(app):
    visita = _visita(token="token-atual")
    db.session.commit()

    with app.test_request_context():
        assert get_vacina_pmo_public_visit("token-atual") is visita

    assert PmoVaccinationVisitToken.query.filter_by(token="token-atual").count() == 1


def test_link_antigo_continua_abrindo_a_carteirinha(app):
    """O caso da Jessica: mensagem ja enviada com o link que morreu."""
    visita = _visita(token="token-novo")
    db.session.add(PmoVaccinationVisitToken(visit_id=visita.id, token="token-antigo"))
    db.session.commit()

    with app.test_request_context():
        assert get_vacina_pmo_public_visit("token-antigo") is visita
        assert get_vacina_pmo_public_visit("token-novo") is visita


def test_token_desconhecido_continua_sem_visita(app):
    _visita(token="token-atual")
    db.session.commit()

    with app.test_request_context():
        assert get_vacina_pmo_public_visit("nunca-existiu") is None


def test_token_nao_e_guardado_duas_vezes(app):
    visita = _visita(token="token-atual")
    db.session.commit()

    with app.test_request_context():
        for _ in range(3):
            get_vacina_pmo_public_visit("token-atual")

    assert PmoVaccinationVisitToken.query.filter_by(token="token-atual").count() == 1


def test_apagar_a_visita_leva_os_tokens_junto(app):
    visita = _visita(token="token-atual")
    db.session.add(PmoVaccinationVisitToken(visit_id=visita.id, token="token-antigo"))
    db.session.commit()

    db.session.delete(visita)
    db.session.commit()

    assert PmoVaccinationVisitToken.query.count() == 0


def test_pagina_de_recuperacao_em_vez_de_404_seco(app, client):
    resposta = client.get("/vacina-pmo/c/link-que-nao-existe")

    assert resposta.status_code == 404, "o status continua sendo 404 para buscadores"
    html = resposta.get_data(as_text=True)
    assert "Este link mudou de endereço" in html
    assert "continua registrada" in html, "o morador precisa saber que nada se perdeu"
    assert "Primeiro acesso" in html, "e qual o caminho para recuperar"


def test_recuperacao_tambem_no_link_do_pet(app, client):
    visita = _visita(token="token-atual")
    db.session.commit()

    html = client.get(f"/vacina-pmo/c/token-atual/pet/999999").get_data(as_text=True)
    assert "Este link mudou de endereço" in html
