"""OAuth 2.0 / OpenID Connect provider — views reais do domínio.

Migrado do app.py monolítico. A lógica do provider (scopes, PKCE, JWKS,
tokens) vive em services/oauth_provider.py; o servidor MCP em blueprints/mcp.py.
"""
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlparse

from authlib.jose import JsonWebKey, jwt
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from extensions import csrf, db
from helpers import has_veterinarian_profile
from models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthConsent,
    OAuthJwkKey,
    OAuthRefreshToken,
    User,
)
from services.oauth_provider import (
    _oauth_allowed_scopes,
    _oauth_client_looks_like_openai_mcp,
    _oauth_client_redirect_valid,
    _oauth_default_mcp_scope,
    _oauth_ensure_mcp_client_scopes,
    _oauth_error_response,
    _oauth_extract_bearer_token,
    _oauth_extract_client_credentials,
    _oauth_get_signing_keys,
    _oauth_grouped_scope_details,
    _oauth_issue_refresh_grant_response,
    _oauth_issuer,
    _oauth_log_event,
    _oauth_normalize_scope,
    _oauth_order_scopes,
    _oauth_refresh_token_can_self_heal_mcp_scope,
    _oauth_refresh_token_requires_mcp_reauthorization,
    _oauth_registration_looks_like_openai_mcp,
    _oauth_requires_pkce,
    _oauth_revoke_refresh_family,
    _oauth_scope_details,
    _oauth_scope_needs_mcp_recovery,
    _oauth_validate_client_secret,
    _oauth_veterinarian_write_scopes,
    _pkce_s256,
)
from time_utils import utcnow

bp = Blueprint("oauth_routes", __name__)


def _oauth_normalize_mcp_resource(resource: str) -> str:
    """Validate and canonicalize the RFC 8707 resource for this MCP server."""
    value = (resource or '').strip().rstrip('/')
    if not value:
        return ''
    issuer = _oauth_issuer().rstrip('/')
    allowed_resources = {f'{issuer}/mcp', f'{issuer}/mcp/v2'}
    if value not in allowed_resources:
        raise ValueError('The requested resource is not a PetOrlandia MCP endpoint.')
    return value


def get_blueprint():
    return bp


# MCP server endpoint — JSON-RPC 2.0 over HTTP (views em blueprints/mcp.py)
from blueprints.mcp import mcp_protected_resource_metadata, mcp_server  # noqa: E402

bp.add_url_rule("/mcp", view_func=mcp_server, methods=["GET", "POST", "OPTIONS"])
# Versioned endpoint for clients that need a clean capability discovery cycle.
bp.add_url_rule("/mcp/v2", view_func=mcp_server, methods=["GET", "POST", "OPTIONS"], endpoint="mcp_server_v2")
# RFC 9396 Protected Resource Metadata — enables OAuth discovery for path-based URLs
bp.add_url_rule(
    "/.well-known/oauth-protected-resource",
    view_func=mcp_protected_resource_metadata,
    methods=["GET"],
)

# RFC 9728 discovery for a resource below the origin preserves its path.
# The root route remains as a compatibility alias for older MCP clients.
bp.add_url_rule(
    "/.well-known/oauth-protected-resource/mcp",
    view_func=mcp_protected_resource_metadata,
    methods=["GET"],
    endpoint="mcp_protected_resource_metadata_for_mcp",
)
bp.add_url_rule(
    "/.well-known/oauth-protected-resource/mcp/v2",
    view_func=mcp_protected_resource_metadata,
    methods=["GET"],
    endpoint="mcp_protected_resource_metadata_for_mcp_v2",
)


