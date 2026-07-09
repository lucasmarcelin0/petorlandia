"""Web Push (VAPID) — inscrições e envio best-effort.

Config esperada (env):
    VAPID_PUBLIC_KEY   — chave pública base64url (uncompressed point)
    VAPID_PRIVATE_KEY  — chave privada base64url
    VAPID_CLAIM_EMAIL  — e-mail de contato exigido pelo protocolo

Sem as chaves configuradas o módulo vira no-op silencioso: nenhuma rota
quebra, apenas não há push. O envio nunca levanta exceção para o chamador —
push é canal complementar, não crítico.
"""
from __future__ import annotations

import hashlib
import json

from flask import current_app

from extensions import db
from time_utils import utcnow

# Depois de tantas falhas consecutivas a inscrição é considerada morta.
_MAX_FAILS = 5


def push_enabled() -> bool:
    return bool(
        current_app.config.get('VAPID_PUBLIC_KEY')
        and current_app.config.get('VAPID_PRIVATE_KEY')
    )


def vapid_public_key() -> str | None:
    return current_app.config.get('VAPID_PUBLIC_KEY') or None


def _endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode('utf-8')).hexdigest()


def save_subscription(user_id: int, subscription: dict, user_agent: str | None = None):
    """Cria/atualiza a inscrição do navegador (upsert por endpoint)."""
    from models import PushSubscription

    endpoint = (subscription.get('endpoint') or '').strip()
    keys = subscription.get('keys') or {}
    p256dh = (keys.get('p256dh') or '').strip()
    auth = (keys.get('auth') or '').strip()
    if not endpoint or not p256dh or not auth:
        raise ValueError('Inscrição de push incompleta.')

    ehash = _endpoint_hash(endpoint)
    sub = PushSubscription.query.filter_by(endpoint_hash=ehash).first()
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, endpoint_hash=ehash)
        db.session.add(sub)
    # O endpoint pode trocar de dono (logout/login no mesmo navegador).
    sub.user_id = user_id
    sub.p256dh = p256dh
    sub.auth = auth
    sub.user_agent = (user_agent or '')[:255] or None
    sub.fail_count = 0
    db.session.commit()
    return sub


def delete_subscription(user_id: int, endpoint: str) -> bool:
    from models import PushSubscription

    sub = PushSubscription.query.filter_by(
        endpoint_hash=_endpoint_hash(endpoint or ''), user_id=user_id
    ).first()
    if not sub:
        return False
    db.session.delete(sub)
    db.session.commit()
    return True


def push_to_user(user_id: int, title: str, body: str, url: str | None = None, tag: str | None = None) -> int:
    """Envia push para todos os dispositivos do usuário. Retorna nº de envios OK.

    Best-effort: erros são logados, inscrições mortas (404/410) removidas.
    """
    if not push_enabled():
        return 0

    from models import PushSubscription

    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    if not subs:
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # pragma: no cover - dependência opcional ausente
        current_app.logger.warning('pywebpush não instalado; push desabilitado.')
        return 0

    payload = json.dumps({
        'title': title,
        'body': body,
        'url': url or '/',
        'tag': tag or 'petorlandia',
    }, ensure_ascii=False)

    claims_email = current_app.config.get('VAPID_CLAIM_EMAIL') or 'mailto:contato@petorlandia.com.br'
    if not claims_email.startswith('mailto:'):
        claims_email = f'mailto:{claims_email}'

    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=current_app.config['VAPID_PRIVATE_KEY'],
                vapid_claims={'sub': claims_email},
                ttl=86400,
            )
            sub.last_success_at = utcnow()
            sub.fail_count = 0
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status in (404, 410):
                db.session.delete(sub)
            else:
                sub.fail_count = (sub.fail_count or 0) + 1
                if sub.fail_count >= _MAX_FAILS:
                    db.session.delete(sub)
                current_app.logger.warning('Falha de push (%s) p/ user %s: %s', status, user_id, exc)
        except Exception as exc:  # noqa: BLE001 - push nunca derruba o chamador
            current_app.logger.warning('Erro inesperado de push p/ user %s: %s', user_id, exc)

    try:
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
    return sent


def push_to_users(user_ids, title: str, body: str, url: str | None = None, tag: str | None = None) -> int:
    total = 0
    for uid in set(u for u in user_ids if u):
        total += push_to_user(uid, title, body, url=url, tag=tag)
    return total
