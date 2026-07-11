from services.health_plan import insurer_token_valid


def test_public_health_endpoints_and_security_headers(app):
    client = app.test_client()

    live = client.get('/live')
    assert live.status_code == 200
    assert live.get_json() == {'status': 'ok'}
    assert live.headers['X-Content-Type-Options'] == 'nosniff'
    assert live.headers['X-Frame-Options'] == 'DENY'
    assert 'Content-Security-Policy' in live.headers

    ready = client.get('/ready')
    assert ready.status_code == 200
    assert ready.get_json() == {'status': 'ready'}


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
    assert response.headers['Location'].endswith('/')


def test_login_rate_limit_is_enforced_when_enabled(app):
    app.config['RATELIMIT_ENABLED'] = True
    client = app.test_client()
    statuses = [
        client.post('/login', data={'login': 'not-found@example.com', 'password': 'wrong'}).status_code
        for _ in range(11)
    ]
    assert 429 in statuses
