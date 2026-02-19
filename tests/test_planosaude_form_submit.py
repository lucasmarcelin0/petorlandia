import os
import flask_login.utils as login_utils

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import app as app_module
from app import app as flask_app, db
from models import Animal, HealthPlan, User


def login(monkeypatch, user_id):
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(user_id))


class _FakePreapproval:
    def create(self, _payload):
        return {
            "status": 201,
            "response": {"init_point": "https://pagamentos.test/checkout"},
        }


class _FakeMercadoPagoSdk:
    def __init__(self, _token):
        pass

    def preapproval(self):
        return _FakePreapproval()


def test_planosaude_animal_post_delegates_to_checkout(monkeypatch):
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")

    with flask_app.app_context():
        db.drop_all()
        db.create_all()

        tutor = User(id=1, name="Tutor", email="tutor@example.com", cpf="12345678901")
        tutor.set_password("x")
        animal = Animal(id=1, name="Rex", user_id=tutor.id)
        plan = HealthPlan(id=1, name="Plano Essencial", description="Cobertura básica", price=59.90)
        db.session.add_all([tutor, animal, plan])
        db.session.commit()

    login(monkeypatch, 1)
    monkeypatch.setattr(app_module.mercadopago, 'SDK', _FakeMercadoPagoSdk)

    with flask_app.test_client() as client:
        response = client.post(
            '/animal/1/planosaude',
            data={
                'plan_id': '1',
                'tutor_document': '12345678901',
                'animal_document': 'CHIP-001',
                'contract_reference': 'CT-2026-0001',
                'document_links': '',
                'extra_notes': 'Teste de contratação',
                'consent': 'y',
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers['Location'] == 'https://pagamentos.test/checkout'
