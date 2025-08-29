import pytest
from datetime import time
from app import app as flask_app, db
from models import User, Clinica, Veterinario, VetSchedule


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_owner_manage_employees(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        owner = User(name="Owner", email="owner@example.com", password_hash="x")
        clinica = Clinica(nome="Clinica", owner=owner)
        vet_user = User(name="Vet", email="vet@example.com", password_hash="x")
        vet = Veterinario(user=vet_user, crmv="123", clinica=clinica)
        db.session.add_all([owner, clinica, vet_user, vet])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: owner)

        resp = client.post(
            f'/clinica/{clinica.id}',
            data={
                f'schedule_{vet.id}-veterinario_id': str(vet.id),
                f'schedule_{vet.id}-dias_semana': ['Segunda'],
                f'schedule_{vet.id}-hora_inicio': '09:00',
                f'schedule_{vet.id}-hora_fim': '10:00',
                f'schedule_{vet.id}-intervalo_inicio': '',
                f'schedule_{vet.id}-intervalo_fim': '',
                f'schedule_{vet.id}-submit': 'Salvar',
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert VetSchedule.query.filter_by(veterinario_id=vet.id).count() == 1

        schedule = VetSchedule.query.filter_by(veterinario_id=vet.id).first()
        resp = client.post(
            f'/clinica/{clinica.id}/veterinario/{vet.id}/schedule/{schedule.id}/delete',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert VetSchedule.query.filter_by(veterinario_id=vet.id).count() == 0

        resp = client.post(
            f'/clinica/{clinica.id}/veterinario/{vet.id}/remove',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert vet.clinica_id is None


def test_schedule_grouped_by_day(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        owner = User(name="Owner2", email="owner2@example.com", password_hash="x")
        clinica = Clinica(nome="Clinica2", owner=owner)
        vet_user = User(name="Vet2", email="vet2@example.com", password_hash="x")
        vet = Veterinario(user=vet_user, crmv="123", clinica=clinica)
        s1 = VetSchedule(veterinario=vet, dia_semana="Segunda", hora_inicio=time(9), hora_fim=time(10))
        s2 = VetSchedule(veterinario=vet, dia_semana="Segunda", hora_inicio=time(10), hora_fim=time(11))
        db.session.add_all([owner, clinica, vet_user, vet, s1, s2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: owner)

        resp = client.get(f'/clinica/{clinica.id}')
        assert resp.status_code == 200
        data = resp.data.decode()
        assert data.count("<li>Segunda:") == 1
        assert "Segunda: 09:00 - 10:00, 10:00 - 11:00" in data
