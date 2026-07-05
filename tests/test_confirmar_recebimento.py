import os

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

import app as app_module  # noqa: F401 — garante rotas registradas
from extensions import db
from models import Order, User


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _make_order(owner_email):
    user = User(name="Tutor Teste", email=owner_email)
    user.set_password("x")
    db.session.add(user)
    db.session.flush()
    order = Order(user_id=user.id)
    db.session.add(order)
    db.session.commit()
    return user, order


def test_buyer_confirms_order_received(app, client, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        buyer, order = _make_order("tutor-recebeu@example.com")
        assert order.received_at is None
        _login(monkeypatch, buyer)

        resp = client.post(f"/pedidos/{order.id}/confirmar-recebimento")
        assert resp.status_code == 302

        db.session.refresh(order)
        assert order.received_at is not None
        first_confirmation = order.received_at

        # Reconfirmar não altera o carimbo original
        resp = client.post(f"/pedidos/{order.id}/confirmar-recebimento")
        assert resp.status_code == 302
        db.session.refresh(order)
        assert order.received_at == first_confirmation


def test_buyer_cannot_confirm_someone_elses_order(app, client, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        _, order = _make_order("dono-do-pedido@example.com")
        intruder = User(name="Outro Tutor", email="intruso@example.com")
        intruder.set_password("x")
        db.session.add(intruder)
        db.session.commit()
        _login(monkeypatch, intruder)

        # HTML: 403 direto; em JSON o app converte 403->404 por segurança.
        resp = client.post(
            f"/pedidos/{order.id}/confirmar-recebimento",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 403

        db.session.refresh(order)
        assert order.received_at is None
