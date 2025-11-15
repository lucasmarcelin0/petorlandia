import pytest
import flask_login.utils as login_utils
from datetime import time

from app import app as flask_app, db
from models import User, Veterinario, VetSchedule, Clinica


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_schedule_days_order(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        vet_user = User(id=1, name='Vet', email='vet@test', worker='veterinario')
        vet_user.set_password('x')
        vet = Veterinario(id=1, user_id=vet_user.id, crmv='123', clinica_id=clinic.id)
        s_wed = VetSchedule(
            id=1,
            veterinario_id=vet.id,
            dia_semana='Quarta',
            hora_inicio=time(9, 0),
            hora_fim=time(10, 0),
        )
        s_mon = VetSchedule(
            id=2,
            veterinario_id=vet.id,
            dia_semana='Segunda',
            hora_inicio=time(9, 0),
            hora_fim=time(10, 0),
        )
        db.session.add_all([clinic, vet_user, vet, s_wed, s_mon])
        db.session.commit()
        vet_id = vet.id
        vet_user_id = vet_user.id
        clinic_id = clinic.id

    fake_vet = type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet',
        'is_authenticated': True,
        'veterinario': type('V', (), {
            'id': vet_id,
            'user': type('WU', (), {'name': 'Vet'})(),
            'clinica_id': clinic_id,
        })(),
    })()

    login(monkeypatch, fake_vet)
    resp = client.get('/appointments')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert html.index('Segunda') < html.index('Quarta')

