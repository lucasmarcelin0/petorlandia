import os
import sys
import re
from datetime import time as dtime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils

from app import app as flask_app, db
from models import User, Clinica, Veterinario, VetSchedule


class FakeVetUser:
    def __init__(self, user, vet):
        self.id = user.id
        self.name = user.name
        self.role = user.role
        self.worker = user.worker
        self.email = user.email
        self.clinica_id = user.clinica_id
        vet_user = SimpleNamespace(name=vet.user.name if vet.user else None)
        self.veterinario = SimpleNamespace(
            id=vet.id,
            clinica_id=vet.clinica_id,
            user=vet_user,
        )

    @property
    def is_authenticated(self):
        return True

    def get_id(self):
        return str(self.id)


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    flask_app.jinja_env.globals['csrf_token'] = lambda: ''
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.session.remove()
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def create_veterinarians():
    clinic = Clinica(nome="Pet Clinic")
    main_user = User(
        name="Main Vet",
        email="main@example.com",
        password_hash="x",
        worker='veterinario',
        role='veterinario',
        clinica=clinic,
    )
    other_user = User(
        name="Other Vet",
        email="other@example.com",
        password_hash="x",
        worker='veterinario',
        role='veterinario',
        clinica=clinic,
    )
    main_vet = Veterinario(user=main_user, crmv="123", clinica=clinic)
    other_vet = Veterinario(user=other_user, crmv="456", clinica=clinic)
    db.session.add_all([clinic, main_user, other_user, main_vet, other_vet])
    db.session.commit()
    return main_user, main_vet, other_vet


def test_veterinarian_sees_only_self_in_schedule_choices(client, monkeypatch):
    with flask_app.app_context():
        main_user, main_vet, other_vet = create_veterinarians()
        fake_user = FakeVetUser(main_user, main_vet)
        main_vet_id = main_vet.id
        other_vet_id = other_vet.id
    login(monkeypatch, fake_user)
    resp = client.get('/appointments')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    match = re.search(r'id="schedule-veterinario_id"[^<]*>(.*?)</select>', html, re.DOTALL)
    assert match is not None
    select_html = match.group(0)
    assert f'value="{main_vet_id}"' in select_html
    assert f'value="{other_vet_id}"' not in select_html


def test_veterinarian_cannot_create_schedule_for_other(client, monkeypatch):
    with flask_app.app_context():
        main_user, main_vet, other_vet = create_veterinarians()
        fake_user = FakeVetUser(main_user, main_vet)
        main_vet_id = main_vet.id
        other_vet_id = other_vet.id
    login(monkeypatch, fake_user)
    resp = client.post(
        '/appointments',
        data={
            'schedule-veterinario_id': str(other_vet_id),
            'schedule-dias_semana': ['Segunda'],
            'schedule-hora_inicio': '09:00',
            'schedule-hora_fim': '10:00',
            'schedule-intervalo_inicio': '',
            'schedule-intervalo_fim': '',
            'schedule-submit': 'Salvar',
        },
    )
    assert resp.status_code == 403
    with flask_app.app_context():
        assert VetSchedule.query.count() == 0


def test_veterinarian_cannot_reassign_existing_schedule(client, monkeypatch):
    with flask_app.app_context():
        main_user, main_vet, other_vet = create_veterinarians()
        fake_user = FakeVetUser(main_user, main_vet)
        main_vet_id = main_vet.id
        other_vet_id = other_vet.id
        horario = VetSchedule(
            veterinario_id=main_vet.id,
            dia_semana='Segunda',
            hora_inicio=dtime(9, 0),
            hora_fim=dtime(10, 0),
        )
        db.session.add(horario)
        db.session.commit()
        horario_id = horario.id
    login(monkeypatch, fake_user)
    resp = client.post(
        f'/appointments/{main_vet_id}/schedule/{horario_id}/edit',
        data={
            'schedule-veterinario_id': str(other_vet_id),
            'schedule-dias_semana': ['Segunda'],
            'schedule-hora_inicio': '09:00',
            'schedule-hora_fim': '10:00',
            'schedule-intervalo_inicio': '',
            'schedule-intervalo_fim': '',
            'schedule-submit': 'Salvar',
        },
    )
    assert resp.status_code == 403
    with flask_app.app_context():
        horario = VetSchedule.query.get(horario_id)
        assert horario.veterinario_id == main_vet_id


def test_veterinarian_cannot_delete_other_vet_schedule(client, monkeypatch):
    with flask_app.app_context():
        main_user, main_vet, other_vet = create_veterinarians()
        fake_user = FakeVetUser(main_user, main_vet)
        main_vet_id = main_vet.id
        other_schedule = VetSchedule(
            veterinario_id=other_vet.id,
            dia_semana='Terça',
            hora_inicio=dtime(9, 0),
            hora_fim=dtime(10, 0),
        )
        db.session.add(other_schedule)
        db.session.commit()
        other_schedule_id = other_schedule.id
    login(monkeypatch, fake_user)
    resp = client.post(f'/appointments/{main_vet_id}/schedule/{other_schedule_id}/delete')
    assert resp.status_code == 403
    with flask_app.app_context():
        assert VetSchedule.query.get(other_schedule_id) is not None
