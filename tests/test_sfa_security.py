import os

from extensions import db
from models import User


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_sfa_dashboard_requires_auth_or_token(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_ADMIN_TOKEN", raising=False)
    app.config["TESTING"] = False

    response = client.get("/sfa/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_sfa_dashboard_allows_admin_session(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_ADMIN_TOKEN", raising=False)
    app.config["TESTING"] = False

    with app.app_context():
        admin = User(name="Admin", email="admin-sfa@test", password_hash="x", role="admin")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    response = client.get("/sfa/")

    assert response.status_code == 200


def test_sfa_dashboard_allows_admin_token(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.setenv("SFA_ADMIN_TOKEN", "token-sfa-teste")
    app.config["TESTING"] = False

    response = client.get("/sfa/", headers={"X-SFA-Token": "token-sfa-teste"})

    assert response.status_code == 200


def test_sfa_webhook_requires_secret_outside_testing(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.delenv("SFA_WEBHOOK_SECRET", raising=False)
    app.config["TESTING"] = False

    response = client.post("/sfa/webhook/t0", json={})

    assert response.status_code == 403


def test_sfa_webhook_accepts_configured_secret(app, client, monkeypatch):
    monkeypatch.setenv("SFA_ALLOW_OPEN_ACCESS", "0")
    monkeypatch.setenv("SFA_WEBHOOK_SECRET", "segredo-webhook")
    app.config["TESTING"] = False

    response = client.post(
        "/sfa/webhook/t0",
        json={
            "id_estudo": "SFA-001",
            "nome": "Participante Teste",
            "data_nascimento": "2000-01-01",
        },
        headers={"X-SFA-Secret": "segredo-webhook"},
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
