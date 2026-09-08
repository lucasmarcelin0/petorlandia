from __future__ import annotations

from authz import _audit_authz_decision, summarize_authz_denials


class _User:
    def __init__(self, user_id: int):
        self.id = user_id


def test_authz_denial_metrics_group_by_route_user_ip(app):
    from authz import _DENY_EVENTS_WINDOW
    _DENY_EVENTS_WINDOW.clear()
    with app.test_request_context(
        "/rota-protegida/12345678901", headers={"User-Agent": "pytest-agent", "X-Forwarded-For": "203.0.113.10"}
    ):
        _audit_authz_decision(
            user=_User(7),
            role="staff",
            resource="consultation:view",
            resource_identifier="consulta-12345678901",
            allowed=False,
            reason="fora_do_escopo_clinica",
        )

    snapshot = summarize_authz_denials(window_minutes=10)
    assert snapshot["total_denies"] >= 1
    assert any(item["key"] == "/rota-protegida/12345678901" for item in snapshot["by_route"])
    assert any(item["key"] == "7" for item in snapshot["by_user"])
    assert any(item["key"] == "203.0.113.10" for item in snapshot["by_ip"])


def test_summarize_authz_denials_aggregation_and_cutoff():
    from datetime import datetime, timedelta, timezone
    from authz import _DENY_EVENTS_WINDOW, summarize_authz_denials

    _DENY_EVENTS_WINDOW.clear()
    now = datetime.now(timezone.utc)

    # Add recent events
    _DENY_EVENTS_WINDOW.extend([
        {"at": now, "route": "/r1", "user_id": 1, "ip": "1.1.1.1"},
        {"at": now - timedelta(minutes=1), "route": "/r1", "user_id": 1, "ip": "2.2.2.2"},
        {"at": now - timedelta(minutes=2), "route": "/r2", "user_id": 2, "ip": "1.1.1.1"},
        {"at": now - timedelta(minutes=3), "route": "/r3", "user_id": 3, "ip": "3.3.3.3"},
        {"at": now - timedelta(minutes=4), "route": "/r4", "user_id": 4, "ip": "4.4.4.4"},
        {"at": now - timedelta(minutes=4.5), "route": "/r5", "user_id": 5, "ip": "5.5.5.5"},
    ])

    # Add old event (past 5 minutes)
    _DENY_EVENTS_WINDOW.append(
        {"at": now - timedelta(minutes=10), "route": "/old", "user_id": 99, "ip": "9.9.9.9"}
    )

    summary = summarize_authz_denials(window_minutes=5, top_n=2)

    assert summary["window_minutes"] == 5
    assert summary["total_denies"] == 6

    assert summary["by_route"][0] == {"key": "/r1", "count": 2}
    assert len(summary["by_route"]) == 2

    assert summary["by_user"][0] == {"key": "1", "count": 2}
    assert len(summary["by_user"]) == 2

    assert summary["by_ip"][0] == {"key": "1.1.1.1", "count": 2}
    assert len(summary["by_ip"]) == 2

