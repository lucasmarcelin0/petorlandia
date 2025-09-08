import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from routes.app import app as flask_app, db
import routes.app as app_module
from models import User, Clinica, Veterinario
from io import BytesIO
from PIL import Image


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    yield flask_app


def test_minha_clinica_redirects(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Pet Clinic")
        user = User(name="Vet", email="vet@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=clinica)
        db.session.add_all([clinica, user, vet])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/minha-clinica')
        assert resp.status_code == 302
        assert f"/clinica/{clinica.id}" in resp.headers['Location']


def test_vet_without_clinic_can_create(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Vet", email="noclinic@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123")
        db.session.add_all([user, vet])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/minha-clinica')
        assert resp.status_code == 200
        assert b'Criar Cl' in resp.data

        db.session.remove()
        db.drop_all()


def test_minha_clinica_shows_dashboard_for_multiple_clinics(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        user = User(name="Owner", email="o@example.com", password_hash="x")
        c1 = Clinica(nome="C1", owner=user)
        c2 = Clinica(nome="C2", owner=user)
        v1_user = User(name="V1", email="v1@example.com", password_hash="x")
        v2_user = User(name="V2", email="v2@example.com", password_hash="x")
        v1 = Veterinario(user=v1_user, crmv="1", clinica=c1)
        v2 = Veterinario(user=v2_user, crmv="2", clinica=c2)
        db.session.add_all([user, c1, c2, v1_user, v1, v2_user, v2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/minha-clinica')
        assert resp.status_code == 200
        assert b'C1' in resp.data and b'C2' in resp.data
        assert b'V1' in resp.data and b'V2' in resp.data


def test_layout_shows_minha_clinica_for_veterinario(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Pet Clinic")
        user = User(name="Vet", email="vet2@example.com", password_hash="x")
        vet = Veterinario(user=user, crmv="123", clinica=clinica)
        db.session.add_all([clinica, user, vet])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/')
        assert b'Minha Cl\xc3\xadnica' in resp.data


def test_layout_shows_minha_clinica_for_colaborador(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        clinica = Clinica(nome="Pet Clinic")
        user = User(name="Colab", email="colab@example.com", password_hash="x", worker="colaborador", clinica=clinica)
        db.session.add_all([clinica, user])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        resp = client.get('/')
        assert b'Minha Cl\xc3\xadnica' in resp.data


def test_minha_clinica_admin_defaults_to_own_clinic(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.create_all()
        other = Clinica(nome="Outra")
        admin = User(name="Admin", email="admin@example.com", password_hash="x", role="admin")
        db.session.add_all([admin, other])
        db.session.commit()

        mine = Clinica(nome="Minha", owner=admin)
        db.session.add(mine)
        db.session.commit()

        admin.clinica_id = mine.id
        db.session.add(admin)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

        resp = client.get('/minha-clinica')
        assert resp.status_code == 302
        assert f"/clinica/{mine.id}" in resp.headers['Location']


def test_create_clinic_without_logo_does_not_upload(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Owner", email="owner@example.com", password_hash="x")
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        called = {}

        def fake_upload(file, filename, folder="uploads"):
            called["called"] = True
            return "http://img"

        monkeypatch.setattr(app_module, "upload_to_s3", fake_upload)

        resp = client.post(
            '/minha-clinica',
            data={
                'nome': 'Clinica X',
                'photo_rotation': '0',
                'photo_zoom': '1',
                'photo_offset_x': '0',
                'photo_offset_y': '0',
            },
        )

        assert resp.status_code == 302
        assert Clinica.query.count() == 1
        assert "called" not in called


def test_create_clinic_with_logo_uploads(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Owner", email="owner2@example.com", password_hash="x")
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        img_bytes = BytesIO()
        Image.new('RGB', (1, 1)).save(img_bytes, format='PNG')
        img_bytes.seek(0)

        called = {}

        def fake_upload(file, filename, folder="uploads"):
            called["called"] = True
            return "http://img"

        monkeypatch.setattr(app_module, "upload_to_s3", fake_upload)

        resp = client.post(
            '/minha-clinica',
            data={
                'nome': 'Clinica Y',
                'logotipo': (img_bytes, 'logo.png'),
                'photo_rotation': '0',
                'photo_zoom': '1',
                'photo_offset_x': '0',
                'photo_offset_y': '0',
            },
            content_type='multipart/form-data'
        )

        assert resp.status_code == 302
        clinica = Clinica.query.first()
        assert clinica.logotipo == "http://img"
        assert "called" in called
