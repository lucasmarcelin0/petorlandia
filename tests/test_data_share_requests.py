import os
import sys
from datetime import datetime, timedelta

os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from werkzeug.exceptions import NotFound

from app import app as flask_app, db, get_user_or_404
from models import (
    Animal,
    Clinica,
    DataShareAccess,
    DataSharePartyType,
    DataShareRequest,
    DataShareLog,
    User,
)


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with flask_app.app_context():
        db.session.remove()
        db.engines.pop(flask_app, None)
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils

    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def _setup_entities():
    db.drop_all()
    db.create_all()
    clinic = Clinica(nome="Clínica Alfa", email="alfa@example.com")
    tutor = User(name="Tutor", email="tutor@example.com", password_hash="x")
    collaborator = User(name="Colab", email="colab@example.com", password_hash="y", worker='colaborador')
    collaborator.clinica = clinic
    tutor.clinica = clinic
    db.session.add_all([clinic, tutor, collaborator])
    db.session.commit()
    animal = Animal(name="Rex", status="ativo", user_id=tutor.id, clinica=clinic)
    db.session.add(animal)
    db.session.commit()
    return clinic, tutor, collaborator, animal


def test_clinic_requests_and_tutor_approves(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinic, tutor, collaborator, animal = _setup_entities()
        login(monkeypatch, collaborator)
        resp = client.post(
            '/api/shares',
            json={'tutor_id': tutor.id, 'clinic_id': clinic.id, 'animal_id': animal.id, 'reason': 'Emergência'},
        )
        assert resp.status_code == 201
        share_request = DataShareRequest.query.one()
        assert share_request.status == 'pending'
        assert share_request.tokens

        login(monkeypatch, tutor)
        resp_decision = client.post(
            f'/api/shares/{share_request.id}/decision',
            json={'action': 'approve'},
        )
        assert resp_decision.status_code == 200
        db.session.refresh(share_request)
        assert share_request.status == 'approved'
        assert share_request.granted_access is not None
        assert share_request.granted_access.granted_by == tutor.id
        assert share_request.granted_access.expires_at is not None
        log = DataShareLog.query.filter_by(event_type='share_granted').one()
        assert log.access_id == share_request.granted_access.id


def test_tutor_can_deny_request(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinic, tutor, collaborator, animal = _setup_entities()
        login(monkeypatch, collaborator)
        resp = client.post('/api/shares', json={'tutor_id': tutor.id, 'clinic_id': clinic.id})
        assert resp.status_code == 201
        share_request = DataShareRequest.query.one()

        login(monkeypatch, tutor)
        resp_decision = client.post(
            f'/api/shares/{share_request.id}/decision',
            json={'action': 'deny'},
        )
        assert resp_decision.status_code == 200
        db.session.refresh(share_request)
        assert share_request.status == 'denied'
        assert DataShareAccess.query.count() == 0


def test_expired_share_blocks_access(monkeypatch, app):
    with app.app_context():
        db.create_all()
        clinic = Clinica(nome="Clínica Beta")
        other = Clinica(nome="Clínica Gama")
        tutor = User(name="Tutor", email="t2@example.com", password_hash="x", clinica=clinic)
        viewer = User(name="Viewer", email="viewer@example.com", password_hash="y", worker='colaborador', clinica=other)
        db.session.add_all([clinic, other, tutor, viewer])
        db.session.commit()
        share = DataShareAccess(
            user_id=tutor.id,
            source_clinic_id=clinic.id,
            granted_to_type=DataSharePartyType.clinic,
            granted_to_id=other.id,
            granted_by=tutor.id,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        db.session.add(share)
        db.session.commit()

        login(monkeypatch, viewer)
        with app.test_request_context('/dados'):
            with pytest.raises(NotFound):
                get_user_or_404(tutor.id, viewer=viewer)
