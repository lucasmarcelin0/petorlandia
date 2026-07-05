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
        # Itens reprecificados ao preço público (taxa embutida):
        # 100→110 e 2x 50→55 (=110), + fretes 8 e 12 → total 240.
        assert float(payment.amount) == 240.0
        titles = [item["title"] for item in captured["payload"]["items"]]
        assert "Frete - Racoes A" in titles
        assert "Frete - Racoes B" in titles


def test_loja_seller_badge_stays_inside_product_card(app, client, monkeypatch):
    with app.app_context():
        buyer = User(name="Comprador Loja", email="buyer-store-card@example.com")
        buyer.set_password("x")
        owner = User(name="Dono Loja", email="owner-store-card@example.com")
        owner.set_password("x")
        db.session.add_all([buyer, owner])
        db.session.flush()

        casa = CasaDeRacao(
            nome="Casa de Racao Teste PetOrlandia",
            owner_id=owner.id,
            status="ativa",
        )
        db.session.add(casa)
        db.session.flush()

        product = Product(
            name="Teste - Areia Higienica Granulada 4kg",
            description="Areia sanitaria para gatos com controle de odores.",
            price=29.9,
            stock=10,
            status="active",
            casa_de_racao_id=casa.id,
        )
        db.session.add(product)
        db.session.commit()
        buyer_id = buyer.id

        with client.session_transaction() as sess:
            sess["_user_id"] = str(buyer_id)
            sess["_fresh"] = True
        monkeypatch.setattr(login_utils, "_get_user", lambda: User.query.get(buyer_id))

    resp = client.get("/loja")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Casa de Racao Teste PetOrlandia" in html
    assert "product-seller-badge product-seller-badge--store" in html
    assert "product-seller-name" in html
    assert "text-overflow:ellipsis" in html
