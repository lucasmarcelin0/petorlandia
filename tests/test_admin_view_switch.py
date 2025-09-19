import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from models import User, Animal, Veterinario, Clinica


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def setup_data():
    clinic = Clinica(id=1, nome='Clinica')
    tutor = User(id=1, name='Tutor', email='tutor@test')
    tutor.set_password('x')
    admin = User(id=2, name='Admin', email='admin@test', role='admin')
    admin.set_password('x')
    vet_user = User(id=3, name='Vet', email='vet@test', worker='veterinario')
    vet_user.set_password('x')
    animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
    vet = Veterinario(id=1, user_id=vet_user.id, clinica_id=clinic.id, crmv='123')
    db.session.add_all([clinic, tutor, admin, vet_user, animal, vet])
    db.session.commit()
    return admin


def test_admin_can_switch_views(client, monkeypatch):
    with flask_app.app_context():
        admin = setup_data()
        admin_id = admin.id
    fake_admin = type(
        'U',
        (),
        {
            'id': admin_id,
            'role': 'admin',
            'worker': None,
            'is_authenticated': True,
            'clinica_id': None,
            'name': 'Admin',
        },
    )()
    login(monkeypatch, fake_admin)
    resp = client.get('/appointments?view_as=veterinario')
    assert resp.status_code == 200
    resp = client.get('/appointments?view_as=colaborador')
    assert resp.status_code == 200
    resp = client.get('/appointments?view_as=tutor')
    assert resp.status_code == 200
    resp = client.get('/appointments/manage')
    assert b'view_as=colaborador' in resp.data
    assert b'view_as=veterinario' in resp.data
    assert b'view_as=tutor' in resp.data


def test_non_admin_view_as_redirects(client, monkeypatch):
    with flask_app.app_context():
        setup_data()
        collaborator = User(
            id=10,
            name='Colab',
            email='colab@test',
            worker='colaborador',
            clinica_id=1,
        )
        collaborator.set_password('x')
        db.session.add(collaborator)
        db.session.commit()
        tutor = User.query.filter_by(email='tutor@test').first()
        tutor_id = tutor.id
        collab_id = collaborator.id

    fake_collaborator = type(
        'U',
        (),
        {
            'id': collab_id,
            'worker': 'colaborador',
            'role': 'adotante',
            'is_authenticated': True,
            'clinica_id': 1,
        },
    )()
    login(monkeypatch, fake_collaborator)
    resp = client.get('/appointments?view_as=veterinario')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/appointments')

    fake_tutor = type(
        'U',
        (),
        {
            'id': tutor_id,
            'worker': None,
            'role': 'adotante',
            'is_authenticated': True,
            'clinica_id': None,
        },
    )()
    login(monkeypatch, fake_tutor)
    resp = client.get('/appointments?view_as=veterinario')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/appointments')
