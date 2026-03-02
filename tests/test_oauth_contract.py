from urllib.parse import parse_qs, urlparse

import base64
import json

from extensions import db
from models import OAuthClient, User


def _login(client, user_id: int):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _seed_user_and_client(app, client_id='contract-client', redirect_uri='https://client.example/callback'):
    with app.app_context():
        user = User(name='Contract User', email='contract@example.com', role='adotante')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id=client_id,
            name='Contract client',
            redirect_uris=redirect_uri,
            scopes='openid profile email appointments:read',
        )
        db.session.add_all([user, oauth_client])
        db.session.commit()
        return user.id


def test_authorization_code_pkce_contract(app, client):
    user_id = _seed_user_and_client(app)
    _login(client, user_id)

    authorize_response = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'contract-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'state-123',
            'nonce': 'nonce-123',
            'code_challenge': 'Z_P4EKbGwIkA01e3Y5fp4tMCvn_Ae5nUw7qY7XwkTrQ',
            'code_challenge_method': 'S256',
            'consent_action': 'approve',
            'consent_scopes': ['openid', 'profile', 'email'],
        },
        follow_redirects=False,
    )

    assert authorize_response.status_code == 302
    parsed = urlparse(authorize_response.headers['Location'])
    params = parse_qs(parsed.query)
    assert parsed.scheme == 'https'
    assert parsed.netloc == 'client.example'
    assert params['state'] == ['state-123']
    assert 'code' in params

    token_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': params['code'][0],
            'client_id': 'contract-client',
            'redirect_uri': 'https://client.example/callback',
            'code_verifier': 'verifier',
        },
    )

    assert token_response.status_code == 200
    payload = token_response.get_json()
    assert payload['token_type'] == 'Bearer'
    assert 'refresh_token' in payload
    assert 'id_token' in payload


def test_authorize_requires_state(app, client):
    user_id = _seed_user_and_client(app, client_id='state-client')
    _login(client, user_id)

    response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'state-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_request'
    assert response.get_json()['error_description'] == 'state is required.'


def test_token_rejects_invalid_redirect_uri_and_unknown_client(app, client):
    user_id = _seed_user_and_client(app, client_id='error-client')
    _login(client, user_id)

    authorize_response = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'error-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'state-error',
            'code_challenge': 'Z_P4EKbGwIkA01e3Y5fp4tMCvn_Ae5nUw7qY7XwkTrQ',
            'code_challenge_method': 'S256',
            'consent_action': 'approve',
            'consent_scopes': ['openid', 'profile', 'email'],
        },
    )
    code = parse_qs(urlparse(authorize_response.headers['Location']).query)['code'][0]

    wrong_redirect = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'error-client',
            'redirect_uri': 'https://client.example/other-callback',
            'code_verifier': 'verifier',
        },
    )
    assert wrong_redirect.status_code == 400
    assert wrong_redirect.get_json()['error'] == 'invalid_grant'

    unknown_client = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'missing-client',
            'redirect_uri': 'https://client.example/callback',
            'code_verifier': 'verifier',
        },
    )
    assert unknown_client.status_code == 401
    assert unknown_client.get_json()['error'] == 'invalid_client'


def test_oidc_claims_are_emitted_in_id_token_and_userinfo(app, client):
    user_id = _seed_user_and_client(app, client_id='claims-client')
    _login(client, user_id)

    authorize_response = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'claims-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'state-claims',
            'nonce': 'nonce-claims',
            'code_challenge': 'Z_P4EKbGwIkA01e3Y5fp4tMCvn_Ae5nUw7qY7XwkTrQ',
            'code_challenge_method': 'S256',
            'consent_action': 'approve',
            'consent_scopes': ['openid', 'profile', 'email'],
        },
    )
    code = parse_qs(urlparse(authorize_response.headers['Location']).query)['code'][0]

    token_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'claims-client',
            'redirect_uri': 'https://client.example/callback',
            'code_verifier': 'verifier',
        },
    )
    tokens = token_response.get_json()

    id_token_parts = tokens['id_token'].split('.')
    payload = id_token_parts[1] + '=' * (-len(id_token_parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload.encode('utf-8')).decode('utf-8'))

    assert claims['aud'] == 'claims-client'
    assert claims['sub'] == str(user_id)
    assert claims['email'] == 'contract@example.com'
    assert claims['name'] == 'Contract User'
    assert claims['nonce'] == 'nonce-claims'

    userinfo = client.get(
        '/oauth/userinfo',
        headers={'Authorization': f"Bearer {tokens['access_token']}"},
    )
    assert userinfo.status_code == 200
    assert userinfo.get_json()['sub'] == str(user_id)
    assert userinfo.get_json()['email'] == 'contract@example.com'
