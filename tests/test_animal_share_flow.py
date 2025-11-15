import os
os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

import pytest
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db
from models import User, Clinica, Animal, Veterinario, AnimalShare, AnimalShareEvent


@pytest.fixture
def app(monkeypatch):
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, MAIL_SUPPRESS_SEND=True)
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def create_basic_entities():
    clinic_a = Clinica(nome='Clínica A')
    clinic_b = Clinica(nome='Clínica B')
    tutor = User(name='Tutor', email='tutor@example.com', password_hash='x', role='adotante', clinica=clinic_b)
    tutor.phone = '+5511999999999'
    animal = Animal(name='Rex', owner=tutor, clinica=clinic_b)
    vet_user = User(name='Vet', email='vet@example.com', password_hash='x', worker='veterinario', clinica=clinic_a)
    vet_profile = Veterinario(user=vet_user, crmv='123', clinica=clinic_a)
    db.session.add_all([clinic_a, clinic_b, tutor, animal, vet_user, vet_profile])
    db.session.commit()
    return tutor, animal, vet_user, clinic_a


def test_clinic_requests_and_tutor_approves(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        tutor, animal, vet_user, _ = create_basic_entities()
        login(monkeypatch, vet_user)
        resp = client.post('/api/shares', json={'animal_id': animal.id, 'reason': 'Avaliar histórico', 'duration_days': 5})
        assert resp.status_code == 201
        share = AnimalShare.query.first()
        assert share.status == 'pending'
        assert share.token is not None

        login(monkeypatch, tutor)
        resp = client.post(f"/api/shares/{share.token.token}/confirm", json={'decision': 'approve'})
        assert resp.status_code == 200
        share = AnimalShare.query.first()
        assert share.status == 'approved'
        assert share.granted_by_id == tutor.id
        assert share.expires_at is not None
        events = [event.event for event in AnimalShareEvent.query.order_by(AnimalShareEvent.id).all()]
        assert events == ['requested', 'approved']


def test_tutor_can_deny_share(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        tutor, animal, vet_user, _ = create_basic_entities()
        login(monkeypatch, vet_user)
        client.post('/api/shares', json={'animal_id': animal.id})
        share = AnimalShare.query.first()
        assert share.status == 'pending'
        login(monkeypatch, tutor)
        resp = client.post(f"/api/shares/{share.token.token}/confirm", json={'decision': 'deny'})
        assert resp.status_code == 200
        share = AnimalShare.query.first()
        assert share.status == 'denied'
        assert share.expires_at is None
        events = [event.event for event in AnimalShareEvent.query.order_by(AnimalShareEvent.id).all()]
        assert events == ['requested', 'denied']


def test_share_auto_expires_and_is_logged(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        tutor, animal, vet_user, clinic = create_basic_entities()
        expired_share = AnimalShare(
            animal_id=animal.id,
            tutor_id=tutor.id,
            clinica_id=clinic.id,
            requested_by_id=vet_user.id,
            status='approved',
            expires_at=datetime.utcnow() - timedelta(days=1)
        )
        db.session.add(expired_share)
        db.session.commit()
        login(monkeypatch, vet_user)
        resp = client.get('/api/shares')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['active'] == []
        share = AnimalShare.query.first()
        assert share.status == 'expired'
        events = [event.event for event in AnimalShareEvent.query.order_by(AnimalShareEvent.id).all()]
        assert 'expired' in events
