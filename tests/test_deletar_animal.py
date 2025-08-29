import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, db
from models import User, Animal


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
    )
    yield flask_app


def test_deletar_animal_json(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(id=1, name='Admin', email='admin@test', role='admin', worker='veterinario')
        admin.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=admin.id)
        db.session.add_all([admin, animal])
        db.session.commit()
        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

    resp = client.post('/animal/1/deletar', headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    assert resp.json['deleted'] is True

    with app.app_context():
        assert Animal.query.get(1).removido_em is not None
