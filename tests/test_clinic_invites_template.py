import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app, db, MISSING_VET_PROFILE_MESSAGE
from sqlalchemy.pool import StaticPool
from models import Clinica, User, Veterinario, VetClinicInvite


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )
    engines = db._app_engines.setdefault(flask_app, {})
    default_engine = engines.get(None)
    if default_engine is not None:
        default_engine.dispose()
    engine_options = db._engine_options.copy()
    engine_options.update(flask_app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {}))
    engine_options["url"] = flask_app.config["SQLALCHEMY_DATABASE_URI"]
    echo = flask_app.config.setdefault("SQLALCHEMY_ECHO", False)
    engine_options.setdefault("echo", echo)
    engine_options.setdefault("echo_pool", echo)
    db._make_metadata(None)
    db._apply_driver_defaults(engine_options, flask_app)
    engines[None] = db._make_engine(None, engine_options, flask_app)
    with flask_app.app_context():
        db.session.remove()
    yield flask_app


def login(monkeypatch, user):
    import flask_login.utils as login_utils
    from flask_login import login_user

    monkeypatch.setattr(login_utils, '_get_user', lambda: user)
    with flask_app.test_request_context():
        login_user(user)


def test_clinic_invites_template_renders_details(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()

        owner = User(
            name="Dra. Ana",
            email="owner@example.com",
            password_hash="owner-password",
            worker="clinica",
        )
        clinic = Clinica(
            nome="Clínica Lua",
            endereco="Rua das Flores, 123 - Centro",
            logotipo="https://example.com/logo.png",
            owner=owner,
        )
        vet_user = User(
            name="Dr. João",
            email="vet@example.com",
            password_hash="vet-password",
            worker="veterinario",
        )
        vet = Veterinario(user=vet_user, crmv="CRMV-1234")
        invite = VetClinicInvite(clinica=clinic, veterinario=vet)
        db.session.add_all([owner, clinic, vet_user, vet, invite])
        db.session.commit()

        login(monkeypatch, vet_user)

        response = client.get('/convites/clinica')
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "Clínica Lua" in html
        assert "Rua das Flores, 123 - Centro" in html
        assert "Dra. Ana" in html
        assert f"Logo da clínica {clinic.nome}" in html
        assert "Aceitar" in html
        assert "Recusar" in html
        assert 'name="csrf_token"' in html

        from flask import url_for

        with app.test_request_context():
            accept_url = url_for('respond_clinic_invite', invite_id=invite.id, action='accept')
            decline_url = url_for('respond_clinic_invite', invite_id=invite.id, action='decline')

        assert f'action="{accept_url}"' in html
        assert f'action="{decline_url}"' in html

        db.session.remove()
        db.drop_all()


def test_clinic_invites_template_guides_user_without_profile(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()

        vet_user = User(
            name="Dr. Sem Perfil",
            email="semperfil@example.com",
            password_hash="senha-secreta",
            worker="veterinario",
        )
        db.session.add(vet_user)
        db.session.commit()

        login(monkeypatch, vet_user)

        response = client.get('/convites/clinica')
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert MISSING_VET_PROFILE_MESSAGE in html
        assert "Nenhum convite por aqui" not in html

        db.session.remove()
        db.drop_all()