@bp.route("/oauth/authorize", methods=["GET", "POST"])
def oauth_authorize():
    response_type = request.values.get('response_type', '').strip()
    client_id = request.values.get('client_id', '').strip()
    redirect_uri = request.values.get('redirect_uri', '').strip()
    scope_raw = request.values.get('scope', '').strip()
    state = request.values.get('state', '').strip()
    nonce = request.values.get('nonce', '').strip() or None
    code_challenge = request.values.get('code_challenge', '').strip()
    code_challenge_method = request.values.get('code_challenge_method', '').strip()
    resource = request.values.get('resource', '').strip()
    recovered_default_mcp_scope = False

    if request.method == 'GET' and not response_type and not client_id:
        return redirect(url_for('site_routes.chatgpt_onboarding'))
    if response_type != 'code':
        return _oauth_error_response('unsupported_response_type', 'Only authorization code flow is supported.')
    if not client_id:
        return _oauth_error_response('invalid_request', 'client_id is required.')
    if not redirect_uri:
        return _oauth_error_response('invalid_request', 'redirect_uri is required.')
    if not state:
        return _oauth_error_response('invalid_request', 'state is required.')

    client = OAuthClient.query.filter_by(client_id=client_id).first()
    if not client:
        return _oauth_error_response('invalid_client', 'Unknown OAuth client.', 401)
    if not _oauth_client_redirect_valid(client, redirect_uri):
        return _oauth_error_response('invalid_request', 'redirect_uri is not allowed for this client.')

    requires_pkce = _oauth_requires_pkce(client)
    if requires_pkce and (not code_challenge or code_challenge_method != 'S256'):
        return _oauth_error_response('invalid_request', 'PKCE with code_challenge_method=S256 is required.')

    if _oauth_client_looks_like_openai_mcp(client, redirect_uri=redirect_uri, resource=resource):
        if _oauth_ensure_mcp_client_scopes(client):
            db.session.commit()
            _oauth_log_event('oauth_mcp_client_scopes_upgraded', client_id=client_id)
        if _oauth_scope_needs_mcp_recovery(scope_raw):
            scope_raw = _oauth_default_mcp_scope()
            recovered_default_mcp_scope = True

    try:
        resource = _oauth_normalize_mcp_resource(resource)
    except ValueError as exc:
        return _oauth_error_response('invalid_target', str(exc))

    try:
        scope = _oauth_normalize_scope(scope_raw, client)
    except ValueError as exc:
        return _oauth_error_response('invalid_scope', str(exc))

    requested_scopes = scope.split()

    if not current_user.is_authenticated:
        login_url = url_for('login_view', next=request.url)
        return redirect(login_url)

    if recovered_default_mcp_scope and not has_veterinarian_profile(current_user):
        scope = _oauth_normalize_scope(_oauth_default_mcp_scope(current_user.id), client)
        requested_scopes = scope.split()

    requested_scope_set = set(requested_scopes)
    if requested_scope_set.intersection(_oauth_veterinarian_write_scopes()) and not has_veterinarian_profile(current_user):
        return render_template(
            'auth/oauth_veterinarian_required.html',
            client=client,
            current_account=current_user,
            requested_scopes=requested_scopes,
            write_scopes=_oauth_scope_details(
                requested_scope_set.intersection(_oauth_veterinarian_write_scopes())
            ),
            error_message='Esta conexao pede permissoes de escrita clinica e exige uma conta veterinaria.',
            switch_account_url=url_for('logout'),
            continue_url=request.url,
        ), 403

    if request.method == 'POST':
        if request.form.get('consent_action') != 'approve':
            query = urlencode({'error': 'access_denied', 'state': state})
            return redirect(f'{redirect_uri}?{query}')

        consented_scopes = set(request.form.getlist('consent_scopes'))
        if set(requested_scopes) != consented_scopes:
            return _oauth_error_response('invalid_scope', 'Explicit consent is required for each requested scope.')

        auth_code = OAuthAuthorizationCode(
            code=secrets.token_urlsafe(48),
            client_id=client_id,
            user_id=current_user.id,
            redirect_uri=redirect_uri,
            resource=resource or None,
            scope=scope,
            nonce=nonce,
            state=state,
            code_challenge=code_challenge if requires_pkce else '',
            code_challenge_method='S256' if requires_pkce else 'none',
            expires_at=OAuthAuthorizationCode.new_expiration(current_app.config.get('OAUTH_AUTHORIZATION_CODE_EXPIRES_IN', 300)),
        )
        db.session.add(auth_code)
        db.session.commit()
        _oauth_log_event('oauth_authorization_code_issued', client_id=client_id, user_id=current_user.id, grant_type='authorization_code')

        query = urlencode({'code': auth_code.code, 'state': state})
        return redirect(f'{redirect_uri}?{query}')

    return render_template(
        'auth/oauth_consent.html',
        client=client,
        current_account=current_user,
        scope=scope,
        requested_scopes=requested_scopes,
        scope_groups=_oauth_grouped_scope_details(requested_scopes),
        state=state,
        redirect_uri=redirect_uri,
        response_type=response_type,
        client_id=client_id,
        nonce=nonce,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        resource=resource,
    )


