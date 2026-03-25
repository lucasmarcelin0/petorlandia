from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

from extensions import db
from models import OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken, User, Veterinario
from time_utils import utcnow


def _login(client, user_id: int):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _seed_client(app, *, client_id: str, scopes: str) -> None:
    with app.app_context():
        oauth_client = OAuthClient(
            client_id=client_id,
            name='ChatGPT connector',
            redirect_uris='https://chatgpt.example/callback',
            scopes=scopes,
        )
        db.session.add(oauth_client)
        db.session.commit()


def test_oauth_authorize_rejects_wildcard_redirect(app, client):
    with app.app_context():
        user = User(name='OAuth User', email='oauth@example.com', role='adotante')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='client-wildcard',
            name='Wildcard client',
            redirect_uris='https://example.com/*',
            scopes='openid profile email',
        )
        db.session.add_all([user, oauth_client])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'client-wildcard',
            'redirect_uri': 'https://example.com/callback',
            'scope': 'openid profile email',
            'state': 'abc',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_request'


def test_oauth_authorize_requires_explicit_scope_consent(app, client):
    with app.app_context():
        user = User(name='OAuth User 2', email='oauth2@example.com', role='adotante')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='client-consent',
            name='Consent client',
            redirect_uris='https://client.example/callback',
            scopes='openid profile email',
        )
        db.session.add_all([user, oauth_client])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'client-consent',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'abc',
            'nonce': 'n',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
            'consent_action': 'approve',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_scope'


def test_oauth_authorize_redirects_unauthenticated_users_to_login_with_next(app, client):
    _seed_client(app, client_id='client-login-flow', scopes='openid profile email tutors:write pets:write')

    response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'client-login-flow',
            'redirect_uri': 'https://chatgpt.example/callback',
            'scope': 'openid profile email tutors:write pets:write',
            'state': 'vet-flow',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    parsed = urlparse(response.headers['Location'])
    assert parsed.path == '/login'
    login_query = parse_qs(parsed.query)
    assert 'next' in login_query
    next_target = unquote(login_query['next'][0])
    assert '/oauth/authorize' in next_target
    assert 'client_id=client-login-flow' in next_target


def test_login_page_explains_chatgpt_connection_flow(app, client):
    response = client.get(
        '/login',
        query_string={
            'next': '/oauth/authorize?client_id=client-login-flow',
        },
    )

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'conectar o PetOrlândia ao ChatGPT' in page
    assert 'name="next"' in page


def test_oauth_authorize_blocks_non_veterinarian_for_write_scopes(app, client):
    _seed_client(app, client_id='client-vet-only', scopes='openid profile email tutors:write pets:write')

    with app.app_context():
        user = User(name='Tutor OAuth', email='tutor-oauth@example.com', role='adotante')
        user.set_password('secret123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'client-vet-only',
            'redirect_uri': 'https://chatgpt.example/callback',
            'scope': 'openid profile email tutors:write pets:write',
            'state': 'vet-only',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
        },
    )

    assert response.status_code == 403
    page = response.get_data(as_text=True)
    assert 'conta veterinária' in page
    assert 'Sair e entrar com outra conta' in page


def test_oauth_authorize_allows_veterinarian_for_write_scopes(app, client):
    _seed_client(app, client_id='client-vet-ok', scopes='openid profile email tutors:write pets:write')

    with app.app_context():
        user = User(
            name='Dra. OAuth',
            email='vet-oauth@example.com',
            role='veterinario',
            worker='veterinario',
        )
        user.set_password('secret123')
        db.session.add(user)
        db.session.flush()
        db.session.add(Veterinario(user_id=user.id, crmv='CRMV-9000'))
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'client-vet-ok',
            'redirect_uri': 'https://chatgpt.example/callback',
            'scope': 'openid profile email tutors:write pets:write',
            'state': 'vet-ok',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
        },
    )

    assert response.status_code == 200
    assert 'Autorizar acesso' in response.get_data(as_text=True)


def test_refresh_rotation_and_reuse_detection_revokes_family(app, client):
    app.config['OAUTH_ACCESS_TOKEN_EXPIRES_IN'] = 600
    app.config['OAUTH_REFRESH_TOKEN_EXPIRES_IN'] = 1200

    with app.app_context():
        user = User(name='OAuth User 3', email='oauth3@example.com', role='adotante')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='client-refresh',
            name='Refresh client',
            redirect_uris='https://client.example/callback',
            scopes='openid profile email',
        )
        db.session.add_all([user, oauth_client])
        db.session.commit()

        code = OAuthAuthorizationCode(
            code='code-value',
            client_id='client-refresh',
            user_id=user.id,
            redirect_uri='https://client.example/callback',
            scope='openid profile email',
            state='xyz',
            code_challenge='Z_P4EKbGwIkA01e3Y5fp4tMCvn_Ae5nUw7qY7XwkTrQ',
            code_challenge_method='S256',
            expires_at=utcnow() + timedelta(minutes=5),
        )
        db.session.add(code)
        db.session.commit()

    token_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': 'code-value',
            'client_id': 'client-refresh',
            'redirect_uri': 'https://client.example/callback',
            'code_verifier': 'verifier',
        },
    )
    assert token_response.status_code == 200
    first_refresh = token_response.get_json()['refresh_token']

    rotate_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'refresh_token',
            'client_id': 'client-refresh',
            'refresh_token': first_refresh,
        },
    )
    assert rotate_response.status_code == 200

    reuse_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'refresh_token',
            'client_id': 'client-refresh',
            'refresh_token': first_refresh,
        },
    )
    assert reuse_response.status_code == 400

    with app.app_context():
        tokens = OAuthRefreshToken.query.filter_by(client_id='client-refresh').all()
        assert len(tokens) == 2
        assert all(token.revoked_at is not None for token in tokens)
