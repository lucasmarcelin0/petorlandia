"""Provider OAuth 2.0/OIDC — helpers de domínio (tokens, scopes, PKCE, JWKS).

Extraído de app.py na modularização. Usado por blueprints/oauth.py e pelo
servidor MCP. Não contém views; apenas lógica do provider.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse

from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import current_app, g, has_request_context, jsonify, request

from extensions import db
from helpers import has_veterinarian_profile
from models import (
    OAuthAccessToken,
    OAuthClient,
    OAuthJwkKey,
    OAuthRefreshToken,
    User,
)
from time_utils import utcnow

_OAUTH_PRIVATE_JWK = None
_OAUTH_PUBLIC_JWK = None


def _oauth_issuer() -> str:
    configured = (current_app.config.get('OAUTH_ISSUER') or '').strip()
    if configured:
        return configured.rstrip('/')
    return request.url_root.rstrip('/') if has_request_context() else ''


def _oauth_get_signing_keys():
    global _OAUTH_PRIVATE_JWK, _OAUTH_PUBLIC_JWK
    if _OAUTH_PRIVATE_JWK is not None and _OAUTH_PUBLIC_JWK is not None:
        return _OAUTH_PRIVATE_JWK, _OAUTH_PUBLIC_JWK

    active_key = OAuthJwkKey.active_key()
    if active_key is None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        active_key = OAuthJwkKey(
            kid=OAuthJwkKey.build_kid(public_pem),
            kty='RSA',
            private_pem=private_pem.decode('utf-8'),
            public_pem=public_pem.decode('utf-8'),
            status='active',
            valid_from=utcnow(),
        )
        db.session.add(active_key)
        db.session.commit()

    _OAUTH_PRIVATE_JWK = JsonWebKey.import_key(active_key.private_pem.encode('utf-8'), {'kid': active_key.kid})
    _OAUTH_PUBLIC_JWK = JsonWebKey.import_key(active_key.public_pem.encode('utf-8'), {'kid': active_key.kid})
    return _OAUTH_PRIVATE_JWK, _OAUTH_PUBLIC_JWK


def _oauth_rotate_signing_key(grace_seconds: int = 86400):
    current = OAuthJwkKey.active_key()
    now = utcnow()

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    next_key = OAuthJwkKey(
        kid=OAuthJwkKey.build_kid(public_pem),
        kty='RSA',
        private_pem=private_pem.decode('utf-8'),
        public_pem=public_pem.decode('utf-8'),
        status='active',
        valid_from=now,
        rotated_from_kid=current.kid if current else None,
    )

    if current is not None:
        current.status = 'retired'
        current.valid_until = now
        current.grace_until = now + timedelta(seconds=grace_seconds)
        db.session.add(current)

    db.session.add(next_key)
    db.session.commit()

    global _OAUTH_PRIVATE_JWK, _OAUTH_PUBLIC_JWK
    _OAUTH_PRIVATE_JWK = None
    _OAUTH_PUBLIC_JWK = None
    return _oauth_get_signing_keys()


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')


def _oauth_error_response(error: str, description: str, status_code: int = 400):
    return jsonify({'error': error, 'error_description': description}), status_code


def _oauth_allowed_scopes() -> set[str]:
    configured = current_app.config.get(
        'OAUTH_ALLOWED_SCOPES',
        (
            'openid profile email '
            'pets:read appointments:read tutors:read tutors:write pets:write '
            'appointments:write consultations:write exams:write '
            'clinical_summary:read consultations:read prescriptions:read '
            'exams:read vaccines:read handoff:read tutor_guidance:generate'
        ),
    )
    return {scope.strip() for scope in str(configured).split() if scope.strip()}


def _oauth_order_scopes(scopes: Iterable[str]) -> str:
    requested = {item.strip() for item in scopes if item and item.strip()}
    scope_order = [
        'openid',
        'profile',
        'email',
        'pets:read',
        'appointments:read',
        'tutors:read',
        'tutors:write',
        'pets:write',
        'appointments:write',
        'consultations:write',
        'exams:write',
        'clinical_summary:read',
        'consultations:read',
        'prescriptions:read',
        'exams:read',
        'vaccines:read',
        'handoff:read',
        'tutor_guidance:generate',
    ]
    ordered_scopes = [scope for scope in scope_order if scope in requested]
    ordered_scopes.extend(sorted(requested.difference(set(scope_order))))
    return ' '.join(ordered_scopes)


def _oauth_veterinarian_write_scopes() -> set[str]:
    return {
        'tutors:write',
        'pets:write',
        'appointments:write',
        'consultations:write',
        'exams:write',
    }


_OAUTH_IDENTITY_SCOPES = {'openid', 'profile', 'email'}
_OAUTH_MCP_SCOPE_SENTINELS = {'pets:read', 'exams:read', 'exams:write'}


def _oauth_scope_tokens(scope_value: str | None) -> set[str]:
    return {item.strip() for item in (scope_value or '').split() if item.strip()}


def _oauth_default_mcp_scope() -> str:
    return _oauth_order_scopes(_oauth_allowed_scopes())


def _oauth_scope_needs_mcp_recovery(scope_value: str | None) -> bool:
    requested = _oauth_scope_tokens(scope_value)
    return not requested or requested.issubset(_OAUTH_IDENTITY_SCOPES)


def _oauth_client_looks_like_openai_mcp(
    client: OAuthClient | None,
    *,
    redirect_uri: str = '',
    resource: str = '',
) -> bool:
    if client is None:
        return False

    values = ' '.join(
        value
        for value in (
            getattr(client, 'name', ''),
            getattr(client, 'client_id', ''),
            getattr(client, 'redirect_uris', ''),
            redirect_uri,
            resource,
        )
        if value
    ).lower()
    resource_value = (resource or '').strip().rstrip('/').lower()
    expected_resource = f'{_oauth_issuer().rstrip("/")}/mcp'.lower()

    has_chatgpt_marker = (
        'chatgpt' in values
        or 'chat.openai.com' in values
        or 'openai' in (getattr(client, 'name', '') or '').lower()
    )
    has_mcp_marker = (
        resource_value == expected_resource
        or values.find('/connector/') != -1
        or values.find('/aip/') != -1
        or ' mcp' in values
        or values.endswith('mcp')
    )
    return has_chatgpt_marker and has_mcp_marker


def _oauth_registration_looks_like_openai_mcp(payload: dict, redirect_uris: list[str]) -> bool:
    client_name = str(payload.get('client_name') or '').lower()
    resource = str(payload.get('resource') or '').strip().rstrip('/').lower()
    expected_resource = f'{_oauth_issuer().rstrip("/")}/mcp'.lower()
    values = ' '.join([client_name, *redirect_uris, resource]).lower()
    has_chatgpt_marker = 'chatgpt' in values or 'chat.openai.com' in values or 'openai' in client_name
    has_mcp_marker = (
        resource == expected_resource
        or values.find('/connector/') != -1
        or values.find('/aip/') != -1
        or ' mcp' in values
        or values.endswith('mcp')
    )
    return has_chatgpt_marker and has_mcp_marker


def _oauth_ensure_mcp_client_scopes(client: OAuthClient) -> bool:
    current_scopes = _oauth_scope_tokens(client.scopes)
    desired_scopes = current_scopes.union(_oauth_allowed_scopes())
    if _OAUTH_MCP_SCOPE_SENTINELS.issubset(current_scopes):
        return False

    client.scopes = _oauth_order_scopes(desired_scopes)
    db.session.add(client)
    return True


def _oauth_access_token_requires_mcp_reauthorization(token: OAuthAccessToken) -> bool:
    if not _oauth_scope_needs_mcp_recovery(token.scope):
        return False
    client = OAuthClient.query.filter_by(client_id=token.client_id).first()
    return _oauth_client_looks_like_openai_mcp(client)


def _oauth_refresh_token_requires_mcp_reauthorization(refresh: OAuthRefreshToken, client: OAuthClient) -> bool:
    return _oauth_scope_needs_mcp_recovery(refresh.scope) and _oauth_client_looks_like_openai_mcp(client)


def _oauth_datetime_is_future(value) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > utcnow()


def _oauth_mcp_user_can_receive_clinical_scopes(user_id: int | None) -> bool:
    user = db.session.get(User, user_id) if user_id else None
    return bool(user and has_veterinarian_profile(user))


def _oauth_access_token_can_self_heal_mcp_scope(token: OAuthAccessToken) -> bool:
    return (
        _oauth_access_token_requires_mcp_reauthorization(token)
        and _oauth_mcp_user_can_receive_clinical_scopes(token.user_id)
    )


def _oauth_refresh_token_can_self_heal_mcp_scope(refresh: OAuthRefreshToken, client: OAuthClient) -> bool:
    if refresh.replaced_by_jti:
        return False
    return (
        _oauth_refresh_token_requires_mcp_reauthorization(refresh, client)
        and _oauth_datetime_is_future(refresh.expires_at)
        and _oauth_mcp_user_can_receive_clinical_scopes(refresh.user_id)
    )


# Human-friendly copy for the consent screen, keyed by scope.
# Each value is (group_key, short_label, plain_description) — all in pt-BR so a
# veterinarian sees "Consultar pacientes" instead of the raw "pets:read".
_OAUTH_SCOPE_CATALOG = {
    'openid':                  ('identity', 'Identificar você',             'Confirma quem você é no PetOrlândia.'),
    'profile':                 ('identity', 'Ver seu perfil',              'Seu nome e informações básicas de perfil.'),
    'email':                   ('identity', 'Ver seu e-mail',             'O endereço de e-mail da sua conta.'),
    'pets:read':               ('read',     'Consultar pacientes',         'Ver os pets e seus dados aos quais você tem acesso.'),
    'appointments:read':       ('read',     'Consultar a agenda',          'Ver consultas e agendamentos.'),
    'tutors:read':             ('read',     'Consultar tutores',           'Ver os dados dos tutores dos pacientes.'),
    'clinical_summary:read':   ('read',     'Resumir o histórico clínico', 'Gerar resumos do histórico dos pacientes.'),
    'consultations:read':      ('read',     'Consultar consultas',         'Ver o histórico de consultas clínicas.'),
    'prescriptions:read':      ('read',     'Consultar prescrições',       'Ver prescrições e medicamentos.'),
    'exams:read':              ('read',     'Consultar exames',            'Ver exames, laudos e resultados.'),
    'vaccines:read':           ('read',     'Consultar vacinas',           'Ver o histórico e as pendências de vacinas.'),
    'handoff:read':            ('read',     'Gerar passagem de plantão',   'Montar handoffs clínicos a partir dos dados existentes.'),
    'tutor_guidance:generate': ('read',     'Gerar orientações ao tutor',  'Criar orientações para o tutor a partir do histórico.'),
    'tutors:write':            ('write',    'Cadastrar e editar tutores',  'Criar ou atualizar cadastros de tutores.'),
    'pets:write':              ('write',    'Cadastrar e editar pacientes','Criar ou atualizar cadastros de pets.'),
    'appointments:write':      ('write',    'Agendar consultas e retornos','Criar agendamentos e retornos na agenda.'),
    'consultations:write':     ('write',    'Registrar consultas',         'Salvar novas consultas clínicas.'),
    'exams:write':             ('write',    'Registrar exames e laudos',   'Criar exames, anexar laudos e liberá-los.'),
}

# Display order + copy for the groups shown on the consent screen.
# (group_key, title, Font Awesome icon, reassurance line)
_OAUTH_SCOPE_GROUPS = (
    ('identity', 'Identificação',            'fa-id-badge',         'Para reconhecer a sua conta.'),
    ('read',     'Consultar informações',    'fa-magnifying-glass', 'Somente leitura — não altera nada no sistema.'),
    ('write',    'Registrar e alterar dados','fa-pen-to-square',    'Cria ou atualiza registros. Toda gravação pede a sua confirmação no chat antes de salvar.'),
)


def _oauth_scope_detail(scope: str) -> dict:
    group, label, description = _OAUTH_SCOPE_CATALOG.get(
        scope, ('read', scope, 'Permissão solicitada pelo aplicativo.')
    )
    return {'scope': scope, 'group': group, 'label': label, 'description': description}


def _oauth_scope_details(scopes: Iterable[str]) -> list[dict]:
    """Flat list of friendly scope descriptions in canonical display order."""
    return [_oauth_scope_detail(scope) for scope in _oauth_order_scopes(scopes).split()]


def _oauth_grouped_scope_details(scopes: Iterable[str]) -> list[dict]:
    """Scope descriptions bucketed into the consent-screen groups, skipping
    empty groups and preserving canonical ordering inside each group."""
    details = _oauth_scope_details(scopes)
    groups = []
    for key, title, icon, hint in _OAUTH_SCOPE_GROUPS:
        items = [detail for detail in details if detail['group'] == key]
        if items:
            groups.append({'key': key, 'title': title, 'icon': icon, 'hint': hint, 'perms': items})
    return groups


def _oauth_normalize_scope(scope_raw: str, client: OAuthClient | None = None) -> str:
    requested = {item.strip() for item in (scope_raw or '').split() if item.strip()}
    if not requested:
        requested = {'openid', 'profile', 'email'}

    allowed = _oauth_allowed_scopes()
    if client:
        allowed = allowed.intersection({item.strip() for item in (client.scopes or '').split() if item.strip()})

    if not requested.issubset(allowed):
        raise ValueError('Requested scope is not allowed.')

    return _oauth_order_scopes(requested)


def _oauth_client_redirect_valid(client: OAuthClient, redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.fragment:
        return False

    for allowed_uri in client.redirect_uri_list():
        if allowed_uri in {
            'https://chatgpt.com/connector/oauth/*',
            'https://chat.openai.com/connector/oauth/*',
            'https://chatgpt.com/aip/*/oauth/callback',
            'https://chat.openai.com/aip/*/oauth/callback',
        }:
            if allowed_uri.endswith('/connector/oauth/*'):
                expected_host = urlparse(allowed_uri).netloc
                if (
                    parsed.scheme == 'https'
                    and parsed.netloc == expected_host
                    and re.fullmatch(r'/connector/oauth/[^/?#]+', parsed.path or '')
                    and not parsed.params
                    and not parsed.query
                ):
                    return True
                continue
            if (
                parsed.scheme == 'https'
                and parsed.netloc in {'chatgpt.com', 'chat.openai.com'}
                and re.fullmatch(r'/aip/[^/]+/oauth/callback', parsed.path or '')
                and not parsed.params
                and not parsed.query
            ):
                return True
            continue
        if '*' in allowed_uri:
            continue
        if redirect_uri == allowed_uri:
            return True
    return False


def _oauth_requires_pkce(client: OAuthClient) -> bool:
    return not bool(client.is_confidential)


def _oauth_validate_client_secret(client: OAuthClient, provided_secret: str) -> bool:
    if not client.is_confidential:
        return True
    if client.auth_method not in {'client_secret_post', 'client_secret_basic'}:
        return False
    expected_secret = (client.client_secret or '').strip()
    return bool(expected_secret) and secrets.compare_digest(expected_secret, provided_secret or '')


def _oauth_extract_client_credentials() -> tuple[str, str]:
    client_id = request.form.get('client_id', '').strip()
    client_secret = request.form.get('client_secret', '').strip()

    auth_header = request.headers.get('Authorization', '')
    if auth_header.lower().startswith('basic '):
        encoded = auth_header[6:].strip()
        try:
            decoded = base64.b64decode(encoded).decode('utf-8')
            basic_client_id, basic_client_secret = decoded.split(':', 1)
        except Exception:
            return '', ''
        return basic_client_id.strip(), basic_client_secret

    return client_id, client_secret


def _oauth_extract_bearer_token() -> str | None:
    auth_header = request.headers.get('Authorization', '')
    if auth_header.lower().startswith('bearer '):
        return auth_header[7:].strip()
    return request.values.get('access_token')




def _oauth_log_event(event: str, **fields):
    current_app.logger.info(
        event,
        extra={
            'request_id': getattr(g, 'request_id', None),
            'client_id': fields.get('client_id'),
            'user_id': fields.get('user_id'),
            'grant_type': fields.get('grant_type'),
        },
    )


def _oauth_revoke_refresh_family(refresh_token: OAuthRefreshToken):
    now = utcnow()
    family_tokens = OAuthRefreshToken.query.filter_by(
        client_id=refresh_token.client_id,
        user_id=refresh_token.user_id,
        family_id=refresh_token.family_id,
    ).all()
    token_ids = [token.id for token in family_tokens]
    for token in family_tokens:
        if token.revoked_at is None:
            token.revoked_at = now
            db.session.add(token)

    if token_ids:
        for access in OAuthAccessToken.query.filter(OAuthAccessToken.refresh_token_id.in_(token_ids)).all():
            if access.revoked_at is None:
                access.revoked_at = now
                db.session.add(access)


def _oauth_issue_refresh_grant_response(
    refresh: OAuthRefreshToken,
    *,
    scope: str | None = None,
    log_event: str = 'oauth_token_issued',
):
    now = utcnow()
    refresh_expires_in = int(current_app.config.get('OAUTH_REFRESH_TOKEN_EXPIRES_IN', 2592000))
    access_expires_in = int(current_app.config.get('OAUTH_ACCESS_TOKEN_EXPIRES_IN', 900))
    granted_scope = scope or refresh.scope

    new_refresh = OAuthRefreshToken(
        client_id=refresh.client_id,
        user_id=refresh.user_id,
        refresh_token=secrets.token_urlsafe(48),
        scope=granted_scope,
        family_id=refresh.family_id,
        expires_at=now + timedelta(seconds=refresh_expires_in),
    )
    db.session.add(new_refresh)
    db.session.flush()

    refresh.revoked_at = now
    refresh.replaced_by_jti = new_refresh.jti
    db.session.add(refresh)

    new_access = OAuthAccessToken(
        client_id=refresh.client_id,
        user_id=refresh.user_id,
        access_token=secrets.token_urlsafe(48),
        token_type='Bearer',
        scope=granted_scope,
        refresh_token_id=new_refresh.id,
        expires_at=now + timedelta(seconds=access_expires_in),
    )
    db.session.add(new_access)
    db.session.commit()
    _oauth_log_event(log_event, client_id=refresh.client_id, user_id=refresh.user_id, grant_type='refresh_token')

    return jsonify({
        'access_token': new_access.access_token,
        'token_type': 'Bearer',
        'expires_in': access_expires_in,
        'scope': granted_scope,
        'refresh_token': new_refresh.refresh_token,
    })


















# ─────────────────────────────────────────────────────────────────────────────
# MCP SERVER  (Model Context Protocol — JSON-RPC 2.0 over HTTP)
# Endpoint: GET|POST /mcp
# Auth:     Bearer token (issued by /oauth/token)
# Discovery: /.well-known/oauth-protected-resource  (RFC 9396 / MCP spec)
# Clients:  Claude, ChatGPT, and any MCP-compatible AI assistant
# ─────────────────────────────────────────────────────────────────────────────