@bp.route("/oauth/token", methods=["GET", "POST"])
@csrf.exempt
def oauth_token():
    if request.method == 'GET':
        return redirect(url_for('site_routes.chatgpt_onboarding'))
    grant_type = request.form.get('grant_type', '').strip()
    if grant_type == 'authorization_code':
        code = request.form.get('code', '').strip()
        client_id, client_secret = _oauth_extract_client_credentials()
        redirect_uri = request.form.get('redirect_uri', '').strip()
        code_verifier = request.form.get('code_verifier', '').strip()
        resource_raw = request.form.get('resource', '').strip()

        if not all([code, client_id, redirect_uri]):
            return _oauth_error_response('invalid_request', 'code, client_id and redirect_uri are required.')

        client = OAuthClient.query.filter_by(client_id=client_id).first()
        if not client:
            return _oauth_error_response('invalid_client', 'Unknown OAuth client.', 401)
        if not _oauth_validate_client_secret(client, client_secret):
            return _oauth_error_response('invalid_client', 'client authentication failed.', 401)

        auth_code = OAuthAuthorizationCode.query.filter_by(code=code, client_id=client_id).first()
        if not auth_code:
            return _oauth_error_response('invalid_grant', 'Authorization code is invalid.')
        if not auth_code.is_active:
            return _oauth_error_response('invalid_grant', 'Authorization code is expired or already used.')
        if auth_code.redirect_uri != redirect_uri:
            return _oauth_error_response('invalid_grant', 'redirect_uri does not match authorization request.')
        try:
            token_resource = _oauth_normalize_mcp_resource(resource_raw)
        except ValueError as exc:
            return _oauth_error_response('invalid_target', str(exc))
        if auth_code.resource and token_resource != auth_code.resource:
            return _oauth_error_response(
                'invalid_target',
                'resource does not match the authorization request.',
            )
        resource = auth_code.resource or token_resource or None
        if auth_code.code_challenge_method == 'S256':
            if not code_verifier:
                return _oauth_error_response('invalid_request', 'code_verifier is required for PKCE-enabled authorization codes.')
            if _pkce_s256(code_verifier) != auth_code.code_challenge:
                return _oauth_error_response('invalid_grant', 'code_verifier is invalid.')

        now_ts = int(utcnow().timestamp())
        expires_in = int(current_app.config.get('OAUTH_ACCESS_TOKEN_EXPIRES_IN', 900))
        access_token = secrets.token_urlsafe(48)
        private_jwk, _ = _oauth_get_signing_keys()

        user = db.session.get(User, auth_code.user_id)
        claims = {
            'iss': _oauth_issuer(),
            'sub': str(auth_code.user_id),
            'aud': client_id,
            'iat': now_ts,
            'exp': now_ts + expires_in,
            'email': user.email if user else '',
            'name': user.name if user else '',
        }
        if auth_code.nonce:
            claims['nonce'] = auth_code.nonce

        id_token = jwt.encode({'alg': 'RS256', 'kid': private_jwk.as_dict().get('kid')}, claims, private_jwk).decode('utf-8')

        refresh_expires_in = int(current_app.config.get('OAUTH_REFRESH_TOKEN_EXPIRES_IN', 2592000))
        refresh_token = OAuthRefreshToken(
            client_id=client_id,
            user_id=auth_code.user_id,
            refresh_token=secrets.token_urlsafe(48),
            resource=resource,
            scope=auth_code.scope,
            expires_at=utcnow() + timedelta(seconds=refresh_expires_in),
        )
        token = OAuthAccessToken(
            client_id=client_id,
            user_id=auth_code.user_id,
            access_token=access_token,
            token_type='Bearer',
            resource=resource,
            scope=auth_code.scope,
            id_token=id_token,
            refresh_token_id=refresh_token.id,
            expires_at=utcnow() + timedelta(seconds=expires_in),
        )
        auth_code.used_at = utcnow()
        consent = OAuthConsent.query.filter_by(user_id=auth_code.user_id, client_id=client_id).first()
        if consent is None:
            consent = OAuthConsent(user_id=auth_code.user_id, client_id=client_id, scopes=auth_code.scope)
        else:
            consent.scopes = auth_code.scope
            consent.revoked_at = None
        db.session.add(refresh_token)
        db.session.flush()
        token.refresh_token_id = refresh_token.id
        db.session.add(token)
        db.session.add(consent)
        db.session.add(auth_code)
        db.session.commit()
        _oauth_log_event('oauth_token_issued', client_id=client_id, user_id=auth_code.user_id, grant_type='authorization_code')

        return jsonify({
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': expires_in,
            'scope': auth_code.scope,
            'id_token': id_token,
            'refresh_token': refresh_token.refresh_token,
        })

    if grant_type == 'refresh_token':
        client_id, client_secret = _oauth_extract_client_credentials()
        refresh_token_value = request.form.get('refresh_token', '').strip()
        resource_raw = request.form.get('resource', '').strip()
        if not client_id or not refresh_token_value:
            return _oauth_error_response('invalid_request', 'client_id and refresh_token are required.')

        client = OAuthClient.query.filter_by(client_id=client_id).first()
        if not client:
            return _oauth_error_response('invalid_client', 'Unknown OAuth client.', 401)
        if not _oauth_validate_client_secret(client, client_secret):
            return _oauth_error_response('invalid_client', 'client authentication failed.', 401)

        refresh = OAuthRefreshToken.query.filter_by(refresh_token=refresh_token_value, client_id=client_id).first()
        if not refresh:
            return _oauth_error_response('invalid_grant', 'Refresh token is invalid.')
        try:
            requested_resource = _oauth_normalize_mcp_resource(resource_raw)
        except ValueError as exc:
            return _oauth_error_response('invalid_target', str(exc))
        mcp_client = _oauth_client_looks_like_openai_mcp(
            client,
            resource=resource_raw,
        )
        if mcp_client and not refresh.resource:
            _oauth_revoke_refresh_family(refresh)
            db.session.commit()
            _oauth_log_event('oauth_mcp_reauthorization_required', client_id=client_id, user_id=refresh.user_id, grant_type='refresh_token')
            return _oauth_error_response(
                'invalid_grant',
                'Refresh token is not bound to the PetOrlandia MCP resource. Reconnect PetOrlandia in ChatGPT.',
            )
        if refresh.resource and requested_resource and requested_resource != refresh.resource:
            return _oauth_error_response(
                'invalid_target',
                'resource does not match the refresh token.',
            )
        if not refresh.is_active:
            was_reused_or_revoked = bool(refresh.replaced_by_jti or refresh.revoked_at)
            _oauth_revoke_refresh_family(refresh)
            db.session.commit()
            if was_reused_or_revoked:
                _oauth_log_event('oauth_refresh_token_reuse_detected', client_id=client_id, user_id=refresh.user_id, grant_type='refresh_token')
                return _oauth_error_response('invalid_grant', 'Refresh token reuse detected; token family revoked.')
            _oauth_log_event('oauth_refresh_token_expired', client_id=client_id, user_id=refresh.user_id, grant_type='refresh_token')
            return _oauth_error_response('invalid_grant', 'Refresh token is expired.')
        if _oauth_refresh_token_requires_mcp_reauthorization(refresh, client):
            _oauth_revoke_refresh_family(refresh)
            db.session.commit()
            _oauth_log_event('oauth_mcp_reauthorization_required', client_id=client_id, user_id=refresh.user_id, grant_type='refresh_token')
            return _oauth_error_response(
                'invalid_grant',
                'Refresh token is missing the current clinical scopes. Reconnect PetOrlandia in ChatGPT to authorize pets:read, exams:write and the remaining clinical scopes.',
            )

        return _oauth_issue_refresh_grant_response(refresh)

    return _oauth_error_response('unsupported_grant_type', 'Only authorization_code and refresh_token grants are supported.')


