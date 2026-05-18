import os

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

import app as app_module
from extensions import db
from models import CasaDeRacao, Endereco, Order, OrderItem, Payment, Product, User


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def test_checkout_adds_one_shipping_item_per_feed_store(app, client, monkeypatch):
    captured = {}

    class FakePreference:
        def create(self, payload):
            captured["payload"] = payload
            return {"status": 201, "response": {"id": "pref-shipping", "init_point": "https://pay.test"}}

    class FakeSdk:
        def preference(self):
            return FakePreference()

    with app.app_context():
        address = Endereco(cep="11111-000", rua="Rua Frete", cidade="Cidade", estado="SP")
        buyer = User(name="Comprador", email="buyer-shipping@example.com")
        buyer.set_password("x")
        buyer.endereco = address
        owner_a = User(name="Loja A Owner", email="owner-a@example.com")
        owner_a.set_password("x")
        owner_b = User(name="Loja B Owner", email="owner-b@example.com")
        owner_b.set_password("x")
        db.session.add_all([address, buyer, owner_a, owner_b])
        db.session.flush()

        casa_a = CasaDeRacao(nome="Racoes A", owner_id=owner_a.id, status="ativa", valor_frete=8)
        casa_b = CasaDeRacao(nome="Racoes B", owner_id=owner_b.id, status="ativa", valor_frete=12)
        db.session.add_all([casa_a, casa_b])
        db.session.flush()

        product_a = Product(name="Racao A", price=100, stock=10, casa_de_racao_id=casa_a.id)
        product_b = Product(name="Racao B", price=50, stock=10, casa_de_racao_id=casa_b.id)
        db.session.add_all([product_a, product_b])
        db.session.flush()

        order = Order(user_id=buyer.id)
        db.session.add(order)
        db.session.flush()
        db.session.add_all([
            OrderItem(order_id=order.id, product_id=product_a.id, item_name=product_a.name, quantity=1, unit_price=100),
            OrderItem(order_id=order.id, product_id=product_b.id, item_name=product_b.name, quantity=2, unit_price=50),
        ])
        db.session.commit()

        with client.session_transaction() as sess:
            sess["current_order"] = order.id
            sess["_user_id"] = str(buyer.id)
            sess["_fresh"] = True
        _login(monkeypatch, buyer)
        runtime_app = __import__("sys").modules["petorlandia_app"]
        monkeypatch.setattr(runtime_app, "mp_sdk", lambda: FakeSdk())
        monkeypatch.setattr(runtime_app, "_mercadopago_notification_url", lambda: "https://example.test/notificacoes")

        class TestCheckoutForm(runtime_app.CheckoutForm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.address_id.choices = [(0, "addr")]

        monkeypatch.setattr(runtime_app, "CheckoutForm", TestCheckoutForm)

        resp = client.post("/checkout", data={"address_id": 0}, headers={"Accept": "text/html"})

        assert resp.status_code == 302
        payment = Payment.query.one()
        assert float(payment.amount) == 220.0
        titles = [item["title"] for item in captured["payload"]["items"]]
        assert "Frete - Racoes A" in titles
        assert "Frete - Racoes B" in titles
