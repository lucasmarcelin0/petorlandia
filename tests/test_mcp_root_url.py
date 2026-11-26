"""Conector do Claude cadastrado só com o domínio (sem /mcp).

O claude.ai mostrava "nenhum servidor MCP foi encontrado na URL fornecida":
o OAuth passava, mas o Claude mandava o JSON-RPC para POST / (405) e o token
saía sem resource, o que o /mcp também recusaria.
"""
import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from extensions import db
from models import OAuthAccessToken, OAuthClient, User

CLAUDE_CALLBACK = 'https://claude.ai/api/mcp/auth_callback'


def _login(client, user_id: int):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _claude_token(app, client) -> str:
    with app.app_context():
        user = User(name='Tutor Claude', email='claude-root@example.com', role='adotante')
        user.set_password('secret123')
        db.session.add_all([
            user,
            OAuthClient(
                client_id='claude-root-client',
                name='Claude',
                redirect_uris=CLAUDE_CALLBACK,
                scopes='openid profile email pets:read',
            ),
        ])
        db.session.commit()
        user_id = user.id

    verifier = 'v' * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    _login(client, user_id)
    scopes = ['openid', 'profile', 'email', 'pets:read']
    authorize = client.post(
        '/oauth/authorize',
        data={
            'response_type': 'code',
            'client_id': 'claude-root-client',
            'redirect_uri': CLAUDE_CALLBACK,
            'scope': ' '.join(scopes),
            'state': 'st',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'consent_action': 'approve',
            'consent_scopes': scopes,
        },
    )
    assert authorize.status_code == 302, authorize.get_data(as_text=True)
    code = parse_qs(urlparse(authorize.headers['Location']).query)['code'][0]

    token = client.post(
        '/oauth/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': 'claude-root-client',
            'redirect_uri': CLAUDE_CALLBACK,
            'code_verifier': verifier,
        },
    )
    assert token.status_code == 200, token.get_data(as_text=True)
    return token.get_json()['access_token']


def test_claude_token_without_resource_is_bound_to_mcp(app, client):
    access_token = _claude_token(app, client)

    with app.app_context():
        stored = OAuthAccessToken.query.filter_by(access_token=access_token).one()
        assert stored.resource.endswith('/mcp')


def test_mcp_json_rpc_works_on_root_url(app, client):
    access_token = _claude_token(app, client)
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}}

    response = client.post('/', json=body, headers={'Authorization': f'Bearer {access_token}'})

    assert response.status_code == 200
    assert response.get_json()['result']['serverInfo']['name']

    tools = client.post(
        '/',
        json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        headers={'Authorization': f'Bearer {access_token}'},
    )
    assert tools.status_code == 200
    assert tools.get_json()['result']['tools']


def test_root_url_without_token_points_to_mcp_metadata(app, client):
    response = client.post('/', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})

    assert response.status_code == 401
    assert 'oauth-protected-resource/mcp"' in response.headers['WWW-Authenticate']


def test_root_url_keeps_home_page_and_rejects_plain_form_post(app, client):
    assert client.get('/').status_code == 200
    assert client.post('/', data={'x': '1'}).status_code == 405


def test_root_resource_is_accepted_as_mcp_alias(app, client):
    with app.test_request_context('/'):
        from blueprints.oauth import _oauth_issuer, _oauth_normalize_mcp_resource

        issuer = _oauth_issuer().rstrip('/')
        assert _oauth_normalize_mcp_resource(issuer + '/') == f'{issuer}/mcp'


def test_non_claude_client_keeps_resource_unbound(app, client):
    from blueprints.oauth import _oauth_redirect_is_claude_mcp

    assert _oauth_redirect_is_claude_mcp(CLAUDE_CALLBACK)
    assert _oauth_redirect_is_claude_mcp('https://claude.com/api/mcp/auth_callback')
    assert not _oauth_redirect_is_claude_mcp('https://claude.ai.evil.example/api/mcp/auth_callback')
    assert not _oauth_redirect_is_claude_mcp('http://claude.ai/api/mcp/auth_callback')
