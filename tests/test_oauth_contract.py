import re
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import base64
import json

from extensions import db
from models import OAuthAccessToken, OAuthClient, OAuthRefreshToken, User, Veterinario
from time_utils import utcnow


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
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
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


def test_authorization_code_binds_access_and_refresh_tokens_to_mcp_resource(app, client):
    user_id = _seed_user_and_client(app, client_id='resource-client')
    _login(client, user_id)
    resource = 'https://www.petorlandia.com.br/mcp/v2'

    consent_response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'resource-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'state-resource',
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
            'code_challenge_method': 'S256',
            'resource': resource,
        },
    )
    assert consent_response.status_code == 200
    assert f'name="resource" value="{resource}"'.encode() in consent_response.data

    authorize_response = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'resource-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'state-resource',
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
            'code_challenge_method': 'S256',
            'resource': resource,
            'consent_action': 'approve',
            'consent_scopes': ['openid', 'profile', 'email'],
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorize_response.headers['Location']).query)['code'][0]

    mismatch = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'resource-client',
            'redirect_uri': 'https://client.example/callback',
            'code_verifier': 'verifier',
            'resource': 'https://www.petorlandia.com.br/mcp',
        },
    )
    assert mismatch.status_code == 400
    assert mismatch.get_json()['error'] == 'invalid_target'

    token_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'resource-client',
            'redirect_uri': 'https://client.example/callback',
            'code_verifier': 'verifier',
            'resource': resource,
        },
    )
    assert token_response.status_code == 200
    payload = token_response.get_json()
    with app.app_context():
        access = OAuthAccessToken.query.filter_by(access_token=payload['access_token']).one()
        refresh = OAuthRefreshToken.query.filter_by(refresh_token=payload['refresh_token']).one()
        assert access.resource == resource
        assert refresh.resource == resource


def test_authorize_rejects_resource_outside_petorlandia_mcp(app, client):
    user_id = _seed_user_and_client(app, client_id='invalid-resource-client')
    _login(client, user_id)

    response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'invalid-resource-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'state-invalid-resource',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
            'resource': 'https://attacker.example/mcp',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_target'


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


def test_authorize_get_renders_consent_screen(app, client):
    user_id = _seed_user_and_client(app, client_id='screen-client')
    _login(client, user_id)

    response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'screen-client',
            'redirect_uri': 'https://client.example/callback',
            'scope': 'openid profile email',
            'state': 'screen-state',
            'code_challenge': 'challenge',
            'code_challenge_method': 'S256',
        },
    )

    assert response.status_code == 200
    assert b'Autorizar acesso' in response.data
    assert b'name="consent_action"' in response.data


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
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
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
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
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


def test_confidential_client_requires_pkce_and_client_secret(app, client):
    with app.app_context():
        user = User(name='Confidential User', email='confidential@example.com', role='adotante')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='confidential-client',
            client_secret='super-secret',
            name='Confidential client',
            redirect_uris='https://client.example/confidential-callback',
            scopes='openid profile email',
            is_confidential=True,
            auth_method='client_secret_post',
        )
        db.session.add_all([user, oauth_client])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)

    missing_pkce = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'confidential-client',
            'redirect_uri': 'https://client.example/confidential-callback',
            'scope': 'openid profile email',
            'state': 'state-without-pkce',
        },
    )
    assert missing_pkce.status_code == 400
    assert missing_pkce.get_json()['error'] == 'invalid_request'

    authorize_response = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'confidential-client',
            'redirect_uri': 'https://client.example/confidential-callback',
            'scope': 'openid profile email',
            'state': 'state-chatgpt',
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
            'code_challenge_method': 'S256',
            'consent_action': 'approve',
            'consent_scopes': ['openid', 'profile', 'email'],
        },
        follow_redirects=False,
    )
    assert authorize_response.status_code == 302
    code = parse_qs(urlparse(authorize_response.headers['Location']).query)['code'][0]

    missing_secret = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'confidential-client',
            'redirect_uri': 'https://client.example/confidential-callback',
            'code_verifier': 'verifier',
        },
    )
    assert missing_secret.status_code == 401
    assert missing_secret.get_json()['error'] == 'invalid_client'

    token_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'confidential-client',
            'client_secret': 'super-secret',
            'redirect_uri': 'https://client.example/confidential-callback',
            'code_verifier': 'verifier',
        },
    )
    assert token_response.status_code == 200
    assert token_response.get_json()['token_type'] == 'Bearer'


