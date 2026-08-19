import re

import flask_login.utils as login_utils

from extensions import db
from models import User
from services.health_plan import insurer_token_valid


def test_public_health_endpoints_and_security_headers(app):
    client = app.test_client()

    live = client.get('/live')
    assert live.status_code == 200
    assert live.get_json() == {'status': 'ok'}
    assert live.headers['X-Content-Type-Options'] == 'nosniff'
    assert live.headers['X-Frame-Options'] == 'DENY'
    assert 'Content-Security-Policy' in live.headers
    assert 'https://www.mercadopago.com.br' in live.headers['Content-Security-Policy']

    ready = client.get('/ready')
    assert ready.status_code == 200
    assert ready.get_json() == {'status': 'ready'}


def test_csp_allows_blob_media_and_images(app):
    """Object URLs sao a unica forma de exibir a foto recem-tirada e o video do
    dia gerado em canvas no PMO. Sem blob: em img-src/media-src o Chrome bloqueia
    a midia e o preview do video volta a falhar."""
    client = app.test_client()

    csp = client.get('/live').headers['Content-Security-Policy']
    directives = {
        part.strip().split(' ')[0]: part.strip()
        for part in csp.split(';')
        if part.strip()
    }

    assert 'blob:' in directives['img-src']
    assert 'media-src' in directives, 'media-src ausente cai em default-src e bloqueia blob:'
    assert 'blob:' in directives['media-src']


def test_service_worker_does_not_intercept_form_posts_and_is_always_revalidated(app):
    client = app.test_client()

    response = client.get('/service-worker.js')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-cache, no-store, must-revalidate'
    assert response.headers['Pragma'] == 'no-cache'
    assert response.headers['Expires'] == '0'
    assert response.headers['Service-Worker-Allowed'] == '/'

    source = response.get_data(as_text=True)
    method_guard = "if (event.request.method !== 'GET')"
    navigation_handler = "if (event.request.mode === 'navigate')"
    assert method_guard in source
    assert navigation_handler in source
    assert source.index(method_guard) < source.index(navigation_handler)
    # O nome do cache precisa ser versionado para que o activate limpe os
    # caches antigos. Fixar o número aqui só fazia o guard quebrar a cada bump
    # legítimo, então validamos o formato.
    assert re.search(r"const CACHE_NAME = 'petorlandia-cache-v\d+';", source)


def test_authenticated_layout_forces_the_new_service_worker_url(app, client, monkeypatch):
    user = User(name='Dra. Worker', email='worker-update@example.com')
    user.set_password('segredo123')
    db.session.add(user)
    db.session.commit()
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)

    response = client.get('/')

    assert response.status_code == 200
    # O registro precisa carregar uma URL versionada (senão um worker antigo
    # continua no controle) e essa URL exata nunca pode ser cacheada.
    registered = re.search(
        r"serviceWorker\.register\('([^']*/service-worker\.js\?v=[^']+)'\)",
        response.get_data(as_text=True),
    )
    assert registered, 'layout precisa registrar o service worker com ?v='

    worker = client.get(registered.group(1))
    assert worker.status_code == 200
    assert worker.headers['Cache-Control'] == 'no-cache, no-store, must-revalidate'


def test_insurer_integration_fails_closed_without_secret(app):
    app.config['INSURER_PORTAL_TOKEN'] = None
    assert insurer_token_valid(None) is False
    assert insurer_token_valid('petorlandia-insurer') is False


def test_insurer_integration_uses_constant_time_secret_comparison(app):
    app.config['INSURER_PORTAL_TOKEN'] = 'rotated-test-secret'
    assert insurer_token_valid('rotated-test-secret') is True
    assert insurer_token_valid('wrong-secret') is False


def test_registration_can_start_without_address(app):
    client = app.test_client()
    response = client.post(
        '/register',
        data={
            'name': 'Tutor Progressivo',
            'email': 'progressivo@example.com',
            'password': 'segura123',
            'confirm_password': 'segura123',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    # Cadastro cai no onboarding, não no sistema vazio.
    assert response.headers['Location'].endswith('/comecar')


def test_html_csrf_failure_returns_to_form_instead_of_raw_400(app):
    original = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        client = app.test_client()
        response = client.post(
            '/register',
            data={
                'name': 'Sessão Antiga',
                'email': 'sessao.antiga@example.com',
                'password': 'segura123',
            },
            headers={
                'Accept': 'text/html',
                'Referer': 'http://localhost/register?next=/minha-clinica',
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers['Location'] == '/register?next=/minha-clinica'
    finally:
        app.config['WTF_CSRF_ENABLED'] = original


def test_json_csrf_failure_keeps_structured_400(app):
    original = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        client = app.test_client()
        response = client.post(
            '/register',
            json={'name': 'Sessão Antiga'},
            headers={'Accept': 'application/json'},
        )
        assert response.status_code == 400
        assert response.get_json()['error'] == 'CSRF token missing or invalid'
    finally:
        app.config['WTF_CSRF_ENABLED'] = original


def test_login_rate_limit_is_enforced_when_enabled(app):
    app.config['RATELIMIT_ENABLED'] = True
    client = app.test_client()
    statuses = [
        client.post('/login', data={'login': 'not-found@example.com', 'password': 'wrong'}).status_code
        for _ in range(11)
    ]
    assert 429 in statuses
