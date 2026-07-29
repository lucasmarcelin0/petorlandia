"""Login com Google: degradação sem credenciais, proteção de CSRF e criação de conta."""

import os

import pytest

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

from app_factory import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import User  # noqa: E402
from services import google_login  # noqa: E402


@pytest.fixture
def app():
    application = create_app()
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        GOOGLE_OAUTH_CLIENT_ID='client-id.apps.googleusercontent.com',
        GOOGLE_OAUTH_CLIENT_SECRET='client-secret',
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _stub_google(monkeypatch, claims):
    monkeypatch.setattr(google_login, 'exchange_code', lambda code, redirect_uri: 'token')
    monkeypatch.setattr(google_login, 'verify_id_token', lambda token: claims)


def test_botao_some_quando_nao_ha_credenciais(app, client):
    app.config['GOOGLE_OAUTH_CLIENT_ID'] = None
    app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = None

    assert 'google-btn' not in client.get('/login').get_data(as_text=True)
    # Sem credenciais o callback não pode devolver 404 cru: quem chegar nele
    # (link antigo, favorito) volta para o login com explicação.
    response = client.get('/auth/google/callback')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_inicio_do_fluxo_guarda_state_na_sessao(client):
    response = client.get('/auth/google')

    assert response.status_code == 302
    assert response.headers['Location'].startswith(
        'https://accounts.google.com/o/oauth2/v2/auth'
    )
    with client.session_transaction() as sess:
        assert sess.get(google_login.STATE_SESSION_KEY)


def test_callback_rejeita_state_divergente(client, monkeypatch):
    """Sem conferir o state, um terceiro poderia forçar login numa conta alheia."""
    _stub_google(monkeypatch, {'email': 'invasor@example.com', 'email_verified': True})

    client.get('/auth/google')  # grava o state legítimo na sessão
    response = client.get('/auth/google/callback?code=abc&state=state-forjado')

    assert response.status_code == 302
    assert '/login' in response.headers['Location']
    assert User.query.filter_by(email='invasor@example.com').first() is None


def test_callback_cria_conta_e_leva_ao_onboarding(client, monkeypatch):
    _stub_google(monkeypatch, {
        'email': 'Nova.Pessoa@Example.com',
        'email_verified': True,
        'name': 'Nova Pessoa',
    })

    client.get('/auth/google')
    with client.session_transaction() as sess:
        state = sess[google_login.STATE_SESSION_KEY]

    response = client.get(f'/auth/google/callback?code=abc&state={state}')

    assert response.status_code == 302
    assert '/comecar' in response.headers['Location']

    user = User.query.filter_by(email='nova.pessoa@example.com').first()
    assert user is not None
    assert user.name == 'Nova Pessoa'


def test_callback_entra_em_conta_existente_sem_duplicar(client, monkeypatch):
    existente = User(name='Ja Existo', email='ja.existo@example.com')
    existente.set_password('senha-original')
    db.session.add(existente)
    db.session.commit()

    _stub_google(monkeypatch, {
        'email': 'ja.existo@example.com',
        'email_verified': True,
        'name': 'Ja Existo',
    })

    client.get('/auth/google')
    with client.session_transaction() as sess:
        state = sess[google_login.STATE_SESSION_KEY]

    response = client.get(f'/auth/google/callback?code=abc&state={state}')

    assert response.status_code == 302
    assert User.query.filter_by(email='ja.existo@example.com').count() == 1


def test_email_nao_verificado_e_recusado(app, monkeypatch):
    """E-mail não verificado não prova posse — aceitar seria porta para tomar conta alheia."""
    monkeypatch.setattr(
        google_login.google_id_token,
        'verify_oauth2_token',
        lambda *args, **kwargs: {
            'iss': 'https://accounts.google.com',
            'email': 'sem.verificar@example.com',
            'email_verified': False,
        },
    )

    with pytest.raises(google_login.GoogleLoginError, match='e-mail verificado'):
        google_login.verify_id_token('token')


def test_emissor_estranho_e_recusado(app, monkeypatch):
    """Token válido em forma, mas emitido por outro provedor, não vale."""
    monkeypatch.setattr(
        google_login.google_id_token,
        'verify_oauth2_token',
        lambda *args, **kwargs: {
            'iss': 'https://evil.example.com',
            'email': 'alguem@example.com',
            'email_verified': True,
        },
    )

    with pytest.raises(google_login.GoogleLoginError):
        google_login.verify_id_token('token')
