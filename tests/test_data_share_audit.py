import os
import sys
from datetime import datetime

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from werkzeug.exceptions import NotFound

from app import app as flask_app, db, get_user_or_404, get_animal_or_404
from models import User, Clinica, Animal, DataShareAccess, DataSharePartyType, DataShareLog


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils

    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def setup_entities():
    db.drop_all()
    db.create_all()
    clinic_a = Clinica(nome="Alpha")
    clinic_b = Clinica(nome="Beta")
    db.session.add_all([clinic_a, clinic_b])
    db.session.commit()
    tutor = User(name="Tutor", email="tutor@example.com", password_hash="x", clinica_id=clinic_a.id)
    viewer = User(name="Viewer", email="viewer@example.com", password_hash="y", clinica_id=clinic_b.id)
    db.session.add_all([tutor, viewer])
    db.session.commit()
    return clinic_a, clinic_b, tutor, viewer


def test_shared_user_access_logs_event(monkeypatch, app):
    with app.app_context():
        clinic_a, clinic_b, tutor, viewer = setup_entities()
        share = DataShareAccess(
            user_id=tutor.id,
            source_clinic_id=clinic_a.id,
            granted_to_type=DataSharePartyType.clinic,
            granted_to_id=clinic_b.id,
            granted_by=viewer.id,
            granted_via='test',
        )
        db.session.add(share)
        db.session.commit()

        login(monkeypatch, viewer)
        with app.test_request_context('/auditoria'):
            loaded = get_user_or_404(tutor.id)
            assert loaded.id == tutor.id

        logs = DataShareLog.query.filter_by(resource_type='user').all()
        assert len(logs) == 1
        assert logs[0].access_id == share.id
        assert logs[0].actor_id == viewer.id


def test_revoked_share_denies_access(monkeypatch, app):
    with app.app_context():
        clinic_a, clinic_b, tutor, viewer = setup_entities()
        share = DataShareAccess(
            user_id=tutor.id,
            source_clinic_id=clinic_a.id,
            granted_to_type=DataSharePartyType.clinic,
            granted_to_id=clinic_b.id,
            revoked_at=datetime.utcnow(),
        )
        db.session.add(share)
        db.session.commit()

        login(monkeypatch, viewer)
        with app.test_request_context('/auditoria'):
            with pytest.raises(NotFound):
                get_user_or_404(tutor.id)

        assert DataShareLog.query.count() == 0


def test_shared_animal_access_logs(monkeypatch, app):
    with app.app_context():
        clinic_a, clinic_b, tutor, viewer = setup_entities()
        animal = Animal(name="Rex", age="2", status="ativo", user_id=tutor.id, clinica_id=clinic_a.id)
        db.session.add(animal)
        db.session.commit()
        share = DataShareAccess(
            user_id=tutor.id,
            animal_id=animal.id,
            source_clinic_id=clinic_a.id,
            granted_to_type=DataSharePartyType.clinic,
            granted_to_id=clinic_b.id,
        )
        db.session.add(share)
        db.session.commit()

        login(monkeypatch, viewer)
        with app.test_request_context('/auditoria'):
            loaded = get_animal_or_404(animal.id)
            assert loaded.id == animal.id

        logs = DataShareLog.query.filter_by(resource_type='animal').all()
        assert len(logs) == 1
        assert logs[0].access_id == share.id
