import os

os.environ.setdefault("FISCAL_MASTER_KEY", "test-master-key")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

from extensions import db
from models import Clinica, Order, OrderItem, Product, StorePaymentAccount, User


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def test_clinic_owner_can_start_mercadopago_oauth(app, client, monkeypatch):
    app.config.update(MERCADOPAGO_CLIENT_ID="app-123", MERCADOPAGO_OAUTH_USE_PKCE=False)
    with app.app_context():
        owner = User(name="Clinica Owner", email="clinic-owner@example.com")
        owner.set_password("x")
        db.session.add(owner)
        db.session.flush()
        clinica = Clinica(nome="Clinica Modular", owner_id=owner.id)
        db.session.add(clinica)
        db.session.commit()
        _login(monkeypatch, owner)

        resp = client.post(f"/clinica/{clinica.id}/mercado-pago/conectar")

        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("https://auth.mercadopago.com.br/authorization?")
        account = StorePaymentAccount.query.filter_by(clinica_id=clinica.id).one()
        assert account.status == "pending"
        assert account.casa_de_racao_id is None


def test_shipping_helper_counts_clinic_and_feed_store_freight(app):
    from app import _order_vendor_shipping
    from models import CasaDeRacao

    with app.app_context():
        buyer = User(name="Comprador", email="buyer-establishment@example.com")
        buyer.set_password("x")
        clinic_owner = User(name="Clinic Owner", email="clinic-establishment@example.com")
        clinic_owner.set_password("x")
        feed_owner = User(name="Feed Owner", email="feed-establishment@example.com")
        feed_owner.set_password("x")
        db.session.add_all([buyer, clinic_owner, feed_owner])
        db.session.flush()

        clinica = Clinica(nome="Clinica Shop", owner_id=clinic_owner.id, valor_frete=7)
        casa = CasaDeRacao(nome="Racao Shop", owner_id=feed_owner.id, valor_frete=9)
        db.session.add_all([clinica, casa])
        db.session.flush()

        clinic_product = Product(name="Produto Clinica", price=30, stock=5, clinica_id=clinica.id)
        feed_product = Product(name="Produto Racao", price=40, stock=5, casa_de_racao_id=casa.id)
        db.session.add_all([clinic_product, feed_product])
        db.session.flush()

        order = Order(user_id=buyer.id)
        db.session.add(order)
        db.session.flush()
        db.session.add_all([
            OrderItem(order_id=order.id, product_id=clinic_product.id, item_name=clinic_product.name, quantity=1, unit_price=30),
            OrderItem(order_id=order.id, product_id=feed_product.id, item_name=feed_product.name, quantity=1, unit_price=40),
        ])
        db.session.commit()

        shipping = _order_vendor_shipping(order)

        assert shipping["products_total"] == 70
        assert shipping["shipping_total"] == 16
        assert shipping["grand_total"] == 86
        assert {store["kind"] for store in shipping["stores"]} == {"clinica", "casa_de_racao"}