@bp.route("/oauth/register", methods=["POST"])
@csrf.exempt
def oauth_dynamic_client_registration():
    payload = request.get_json(silent=True) or {}

    redirect_uris = payload.get('redirect_uris')
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _oauth_error_response('invalid_redirect_uri', 'redirect_uris must be a non-empty array of HTTPS URLs.')

    normalized_redirect_uris = []
    for uri in redirect_uris:
        candidate = (uri or '').strip()
        parsed = urlparse(candidate)
        if not candidate or parsed.scheme.lower() != 'https' or not parsed.netloc:
            return _oauth_error_response('invalid_redirect_uri', 'redirect_uris must contain only HTTPS URLs.')
        normalized_redirect_uris.append(candidate)

    supported_grants = {'authorization_code', 'refresh_token'}
    grant_types = payload.get('grant_types') or ['authorization_code']
    if not isinstance(grant_types, list) or not grant_types or any(g not in supported_grants for g in grant_types):
        return _oauth_error_response('invalid_client_metadata', 'Unsupported grant_types requested.')

    response_types = payload.get('response_types') or ['code']
    if not isinstance(response_types, list) or set(response_types) != {'code'}:
        return _oauth_error_response('invalid_client_metadata', 'Only response_types=["code"] is supported.')

    token_endpoint_auth_method = (payload.get('token_endpoint_auth_method') or 'none').strip()
    if token_endpoint_auth_method not in {'none', 'client_secret_post', 'client_secret_basic'}:
        return _oauth_error_response('invalid_client_metadata', 'Unsupported token_endpoint_auth_method.')

    requested_scope = str(payload.get('scope') or '').strip()
    if (
        _oauth_registration_looks_like_openai_mcp(payload, normalized_redirect_uris)
        and _oauth_scope_needs_mcp_recovery(requested_scope)
    ):
        requested_scope = _oauth_default_mcp_scope()
    scope = _oauth_normalize_scope(requested_scope) if requested_scope else _oauth_order_scopes(_oauth_allowed_scopes())
    if not scope:
        return _oauth_error_response('invalid_scope', 'No valid scope was requested.')

    client = OAuthClient(
        client_id=secrets.token_urlsafe(24),
        client_secret=secrets.token_urlsafe(32) if token_endpoint_auth_method in {'client_secret_post', 'client_secret_basic'} else None,
        name=str(payload.get('client_name') or 'Dynamic Client').strip()[:120] or 'Dynamic Client',
        redirect_uris='\n'.join(normalized_redirect_uris),
        grant_types=' '.join(grant_types),
        scopes=scope,
        auth_method=token_endpoint_auth_method,
        is_confidential=token_endpoint_auth_method in {'client_secret_post', 'client_secret_basic'},
    )
    db.session.add(client)
    db.session.commit()

    response_payload = {
        'client_id': client.client_id,
        'client_id_issued_at': int(client.created_at.timestamp()) if client.created_at else int(utcnow().timestamp()),
        'client_name': client.name,
        'redirect_uris': normalized_redirect_uris,
        'grant_types': grant_types,
        'response_types': ['code'],
        'token_endpoint_auth_method': token_endpoint_auth_method,
        'scope': scope,
    }
    if client.client_secret:
        response_payload['client_secret'] = client.client_secret
        response_payload['client_secret_expires_at'] = 0

    return jsonify(response_payload), 201


