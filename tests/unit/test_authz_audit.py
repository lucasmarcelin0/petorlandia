from __future__ import annotations

from authz import _audit_authz_decision, summarize_authz_denials


class _User:
    def __init__(self, user_id: int):
        self.id = user_id


def test_authz_denial_metrics_group_by_route_user_ip(app):
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
