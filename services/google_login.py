"""Login com Google (OAuth 2.0 + OpenID Connect).

Usa apenas ``requests`` e ``google-auth``, que já são dependências do projeto.
O fluxo é o authorization code padrão:

1. ``build_authorization_url`` leva o usuário ao consentimento do Google;
2. o Google devolve um ``code`` no callback;
3. ``exchange_code`` troca o code por um ``id_token`` assinado;
4. ``verify_id_token`` valida assinatura, emissor, audiência e validade.

Quando as credenciais não estão configuradas, ``is_enabled()`` retorna False e
a interface simplesmente não oferece o botão — nada quebra.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests
from flask import current_app
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

AUTHORIZATION_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
SCOPES = 'openid email profile'

#: Chave de sessão onde guardamos o ``state`` entre a ida e a volta do Google.
STATE_SESSION_KEY = 'google_oauth_state'
#: Chave de sessão com o destino pós-login.
NEXT_SESSION_KEY = 'google_oauth_next'


class GoogleLoginError(Exception):
    """Falha recuperável no fluxo — a view converte em mensagem ao usuário."""


def client_id() -> str | None:
    return (current_app.config.get('GOOGLE_OAUTH_CLIENT_ID') or '').strip() or None


def client_secret() -> str | None:
    return (current_app.config.get('GOOGLE_OAUTH_CLIENT_SECRET') or '').strip() or None


def is_enabled() -> bool:
    """True quando dá para oferecer o botão 'Entrar com Google'."""

    return bool(client_id() and client_secret())


def new_state() -> str:
    """Token anti-CSRF que amarra o callback à sessão que iniciou o fluxo."""

    return secrets.token_urlsafe(32)


def build_authorization_url(redirect_uri: str, state: str) -> str:
    params = {
        'client_id': client_id(),
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': SCOPES,
        'state': state,
        # Sem refresh token: só precisamos identificar a pessoa uma vez.
        'access_type': 'online',
        # Deixa o usuário trocar de conta em vez de reusar a última em silêncio.
        'prompt': 'select_account',
    }
    return f'{AUTHORIZATION_ENDPOINT}?{urlencode(params)}'


def exchange_code(code: str, redirect_uri: str) -> str:
    """Troca o authorization code pelo ``id_token`` (JWT assinado pelo Google)."""

    try:
        response = requests.post(
            TOKEN_ENDPOINT,
            data={
                'code': code,
                'client_id': client_id(),
                'client_secret': client_secret(),
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=15,
        )
    except requests.RequestException as exc:  # noqa: BLE001
        raise GoogleLoginError('Não foi possível falar com o Google.') from exc

    if response.status_code != 200:
        current_app.logger.warning(
            'Troca de code do Google falhou (HTTP %s): %s',
            response.status_code,
            response.text[:400],
        )
        raise GoogleLoginError('O Google recusou a autenticação.')

    token = (response.json() or {}).get('id_token')
    if not token:
        raise GoogleLoginError('O Google não devolveu a identificação da conta.')
    return token


def verify_id_token(token: str) -> dict:
    """Valida o JWT e devolve as claims.

    ``verify_oauth2_token`` confere assinatura, emissor, audiência e expiração —
    é o que impede alguém de forjar um token com o e-mail de outra pessoa.
    """

    try:
        claims = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            client_id(),
        )
    except ValueError as exc:
        current_app.logger.warning('id_token do Google inválido: %s', exc)
        raise GoogleLoginError('Não conseguimos validar sua conta Google.') from exc

    if claims.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'}:
        raise GoogleLoginError('Não conseguimos validar sua conta Google.')

    # Sem e-mail verificado não há prova de posse: seria porta aberta para
    # assumir a conta de outra pessoa que já usa esse endereço aqui.
    if not claims.get('email_verified'):
        raise GoogleLoginError(
            'Sua conta Google está sem e-mail verificado. '
            'Verifique no Google e tente de novo.'
        )

    if not (claims.get('email') or '').strip():
        raise GoogleLoginError('Sua conta Google não expôs um e-mail.')

    return claims
