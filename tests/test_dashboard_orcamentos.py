import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from app import app as flask_app, db
from models import (
    Animal,
    Clinica,
    Consulta,
    Orcamento,
    OrcamentoItem,
    Payment,
    PaymentMethod,
    PaymentStatus,
    User,
)


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def _create_consulta_with_orcamento(*, clinic, vet, tutor, animal_name, valor):
    animal = Animal(name=animal_name, owner=tutor, clinica=clinic)
    db.session.add(animal)
    db.session.flush()

    consulta = Consulta(
        animal_id=animal.id,
        created_by=vet.id,
        clinica_id=clinic.id,
        status="in_progress",
    )
    db.session.add(consulta)
    db.session.flush()

    orcamento = Orcamento(
        clinica_id=clinic.id,
        consulta=consulta,
        descricao=f"Orçamento {animal_name}",
    )
    db.session.add(orcamento)
    db.session.flush()

    item = OrcamentoItem(
        consulta=consulta,
        orcamento=orcamento,
        descricao="Consulta",
        valor=valor,
        clinica=clinic,
    )
    db.session.add(item)

    pagamento = Payment(
        method=PaymentMethod.PIX,
        status=PaymentStatus.COMPLETED,
        external_reference=f"consulta-{consulta.id}",
        user_id=tutor.id,
        amount=valor,
    )
    db.session.add(pagamento)

    return consulta


def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_dashboard_orcamentos_restrito_a_clinica_do_usuario(app):
    with app.app_context():
        db.drop_all()
        db.create_all()

        clinic_a = Clinica(nome="Clínica A")
        clinic_b = Clinica(nome="Clínica B")
        db.session.add_all([clinic_a, clinic_b])
        db.session.flush()
        clinic_b_id = clinic_b.id

        vet_a = User(name="Vet A", email="vet_a@example.com", clinica_id=clinic_a.id)
        vet_a.set_password("senha")
        tutor_a = User(name="Tutor A", email="tutor_a@example.com")
        tutor_a.set_password("123")

        vet_b = User(name="Vet B", email="vet_b@example.com", clinica_id=clinic_b.id)
        vet_b.set_password("senha")
        tutor_b = User(name="Tutor B", email="tutor_b@example.com")
        tutor_b.set_password("123")

        db.session.add_all([vet_a, tutor_a, vet_b, tutor_b])
        db.session.flush()

        _create_consulta_with_orcamento(
            clinic=clinic_a,
            vet=vet_a,
            tutor=tutor_a,
            animal_name="Rex",
            valor=50,
        )
        _create_consulta_with_orcamento(
            clinic=clinic_b,
            vet=vet_b,
            tutor=tutor_b,
            animal_name="Bolt",
            valor=75,
        )

        db.session.commit()

    client = app.test_client()
    with client:
        _login(client, "vet_a@example.com", "senha")

        resp = client.get("/dashboard/orcamentos")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Tutor A" in html
        assert "Rex" in html
        assert "Tutor B" not in html
        assert "Bolt" not in html
        assert "Clínica A" in html

        resp_forbidden = client.get("/dashboard/orcamentos?scope=all")
        assert resp_forbidden.status_code == 403

    with app.app_context():
        db.drop_all()


def test_dashboard_orcamentos_admin_pode_ver_todas_clinicas(app):
    clinic_b_id = None

    with app.app_context():
        db.drop_all()
        db.create_all()

        clinic_a = Clinica(nome="Clínica A")
        clinic_b = Clinica(nome="Clínica B")
        db.session.add_all([clinic_a, clinic_b])
        db.session.flush()
        clinic_b_id = clinic_b.id

        admin = User(name="Admin", email="admin@example.com", role="admin")
        admin.set_password("senha")
        tutor_a = User(name="Tutor A", email="tutor_a@example.com")
        tutor_a.set_password("123")
        tutor_b = User(name="Tutor B", email="tutor_b@example.com")
        tutor_b.set_password("123")
        db.session.add_all([admin, tutor_a, tutor_b])
        db.session.flush()

        _create_consulta_with_orcamento(
            clinic=clinic_a,
            vet=admin,
            tutor=tutor_a,
            animal_name="Rex",
            valor=60,
        )
        _create_consulta_with_orcamento(
            clinic=clinic_b,
            vet=admin,
            tutor=tutor_b,
            animal_name="Bolt",
            valor=80,
        )

        db.session.commit()

    client = app.test_client()
    with client:
        _login(client, "admin@example.com", "senha")

        resp_global = client.get("/dashboard/orcamentos?scope=all")
        assert resp_global.status_code == 200
        html_global = resp_global.get_data(as_text=True)
        assert "Tutor A" in html_global
        assert "Tutor B" in html_global
        assert "Clínica A" in html_global
        assert "Clínica B" in html_global

        resp_clinic_b = client.get(
            f"/dashboard/orcamentos?scope=clinic&clinica_id={clinic_b_id}"
        )
        assert resp_clinic_b.status_code == 200
        html_clinic_b = resp_clinic_b.get_data(as_text=True)
        assert "Tutor B" in html_clinic_b
        assert "Tutor A" not in html_clinic_b

    with app.app_context():
        db.drop_all()
