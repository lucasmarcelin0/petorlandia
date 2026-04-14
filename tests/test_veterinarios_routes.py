import os
import sys
from datetime import datetime, time, timezone

import pytest

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import Animal, BlocoPrescricao, Clinica, Consulta, Prescricao, User, Veterinario, VetSchedule


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.session.remove()
            db.create_all()
        yield client
        with flask_app.app_context():
            db.session.remove()
            db.drop_all()


def test_veterinarios_listing_and_detail(client):
    with flask_app.app_context():
        user = User(name="Vet", email="vet@test", password_hash="x", worker="veterinario")
        vet = Veterinario(user=user, crmv="123")
        schedule = VetSchedule(veterinario=vet, dia_semana="Segunda", hora_inicio=time(9, 0), hora_fim=time(17, 0))
        db.session.add_all([user, vet, schedule])
        db.session.commit()
        vet_id = vet.id

    resp = client.get("/veterinarios")
    assert resp.status_code == 200
    assert b"Vet" in resp.data

    resp = client.get(f"/veterinario/{vet_id}")
    assert resp.status_code == 200
    assert b"CRMV" in resp.data
    assert b"123" in resp.data
    assert b"Segunda" in resp.data


def login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_veterinarian_activity_report_renders_compiled_data(client):
    with flask_app.app_context():
        admin = User(name="Admin", email="admin@test", password_hash="x", role="admin")
        tutor = User(name="Tutor", email="tutor@test", password_hash="x")
        vet_user = User(name="Vet Relatorio", email="vet-report@test", password_hash="x", worker="veterinario")
        clinic = Clinica(nome="Clinica Centro")
        vet = Veterinario(user=vet_user, crmv="999", clinica=clinic)
        db.session.add_all([admin, tutor, vet_user, clinic, vet])
        db.session.flush()
        animal = Animal(name="Rex", user_id=tutor.id, clinica=clinic)
        db.session.add(animal)
        db.session.flush()

        consulta = Consulta(
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            queixa_principal="Dermatite",
            status="finalizada",
            created_at=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
            finalizada_em=datetime(2026, 4, 10, 13, 0, tzinfo=timezone.utc),
        )
        bloco = BlocoPrescricao(
            animal_id=animal.id,
            clinica_id=clinic.id,
            saved_by_id=vet_user.id,
            data_criacao=datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc),
        )
        prescricao = Prescricao(
            bloco=bloco,
            animal_id=animal.id,
            medicamento="Cetoconazol",
        )
        db.session.add_all([consulta, bloco, prescricao])
        db.session.commit()
        admin_id = admin.id
        vet_id = vet.id

    login(client, admin_id)
    resp = client.get(
        f"/veterinario/{vet_id}/relatorio-atividades?start_date=2026-04-01&end_date=2026-04-30"
    )

    assert resp.status_code == 200
    assert b"Relat" in resp.data
    assert b"Vet Relatorio" in resp.data
    assert b"Dermatite" in resp.data
    assert b"Cetoconazol" in resp.data
