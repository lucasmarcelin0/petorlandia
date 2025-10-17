import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from app import app as flask_app, db
from models import RequestIdempotencyKey


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        flask_app.config['_debug_delay_calls'] = 0
    yield flask_app


def test_duplicate_submission_returns_cached_response(app):
    client = app.test_client()
    token = "test-token-123"

    resp1 = client.post(
        '/_debug/delay',
        data={'delay': 0.01, '_idempotency_key': token},
        headers={'X-Idempotency-Key': token},
    )
    assert resp1.status_code == 200
    assert resp1.get_json()['calls'] == 1

    resp2 = client.post(
        '/_debug/delay',
        data={'delay': 0.01, '_idempotency_key': token},
        headers={'X-Idempotency-Key': token},
    )
    assert resp2.status_code == 200
    assert resp2.headers.get('X-Idempotent-Replay') == '1'
    assert resp2.get_json()['calls'] == 1

    with app.app_context():
        records = RequestIdempotencyKey.query.filter_by(token=token).all()
        assert len(records) == 1
        assert records[0].response_code == 200


def test_form_field_only_token_is_respected(app):
    client = app.test_client()
    token = "token-without-header"

    resp1 = client.post('/_debug/delay', data={'delay': 0, '_idempotency_key': token})
    assert resp1.status_code == 200
    assert resp1.get_json()['calls'] == 1

    resp2 = client.post('/_debug/delay', data={'delay': 0, '_idempotency_key': token})
    assert resp2.status_code == 200
    assert resp2.headers.get('X-Idempotent-Replay') == '1'
    assert resp2.get_json()['calls'] == 1


def test_new_token_triggers_new_execution(app):
    client = app.test_client()

    resp1 = client.post('/_debug/delay', data={'delay': 0, '_idempotency_key': 'token-a'})
    assert resp1.status_code == 200
    assert resp1.get_json()['calls'] == 1

    resp2 = client.post('/_debug/delay', data={'delay': 0, '_idempotency_key': 'token-b'})
    assert resp2.status_code == 200
    assert resp2.get_json()['calls'] == 2