@bp.route("/.well-known/openid-configuration", methods=["GET"])
@bp.route("/.well-known/oauth-authorization-server", methods=["GET"], endpoint="oauth_authorization_server_metadata")
def openid_configuration():
    issuer = _oauth_issuer()
    return jsonify({
        'issuer': issuer,
        'authorization_endpoint': f'{issuer}/oauth/authorize',
        'token_endpoint': f'{issuer}/oauth/token',
        'userinfo_endpoint': f'{issuer}/oauth/userinfo',
        'jwks_uri': f'{issuer}/.well-known/jwks.json',
        'registration_endpoint': f'{issuer}/oauth/register',
        'response_types_supported': ['code'],
        'subject_types_supported': ['public'],
        'id_token_signing_alg_values_supported': ['RS256'],
        # Single source of truth: derived from OAUTH_ALLOWED_SCOPES so the
        # authorization-server metadata, the protected-resource metadata and
        # the consent screen never drift apart.
        'scopes_supported': _oauth_order_scopes(_oauth_allowed_scopes()).split(),
        'token_endpoint_auth_methods_supported': ['none', 'client_secret_post', 'client_secret_basic'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'claims_supported': ['sub', 'email', 'name'],
        # PKCE (RFC 7636) — required by Claude and ChatGPT connectors
        'code_challenge_methods_supported': ['S256'],
    })


@bp.route("/.well-known/jwks.json", methods=["GET"])
def jwks():
    keys = []
    for key in OAuthJwkKey.public_key_set():
        keys.append(JsonWebKey.import_key(key.public_pem.encode('utf-8'), {'kid': key.kid}).as_dict(is_private=False))
    if not keys:
        _, public_jwk = _oauth_get_signing_keys()
        keys = [public_jwk.as_dict(is_private=False)]
    return jsonify({'keys': keys})


@bp.route("/oauth/userinfo", methods=["GET"])
def oauth_userinfo():
    access_token = _oauth_extract_bearer_token()
    if not access_token:
        return _oauth_error_response('invalid_request', 'Missing bearer access token.', 401)

    token = OAuthAccessToken.query.filter_by(access_token=access_token).first()
    if not token or not token.is_active:
        return _oauth_error_response('invalid_token', 'Access token is invalid or expired.', 401)

    user = db.session.get(User, token.user_id)
    if not user:
        return _oauth_error_response('invalid_token', 'Token subject no longer exists.', 401)

    return jsonify({'sub': str(user.id), 'email': user.email, 'name': user.name})


@bp.route("/oauth/revoke", methods=["POST"])
@csrf.exempt
def oauth_revoke():
    token_value = request.form.get('token', '').strip()
    if not token_value:
        return _oauth_error_response('invalid_request', 'token is required.')

    token = OAuthAccessToken.query.filter_by(access_token=token_value).first()
    if token and token.revoked_at is None:
        token.revoke()
        db.session.add(token)
        if token.refresh_token_id:
            refresh = db.session.get(OAuthRefreshToken, token.refresh_token_id)
            if refresh and refresh.revoked_at is None:
                _oauth_revoke_refresh_family(refresh)
        db.session.commit()
        _oauth_log_event('oauth_token_revoked', client_id=token.client_id, user_id=token.user_id, grant_type='token_revoke')

    return ('', 200)


@bp.route("/oauth/introspect", methods=["POST"])
@csrf.exempt
def oauth_introspect():
    token_value = request.form.get('token', '').strip()
    if not token_value:
        return _oauth_error_response('invalid_request', 'token is required.')

    token = OAuthAccessToken.query.filter_by(access_token=token_value).first()
    if not token or not token.is_active:
        return jsonify({'active': False})

    return jsonify({
        'active': True,
        'client_id': token.client_id,
        'scope': token.scope,
        'sub': str(token.user_id),
        'token_type': token.token_type,
        'exp': int(token.expires_at.timestamp()),
    })

