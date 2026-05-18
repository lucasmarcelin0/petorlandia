"""Mercado Pago OAuth helpers for marketplace sellers."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import requests
from flask import current_app, url_for

from time_utils import utcnow


MERCADO_PAGO_AUTH_URL = "https://auth.mercadopago.com.br/authorization"
MERCADO_PAGO_TOKEN_URL = "https://api.mercadopago.com/oauth/token"


class MercadoPagoOAuthError(RuntimeError):
    """Raised when Mercado Pago OAuth cannot complete safely."""


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    state: str
    code_verifier: str | None


@dataclass(frozen=True)
class OAuthCredentials:
    access_token: str
    refresh_token: str | None
    public_key: str | None
    provider_user_id: str | None
    expires_at: object | None


@dataclass(frozen=True)
class RenewalResult:
    checked: int
    renewed: int
    failed: int


def build_redirect_uri() -> str:
    configured = (current_app.config.get("MERCADOPAGO_OAUTH_REDIRECT_URI") or "").strip()
    if configured:
        return configured
    return url_for("mercadopago_oauth_callback", _external=True)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_start() -> OAuthStart:
    client_id = (current_app.config.get("MERCADOPAGO_CLIENT_ID") or "").strip()
    if not client_id:
        raise MercadoPagoOAuthError("MERCADOPAGO_CLIENT_ID nao configurado.")

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "platform_id": "mp",
        "state": state,
        "redirect_uri": build_redirect_uri(),
    }

    code_verifier = None
    if current_app.config.get("MERCADOPAGO_OAUTH_USE_PKCE", True):
        code_verifier = secrets.token_urlsafe(64)
        params["code_challenge"] = _pkce_challenge(code_verifier)
        params["code_challenge_method"] = "S256"

    return OAuthStart(
        authorization_url=f"{MERCADO_PAGO_AUTH_URL}?{urlencode(params)}",
        state=state,
        code_verifier=code_verifier,
    )


def exchange_code_for_credentials(code: str, code_verifier: str | None = None) -> OAuthCredentials:
    client_id = (current_app.config.get("MERCADOPAGO_CLIENT_ID") or "").strip()
    client_secret = (current_app.config.get("MERCADOPAGO_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise MercadoPagoOAuthError("Credenciais OAuth do Mercado Pago nao configuradas.")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": build_redirect_uri(),
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    try:
        response = requests.post(MERCADO_PAGO_TOKEN_URL, data=payload, timeout=15)
    except requests.RequestException as exc:
        raise MercadoPagoOAuthError("Falha ao conectar com o Mercado Pago.") from exc

    if response.status_code >= 400:
        raise MercadoPagoOAuthError("Mercado Pago recusou a autorizacao.")

    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        raise MercadoPagoOAuthError("Mercado Pago retornou credenciais invalidas.")

    expires_in = data.get("expires_in")
    expires_at = None
    if expires_in:
        try:
            expires_at = utcnow() + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None

    return OAuthCredentials(
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        public_key=data.get("public_key"),
        provider_user_id=str(data.get("user_id")) if data.get("user_id") else None,
        expires_at=expires_at,
    )


def refresh_credentials(refresh_token: str) -> OAuthCredentials:
    client_id = (current_app.config.get("MERCADOPAGO_CLIENT_ID") or "").strip()
    client_secret = (current_app.config.get("MERCADOPAGO_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise MercadoPagoOAuthError("Credenciais OAuth do Mercado Pago nao configuradas.")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        response = requests.post(MERCADO_PAGO_TOKEN_URL, data=payload, timeout=15)
    except requests.RequestException as exc:
        raise MercadoPagoOAuthError("Falha ao conectar com o Mercado Pago.") from exc

    if response.status_code >= 400:
        raise MercadoPagoOAuthError("Mercado Pago recusou a renovacao.")

    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        raise MercadoPagoOAuthError("Mercado Pago retornou credenciais invalidas.")

    expires_in = data.get("expires_in")
    expires_at = None
    if expires_in:
        try:
            expires_at = utcnow() + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None

    return OAuthCredentials(
        access_token=access_token,
        refresh_token=data.get("refresh_token") or refresh_token,
        public_key=data.get("public_key"),
        provider_user_id=str(data.get("user_id")) if data.get("user_id") else None,
        expires_at=expires_at,
    )


def renew_due_store_accounts(db, StorePaymentAccount, *, days_before_expiry: int = 30) -> RenewalResult:
    threshold = utcnow() + timedelta(days=days_before_expiry)
    accounts = (
        StorePaymentAccount.query
        .filter_by(provider="mercado_pago", status="connected")
        .filter(StorePaymentAccount.refresh_token_encrypted.isnot(None))
        .filter(
            (StorePaymentAccount.token_expires_at.is_(None))
            | (StorePaymentAccount.token_expires_at <= threshold)
        )
        .all()
    )

    renewed = 0
    failed = 0
    for account in accounts:
        try:
            credentials = refresh_credentials(account.refresh_token)
            account.access_token = credentials.access_token
            account.refresh_token = credentials.refresh_token
            if credentials.public_key:
                account.public_key = credentials.public_key
            if credentials.provider_user_id:
                account.provider_user_id = credentials.provider_user_id
            account.token_expires_at = credentials.expires_at
            account.last_refreshed_at = utcnow()
            account.status = "connected"
            account.error_message = None
            renewed += 1
        except Exception as exc:  # noqa: BLE001 - status must persist for dashboard/support
            account.status = "error"
            account.error_message = str(exc)
            failed += 1
        db.session.add(account)

    db.session.commit()
    return RenewalResult(checked=len(accounts), renewed=renewed, failed=failed)
