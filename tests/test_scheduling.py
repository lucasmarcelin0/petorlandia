import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from flask_login import login_required, current_user
import flask_login.utils as login_utils

from datetime import time
from app import app as flask_app, db
from models import HealthSubscription, VetSchedule, User, Veterinario
from helpers import has_schedule_conflict


@flask_app.route('/schedule/<int:slot_id>', methods=['POST'])
@login_required
def schedule(slot_id):
    sub = (
        HealthSubscription.query
        .filter_by(user_id=current_user.id, active=True)
        .first()
    )
    if not sub:
        return 'no active subscription', 400

    slot = VetSchedule.query.get(slot_id)
    if getattr(slot, 'booked', False):
        return 'slot unavailable', 409

    slot.booked = True
    return 'scheduled', 200


@pytest.fixture
def client(monkeypatch):
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:'
    )
    class FakeUser:
        id = 1
        is_authenticated = True
    monkeypatch.setattr(login_utils, '_get_user', lambda: FakeUser())
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    with flask_app.test_client() as client:
        yield client
    with flask_app.app_context():
        db.session.remove()


def test_schedule_requires_active_subscription(client, monkeypatch):
    class FakeQuery:
        def filter_by(self, **kw):
            class R:
                def first(self_inner):
                    return None
            return R()
    with flask_app.app_context():
        monkeypatch.setattr(HealthSubscription, 'query', FakeQuery())
    resp = client.post('/schedule/1')
    assert resp.status_code == 400


def test_successful_scheduling(client, monkeypatch):
    class Sub:
        pass
    class HSQuery:
        def filter_by(self, **kw):
            class R:
                def first(self_inner):
                    return Sub()
            return R()
    class Slot:
        def __init__(self):
            self.booked = False
    slot = Slot()
    class SlotQuery:
        def get(self, _):
            return slot
    with flask_app.app_context():
        monkeypatch.setattr(HealthSubscription, 'query', HSQuery())
        monkeypatch.setattr(VetSchedule, 'query', SlotQuery())
    resp = client.post('/schedule/1')
    assert resp.status_code == 200
    assert slot.booked is True


def test_conflict_when_slot_booked(client, monkeypatch):
    class Sub:
        pass
    class HSQuery:
        def filter_by(self, **kw):
            class R:
                def first(self_inner):
                    return Sub()
            return R()
    class Slot:
        def __init__(self):
            self.booked = True
    class SlotQuery:
        def get(self, _):
            return Slot()
    with flask_app.app_context():
        monkeypatch.setattr(HealthSubscription, 'query', HSQuery())
        monkeypatch.setattr(VetSchedule, 'query', SlotQuery())
    resp = client.post('/schedule/1')
    assert resp.status_code == 409


def test_has_schedule_conflict(monkeypatch):
    with flask_app.app_context():
        db.create_all()
        user = User(name="Vet", email="v@example.com", password_hash="x", worker='veterinario')
        vet = Veterinario(user=user, crmv="1")
        db.session.add_all([user, vet])
        db.session.commit()
        slot = VetSchedule(
            veterinario_id=vet.id,
            dia_semana="Segunda",
            hora_inicio=time(9, 0),
            hora_fim=time(12, 0),
        )
        db.session.add(slot)
        db.session.commit()
        assert has_schedule_conflict(vet.id, "Segunda", time(11, 0), time(13, 0)) is True
        assert has_schedule_conflict(vet.id, "Segunda", time(12, 0), time(14, 0)) is False
