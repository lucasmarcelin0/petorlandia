"""Privacy-preserving product funnel events persisted and mirrored to logs."""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from flask import current_app, g, request, session
from flask_login import current_user

from extensions import db


_SAFE_PROPERTY_KEYS = {
    "city", "role", "service", "category", "channel", "success", "stage",
    "plan", "feature", "source_path", "link_text",
}


def _tracking_context() -> tuple[str, str, dict]:
    anonymous_id = session.get("analytics_anonymous_id")
    if not anonymous_id:
        anonymous_id = secrets.token_urlsafe(18)
        session["analytics_anonymous_id"] = anonymous_id

    session_id = session.get("analytics_session_id")
    if not session_id:
        session_id = secrets.token_urlsafe(18)
        session["analytics_session_id"] = session_id

    incoming = {
        key: (request.args.get(key) or "").strip()[:160]
        for key in ("utm_source", "utm_medium", "utm_campaign")
        if (request.args.get(key) or "").strip()
    }
    if incoming:
        if not session.get("analytics_first_touch"):
            session["analytics_first_touch"] = incoming
        session["analytics_last_touch"] = incoming

    attribution = (
        session.get("analytics_last_touch")
        or session.get("analytics_first_touch")
        or {}
    )
    return anonymous_id, session_id, attribution


def track_event(name: str, *, source: str | None = None, **properties) -> None:
    safe_properties = {
        key: value
        for key, value in properties.items()
        if key in _SAFE_PROPERTY_KEYS
        and value is not None
    }
    anonymous_id, session_id, attribution = _tracking_context()
    source_path = str(
        safe_properties.pop("source_path", None) or request.path
    )[:300]
    referrer_host = None
    if request.referrer:
        try:
            referrer_host = (urlparse(request.referrer).hostname or "")[:180] or None
        except ValueError:
            referrer_host = None

    try:
        from models import ProductEvent

        db.session.add(ProductEvent(
            event_name=str(name)[:80],
            anonymous_id=anonymous_id,
            session_id=session_id,
            user_id=(
                getattr(current_user, "id", None)
                if current_user.is_authenticated
                else None
            ),
            source_path=source_path,
            referrer_host=referrer_host,
            utm_source=(source or attribution.get("utm_source") or "")[:120] or None,
            utm_medium=(attribution.get("utm_medium") or "")[:120] or None,
            utm_campaign=(attribution.get("utm_campaign") or "")[:160] or None,
            properties=safe_properties,
        ))
        db.session.commit()
    except Exception:  # telemetry must never block the product
        db.session.rollback()
        current_app.logger.warning("product_event_persist_failed", exc_info=True)

    current_app.logger.info(
        "product_event",
        extra={
            "event_name": name,
            "event_source": source or attribution.get("utm_source"),
            "event_user_id": getattr(current_user, "id", None) if current_user.is_authenticated else None,
            "event_role": getattr(current_user, "role", None) if current_user.is_authenticated else None,
            "event_path": source_path,
            "event_request_id": getattr(g, "request_id", None),
            "event_properties": safe_properties,
        },
    )
