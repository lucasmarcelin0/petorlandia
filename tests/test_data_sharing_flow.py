import os
import sys
from datetime import datetime, timedelta

import pytest

os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import (
    Animal,
    Clinica,
    DataShareAccess,
    DataShareLog,
    DataSharePartyType,
    DataShareRequest,
    User,
)
from services import find_active_share


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils

    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


@pytest.fixture(autouse=True)
def reset_db(app):
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def mute_notifications(monkeypatch):
    monkeypatch.setattr('app.mail.send', lambda *args, **kwargs: None)
    monkeypatch.setattr('app._send_share_sms', lambda *args, **kwargs: False)


def seed_entities():
    clinic_a = Clinica(nome='Origem')
    clinic_b = Clinica(nome='Destino')
    db.session.add_all([clinic_a, clinic_b])
    db.session.commit()
    tutor = User(name='Tutor', email='tutor@example.com', password_hash='x', clinica_id=clinic_a.id)
    staff = User(name='Staff', email='staff@example.com', password_hash='y', worker='colaborador', clinica_id=clinic_b.id)
    db.session.add_all([tutor, staff])
    db.session.commit()
    animal = Animal(name='Rex', age='2 anos', status='ativo', user_id=tutor.id, clinica_id=clinic_a.id)
    db.session.add(animal)
    db.session.commit()
    return tutor, staff, animal, clinic_b


def test_tutor_can_approve_and_deny_requests(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        tutor, staff, animal, _ = seed_entities()
        login(monkeypatch, staff)
        resp = client.post('/api/shares', json={'tutor_id': tutor.id, 'animal_id': animal.id, 'message': 'Acesso temporário'})
        assert resp.status_code == 201
        share_request = DataShareRequest.query.first()

        login(monkeypatch, tutor)
        approve_resp = client.post(f'/api/shares/{share_request.id}/approve', json={'expires_in_days': 2})
        assert approve_resp.status_code == 200
        share_request = DataShareRequest.query.get(share_request.id)
        assert share_request.status == 'approved'
        access = DataShareAccess.query.first()
        assert access is not None
        assert access.granted_by == tutor.id
        access.revoked_at = datetime.utcnow()
        db.session.commit()

        login(monkeypatch, staff)
        resp = client.post('/api/shares', json={'tutor_id': tutor.id, 'message': 'Outro acesso'})
        assert resp.status_code == 201
        pending = DataShareRequest.query.filter_by(status='pending').first()
        login(monkeypatch, tutor)
        deny_resp = client.post(f'/api/shares/{pending.id}/deny', json={'reason': 'Indisponível'})
        assert deny_resp.status_code == 200
        updated = DataShareRequest.query.get(pending.id)
        assert updated.status == 'denied'
        assert updated.denial_reason == 'Indisponível'


def test_expired_shares_are_not_active(monkeypatch, app):
    with app.app_context():
        tutor, staff, animal, clinic = seed_entities()
        share = DataShareAccess(
            user_id=tutor.id,
            animal_id=animal.id,
            source_clinic_id=tutor.clinica_id,
            granted_to_type=DataSharePartyType.clinic,
            granted_to_id=clinic.id,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        db.session.add(share)
        db.session.commit()
        active = find_active_share([(DataSharePartyType.clinic, clinic.id)], user_id=tutor.id, animal_id=animal.id)
        assert active is None


def test_share_grant_creates_audit_log(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        tutor, staff, animal, _ = seed_entities()
        login(monkeypatch, staff)
        resp = client.post('/api/shares', json={'tutor_id': tutor.id, 'animal_id': animal.id})
        assert resp.status_code == 201
        request = DataShareRequest.query.first()

        login(monkeypatch, tutor)
        approve_resp = client.post(f'/api/shares/{request.id}/approve')
        assert approve_resp.status_code == 200
        logs = DataShareLog.query.filter_by(event_type='share_granted').all()
        assert logs
        assert logs[0].resource_type in {'user', 'animal'}