def test_chatgpt_cached_oidc_scope_is_expanded_to_clinical_consent_and_token(app, client):
    redirect_uri = 'https://chatgpt.com/aip/petorlandia/oauth/callback'
    with app.app_context():
        user = User(name='Dr. ChatGPT', email='chatgpt-vet@example.com', role='veterinario', worker='veterinario')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='chatgpt-stale-client',
            name='ChatGPT PetOrlandia MCP',
            redirect_uris=redirect_uri,
            scopes='openid profile email',
        )
        db.session.add_all([user, oauth_client])
        db.session.flush()
        db.session.add(Veterinario(user_id=user.id, crmv='CRMV-CHATGPT'))
        db.session.commit()
        user_id = user.id

    _login(client, user_id)

    consent_response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': 'chatgpt-stale-client',
            'redirect_uri': redirect_uri,
            'scope': 'openid profile email',
            'state': 'state-chatgpt-stale',
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
            'code_challenge_method': 'S256',
        },
    )

    assert consent_response.status_code == 200
    html = consent_response.get_data(as_text=True)
    consent_scopes = re.findall(r'name="consent_scopes" value="([^"]+)"', html)
    scope_value = re.search(r'name="scope" value="([^"]+)"', html).group(1)
    assert 'pets:read' in consent_scopes
    assert 'exams:write' in consent_scopes

    authorize_response = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'chatgpt-stale-client',
            'redirect_uri': redirect_uri,
            'scope': scope_value,
            'state': 'state-chatgpt-stale',
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
            'code_challenge_method': 'S256',
            'consent_action': 'approve',
            'consent_scopes': consent_scopes,
        },
        follow_redirects=False,
    )
    assert authorize_response.status_code == 302
    code = parse_qs(urlparse(authorize_response.headers['Location']).query)['code'][0]

    token_response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'chatgpt-stale-client',
            'redirect_uri': redirect_uri,
            'code_verifier': 'verifier',
        },
    )

    assert token_response.status_code == 200
    granted_scopes = set(token_response.get_json()['scope'].split())
    assert {'pets:read', 'exams:write', 'clinical_summary:read'}.issubset(granted_scopes)
    with app.app_context():
        stored_client = OAuthClient.query.filter_by(client_id='chatgpt-stale-client').one()
        assert {'pets:read', 'exams:write'}.issubset(set(stored_client.scopes.split()))


def test_chatgpt_dynamic_client_connector_redirect_reaches_clinical_consent(app, client):
    redirect_uri = 'https://chatgpt.com/connector/oauth/petorlandia-callback-123'
    registration = client.post(
        '/oauth/register',
        json={
            'client_name': 'ChatGPT PetOrlandia MCP',
            'redirect_uris': [redirect_uri],
            'token_endpoint_auth_method': 'none',
            'grant_types': ['authorization_code', 'refresh_token'],
            'response_types': ['code'],
            'scope': 'openid profile email',
            'resource': 'https://www.petorlandia.com.br/mcp',
        },
    )
    assert registration.status_code == 201
    client_id = registration.get_json()['client_id']

    with app.app_context():
        user = User(name='Dr. Connector', email='chatgpt-connector@example.com', role='veterinario', worker='veterinario')
        user.set_password('secret123')
        db.session.add(user)
        db.session.flush()
        db.session.add(Veterinario(user_id=user.id, crmv='CRMV-CONNECTOR'))
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    consent_response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'scope': 'openid profile email',
            'state': 'state-chatgpt-connector',
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
            'code_challenge_method': 'S256',
            'resource': 'https://www.petorlandia.com.br/mcp',
        },
    )

    assert consent_response.status_code == 200
    html = consent_response.get_data(as_text=True)
    assert 'Autorizar acesso' in html
    consent_scopes = re.findall(r'name="consent_scopes" value="([^"]+)"', html)
    assert {'openid', 'profile', 'email', 'pets:read', 'exams:write'}.issubset(set(consent_scopes))


def test_chatgpt_dynamic_client_gives_tutor_own_record_scopes_without_vet_scopes(app, client):
    redirect_uri = 'https://chatgpt.com/connector/oauth/petorlandia-tutor-callback'
    registration = client.post(
        '/oauth/register',
        json={
            'client_name': 'ChatGPT PetOrlandia MCP',
            'redirect_uris': [redirect_uri],
            'token_endpoint_auth_method': 'none',
            'grant_types': ['authorization_code', 'refresh_token'],
            'response_types': ['code'],
            'scope': 'openid profile email',
            'resource': 'https://www.petorlandia.com.br/mcp',
        },
    )
    client_id = registration.get_json()['client_id']

    with app.app_context():
        user = User(name='Tutor Connector', email='tutor-connector@example.com', role='adotante')
        user.set_password('secret123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    consent_response = client.get(
        '/oauth/authorize',
        query_string={
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'scope': 'openid profile email',
            'state': 'state-chatgpt-tutor',
            'code_challenge': 'iMnq5o6zALKXGivsnlom_0F5_WYda32GHkxlV7mq7hQ',
            'code_challenge_method': 'S256',
            'resource': 'https://www.petorlandia.com.br/mcp',
        },
    )

    assert consent_response.status_code == 200
    consent_scopes = set(re.findall(r'name="consent_scopes" value="([^"]+)"', consent_response.get_data(as_text=True)))
    assert {'pets:read', 'pets:write', 'tutors:write', 'appointments:write'}.issubset(consent_scopes)
    assert 'consultations:write' not in consent_scopes
    assert 'exams:write' not in consent_scopes


