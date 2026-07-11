"""Privacy-preserving product funnel events emitted as structured logs."""

from __future__ import annotations

from flask import current_app, g, request
from flask_login import current_user


def track_event(name: str, *, source: str | None = None, **properties) -> None:
    safe_properties = {
        key: value
        for key, value in properties.items()
        if key in {"city", "role", "service", "category", "channel", "success"}
        and value is not None
    }
    current_app.logger.info(
        "product_event",
        extra={
            "event_name": name,
            "event_source": source or request.args.get("utm_source"),
            "event_user_id": getattr(current_user, "id", None) if current_user.is_authenticated else None,
            "event_role": getattr(current_user, "role", None) if current_user.is_authenticated else None,
            "event_path": request.path,
            "event_request_id": getattr(g, "request_id", None),
            "event_properties": safe_properties,
        },
    )
