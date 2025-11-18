import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

from app import app as flask_app, db
from models import DataShareAccess, DataShareLog, DataSharePartyType


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
    )
    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    yield flask_app


def reset_db():
    db.session.remove()
    db.engine.dispose()
    db.drop_all()
    db.create_all()


def test_guard_blocks_missing_required_columns(app):
    with app.app_context():
        reset_db()
        share = DataShareAccess()
        db.session.add(share)

        with pytest.raises(ValueError) as excinfo:
            db.session.flush()

        message = str(excinfo.value)
        assert "DataShareAccess" in message
        assert "granted_to_type" in message
        assert "granted_to_id" in message


def test_guard_allows_complete_rows(app):
    with app.app_context():
        reset_db()
        share = DataShareAccess(granted_to_type=DataSharePartyType.clinic, granted_to_id=1)
        db.session.add(share)
        db.session.flush()

        assert share.id is not None


def test_guard_allows_relationship_backfills(app):
    with app.app_context():
        reset_db()
        share = DataShareAccess(granted_to_type=DataSharePartyType.clinic, granted_to_id=1)
        db.session.add(share)
        db.session.flush()

        log = DataShareLog(access=share, event_type="read", resource_type="user")
        db.session.add(log)
        db.session.flush()

        assert log.access_id == share.id