def test_chatgpt_oidc_only_refresh_token_requires_reauthorization_for_veterinarian(app, client):
    with app.app_context():
        user = User(name='Dr. Refresh', email='chatgpt-refresh@example.com', role='veterinario', worker='veterinario')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='chatgpt-refresh-client',
            name='ChatGPT PetOrlandia MCP',
            redirect_uris='https://chatgpt.com/aip/petorlandia/oauth/callback',
            scopes='openid profile email',
        )
        db.session.add_all([user, oauth_client])
        db.session.flush()
        db.session.add(Veterinario(user_id=user.id, crmv='CRMV-REFRESH'))
        refresh = OAuthRefreshToken(
            client_id='chatgpt-refresh-client',
            user_id=user.id,
            refresh_token='refresh-token-with-basic-scope',
            scope='openid profile email',
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.session.add(refresh)
        db.session.commit()
        refresh_id = refresh.id

    response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'refresh_token',
            'client_id': 'chatgpt-refresh-client',
            'refresh_token': 'refresh-token-with-basic-scope',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_grant'
    with app.app_context():
        stored_refresh = db.session.get(OAuthRefreshToken, refresh_id)
        assert stored_refresh.revoked_at is not None
        assert stored_refresh.replaced_by_jti is None


def test_chatgpt_oidc_only_refresh_token_requires_reauthorization_for_tutor(app, client):
    with app.app_context():
        user = User(name='Tutor Refresh', email='chatgpt-refresh-tutor@example.com', role='adotante')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='chatgpt-refresh-tutor-client',
            name='ChatGPT PetOrlandia MCP',
            redirect_uris='https://chatgpt.com/aip/petorlandia/oauth/callback',
            scopes='openid profile email',
        )
        db.session.add_all([user, oauth_client])
        db.session.flush()
        refresh = OAuthRefreshToken(
            client_id='chatgpt-refresh-tutor-client',
            user_id=user.id,
            refresh_token='refresh-token-tutor-basic-scope',
            scope='openid profile email',
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.session.add(refresh)
        db.session.commit()
        refresh_id = refresh.id

    response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'refresh_token',
            'client_id': 'chatgpt-refresh-tutor-client',
            'refresh_token': 'refresh-token-tutor-basic-scope',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_grant'
    with app.app_context():
        stored_refresh = db.session.get(OAuthRefreshToken, refresh_id)
        assert stored_refresh.revoked_at is not None
        assert stored_refresh.replaced_by_jti is None


def test_revoked_chatgpt_refresh_token_cannot_self_heal(app, client):
    with app.app_context():
        user = User(name='Tutor Revogado', email='refresh-revogado@example.com', role='adotante')
        user.set_password('secret123')
        oauth_client = OAuthClient(
            client_id='chatgpt-revoked-refresh-client',
            name='ChatGPT PetOrlandia MCP',
            redirect_uris='https://chatgpt.com/connector/oauth/petorlandia-revoked',
            scopes='openid profile email',
        )
        db.session.add_all([user, oauth_client])
        db.session.flush()
        refresh = OAuthRefreshToken(
            client_id=oauth_client.client_id,
            user_id=user.id,
            refresh_token='revoked-chatgpt-refresh-token',
            scope='openid profile email',
            revoked_at=utcnow() - timedelta(minutes=1),
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.session.add(refresh)
        db.session.commit()

    response = client.post(
        '/oauth/token',
        data={
            'grant_type': 'refresh_token',
            'client_id': 'chatgpt-revoked-refresh-client',
            'refresh_token': 'revoked-chatgpt-refresh-token',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_grant'
    with app.app_context():
        stored_tokens = OAuthRefreshToken.query.filter_by(
            client_id='chatgpt-revoked-refresh-client'
        ).all()
        assert len(stored_tokens) == 1
        assert stored_tokens[0].revoked_at is not None
        assert stored_tokens[0].replaced_by_jti is None
