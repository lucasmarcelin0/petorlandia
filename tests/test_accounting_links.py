import os
import sys
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import inspect

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app, db  # noqa: E402
import app as app_module  # noqa: E402
from models import (  # noqa: E402
    Animal,
    BlocoOrcamento,
    ClinicNotification,
    Clinica,
    Consulta,
    Orcamento,
    OrcamentoItem,
    User,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app


@pytest.fixture(autouse=True)
def stub_classification(monkeypatch):
    monkeypatch.setattr(app_module, "classify_transactions_for_month", lambda *_args, **_kwargs: None)


@pytest.fixture
def clinic_setup(app):
    with app.app_context():
        clinic = Clinica(nome="Clínica Norte")
        db.session.add(clinic)
        db.session.flush()

        admin = User(
            name="Admin",
            email="admin@example.com",
            role="admin",
            clinica_id=clinic.id,
        )
        admin.set_password("senha123")
        clinic.owner = admin

        tutor = User(name="Tutor", email="tutor@example.com")
        tutor.set_password("123456")

        db.session.add_all([admin, tutor])
        db.session.flush()

        animal = Animal(name="Bolt", user_id=tutor.id, clinica_id=clinic.id)
        db.session.add(animal)
        db.session.flush()

        consulta = Consulta(
            animal_id=animal.id,
            created_by=admin.id,
            clinica_id=clinic.id,
            status="in_progress",
        )
        db.session.add(consulta)
        db.session.flush()

        orcamento = Orcamento(
            clinica_id=clinic.id,
            consulta_id=consulta.id,
            descricao="Procedimentos de junho",
            created_at=datetime(2024, 6, 5, 10, 0, 0),
        )
        db.session.add(orcamento)
        db.session.flush()

        db.session.add(
            OrcamentoItem(
                consulta_id=consulta.id,
                orcamento_id=orcamento.id,
                clinica_id=clinic.id,
                descricao="Exames",
                valor=Decimal("150.00"),
            )
        )

        bloco = BlocoOrcamento(
            animal_id=animal.id,
            clinica_id=clinic.id,
            data_criacao=datetime(2024, 6, 10, 9, 0, 0),
            payment_status="pendente",
        )
        db.session.add(bloco)
        db.session.flush()

        db.session.add(
            OrcamentoItem(
                bloco_id=bloco.id,
                clinica_id=clinic.id,
                descricao="Cirurgia",
                valor=Decimal("900.00"),
            )
        )

        db.session.commit()

        return {
            "clinic_id": clinic.id,
            "animal_id": animal.id,
            "consulta_id": consulta.id,
            "bloco_id": bloco.id,
        }


def _login(client):
    return client.post(
        "/login",
        data={"email": "admin@example.com", "password": "senha123"},
        follow_redirects=True,
    )


def test_contabilidade_pagamentos_enforces_active_filters(app, clinic_setup):
    client = app.test_client()
    with client:
        login_resp = _login(client)
        assert login_resp.status_code == 200

        response = client.get("/contabilidade/pagamentos?mes=2024-07", follow_redirects=False)
        assert response.status_code == 302
        parsed = urlsplit(response.location)
        assert parsed.path == "/contabilidade/pagamentos"
        params = parse_qs(parsed.query)
        assert params.get("clinica_id") == [str(clinic_setup["clinic_id"])]
        assert params.get("mes") == ["2024-07"]

        final = client.get(response.headers["Location"])
        assert final.status_code == 200


def test_orcamentos_view_uses_selected_filters_in_accounting_link(app, clinic_setup):
    client = app.test_client()
    with client:
        _login(client)
        clinic_id = clinic_setup["clinic_id"]
        resp = client.get(f"/clinica/{clinic_id}/orcamentos?mes=2024-06")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        expected_href = f"/contabilidade/pagamentos?clinica_id={clinic_id}&mes=2024-06"
        assert expected_href.replace("&", "&amp;") in html


def test_dashboard_orcamentos_button_reflects_filters(app, clinic_setup):
    client = app.test_client()
    with client:
        _login(client)
        clinic_id = clinic_setup["clinic_id"]
        resp = client.get(f"/dashboard/orcamentos?scope=clinic&clinica_id={clinic_id}&mes=2024-08")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        expected_href = f"/contabilidade/pagamentos?clinica_id={clinic_id}&mes=2024-08"
        assert expected_href.replace("&", "&amp;") in html


def test_budget_widget_links_point_to_medical_pages(app, clinic_setup):
    client = app.test_client()
    with client:
        _login(client)
        clinic_id = clinic_setup["clinic_id"]
        resp = client.get(f"/contabilidade/pagamentos?clinica_id={clinic_id}&mes=2024-06")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        consulta_anchor = f"/consulta/{clinic_setup['animal_id']}?c={clinic_setup['consulta_id']}#orcamento"
        assert consulta_anchor in html
        pagamento_form = f"/consulta/{clinic_setup['consulta_id']}/pagar_orcamento"
        assert pagamento_form in html
        bloco_link = f"/bloco_orcamento/{clinic_setup['bloco_id']}/editar"
        assert bloco_link in html
        bloco_pagamento = f"/pagar_orcamento/{clinic_setup['bloco_id']}"
        assert bloco_pagamento in html


def test_accounting_home_recovers_when_notifications_table_missing(app, clinic_setup):
    client = app.test_client()
    with app.app_context():
        ClinicNotification.__table__.drop(bind=db.engine, checkfirst=True)
        inspector = inspect(db.engine)
        assert not inspector.has_table("clinic_notifications")

    with client:
        _login(client)
        response = client.get("/contabilidade")
        assert response.status_code == 200

    with app.app_context():
        assert inspect(db.engine).has_table("clinic_notifications")
