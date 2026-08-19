"""Regressões das melhorias de confiança, crescimento e portabilidade."""

import gzip
import io
import json
import zipfile
from decimal import Decimal

import flask_login.utils as login_utils

from extensions import db
from models import Animal, Clinica, Product, ProductEvent, User


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_support_uses_real_contact_and_has_no_configuration_placeholders(client):
    response = client.get("/support")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "lukemarki3@gmail.com" in html
    assert "31 99950-5748" in html
    assert "Configure SUPPORT" not in html
    assert "contato@exemplo.com" not in html.lower()


def test_404_is_branded_private_and_not_indexable(client):
    response = client.get(
        "/pagina-que-nao-existe",
        headers={"Accept": "text/html"},
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 404
    assert "PetOrlândia" in html
    assert 'content="noindex,follow"' in html
    assert "no-store" in response.headers["Cache-Control"]


def test_public_html_is_compressed_when_browser_accepts_gzip(client):
    response = client.get("/", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    assert "PetOrlândia" in gzip.decompress(response.data).decode("utf-8")


def test_product_events_persist_utm_and_real_cta_source(app, client):
    landing = client.get(
        "/?utm_source=parceiro&utm_medium=indicacao&utm_campaign=lancamento"
    )
    assert landing.status_code == 200

    click = client.post(
        "/eventos/cta",
        json={
            "name": "cta_home_clinic",
            "path": "/precos",
            "text": "Testar grátis",
        },
    )
    assert click.status_code == 204

    landing_event = ProductEvent.query.filter_by(event_name="landing_viewed").one()
    cta_event = ProductEvent.query.filter_by(event_name="cta_home_clinic").one()
    assert landing_event.utm_source == "parceiro"
    assert landing_event.utm_medium == "indicacao"
    assert landing_event.utm_campaign == "lancamento"
    assert cta_event.source_path == "/precos"
    assert cta_event.properties["link_text"] == "Testar grátis"


def test_pricing_plan_survives_registration_entry(client):
    response = client.get("/register?plan=anual")
    assert response.status_code == 200

    with client.session_transaction() as session:
        assert session["preferred_membership_plan"] == "anual"


def test_owner_can_export_clinic_data_but_unrelated_user_cannot(
    app,
    client,
    monkeypatch,
):
    owner = User(name="Dra. Marina", email="marina.export@example.com")
    owner.set_password("segredo123")
    stranger = User(name="Outro usuário", email="outro.export@example.com")
    stranger.set_password("segredo123")
    tutor = User(
        name="Tutor exportado",
        email="tutor.export@example.com",
        phone="31999999999",
    )
    tutor.set_password("segredo123")
    db.session.add_all([owner, stranger, tutor])
    db.session.flush()

    clinic = Clinica(
        nome="Clínica Portável",
        owner_id=owner.id,
        email="contato@clinicaportavel.example",
        status="ativa",
    )
    db.session.add(clinic)
    db.session.flush()
    db.session.add(Animal(name="Luna", user_id=tutor.id, clinica_id=clinic.id))
    db.session.commit()

    _login(client, owner.id)
    monkeypatch.setattr(login_utils, "_get_user", lambda: owner)
    response = client.get(
        f"/clinica/{clinic.id}/exportar-dados",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    assert "attachment" in response.headers["Content-Disposition"]

    with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
        assert {
            "LEIA-ME.txt",
            "clinica.json",
            "tutores.json",
            "pacientes.json",
            "agendamentos.json",
            "consultas.json",
            "vacinas.json",
            "orcamentos.json",
            "orcamento_itens.json",
        }.issubset(bundle.namelist())
        patients = json.loads(bundle.read("pacientes.json"))
        tutors = json.loads(bundle.read("tutores.json"))
        assert patients[0]["name"] == "Luna"
        assert tutors[0]["email"] == "tutor.export@example.com"

    unrelated_client = app.test_client()
    _login(unrelated_client, stranger.id)
    monkeypatch.setattr(login_utils, "_get_user", lambda: stranger)
    denied = unrelated_client.get(
        f"/clinica/{clinic.id}/exportar-dados",
        headers={"Accept": "text/html"},
    )
    assert denied.status_code == 403


def test_marketplace_price_is_a_transparent_take_rate(app):
    app.config["MERCADOPAGO_MARKETPLACE_FEE_PERCENT"] = 10

    assert Product.public_price_from_base(Decimal("10.00")) == Decimal("11.11")
    assert Product.public_price_from_base(Decimal("100.00")) == Decimal("111.11")
