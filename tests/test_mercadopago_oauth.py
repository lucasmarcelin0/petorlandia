import os
import sys
from datetime import timedelta
from types import SimpleNamespace

os.environ.setdefault("FISCAL_MASTER_KEY", "test-master-key")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")

import flask_login.utils as login_utils

import app as app_module
from extensions import db
from models import CasaDeRacao, Endereco, Order, OrderItem, Product, StorePaymentAccount, User
from security.crypto import clear_crypto_cache
from services.mercadopago_oauth import renew_due_store_accounts
from time_utils import utcnow


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _create_owner_and_store():
    owner = User(name="Lojista", email="lojista@example.com")
    owner.set_password("x")
    db.session.add(owner)
    db.session.flush()
    casa = CasaDeRacao(nome="Racoes Centro", owner_id=owner.id, status="ativa")
    db.session.add(casa)
    db.session.commit()
    return owner, casa


def test_mercadopago_connect_start_creates_pending_account(app, client, monkeypatch):
    app.config.update(
        MERCADOPAGO_CLIENT_ID="app-123",
        MERCADOPAGO_OAUTH_USE_PKCE=False,
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        owner, casa = _create_owner_and_store()
        _login(monkeypatch, owner)

        resp = client.post(f"/casa-de-racao/{casa.id}/mercado-pago/conectar")

        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("https://auth.mercadopago.com.br/authorization?")
        account = StorePaymentAccount.query.filter_by(casa_de_racao_id=casa.id).one()
        assert account.status == "pending"
        assert account.oauth_state


def test_mercadopago_callback_stores_encrypted_credentials(app, client, monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key")
    clear_crypto_cache()
    app.config.update(
        MERCADOPAGO_CLIENT_ID="app-123",
        MERCADOPAGO_CLIENT_SECRET="secret-123",
        MERCADOPAGO_OAUTH_REDIRECT_URI="https://example.test/casa-de-racao/mercado-pago/callback",
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        owner, casa = _create_owner_and_store()
        account = StorePaymentAccount(
            casa_de_racao_id=casa.id,
            provider="mercado_pago",
            oauth_state="state-123",
            status="pending",
        )
        account.code_verifier = "verifier"
        db.session.add(account)
        db.session.commit()
        _login(monkeypatch, owner)

        credentials = SimpleNamespace(
            access_token="seller-token",
            refresh_token="refresh-token",
            public_key="public-key",
            provider_user_id="987654",
            expires_at=None,
        )
        monkeypatch.setattr(
            sys.modules["petorlandia_app"],
            "exchange_code_for_credentials",
            lambda code, verifier: credentials,
        )

        resp = client.get("/casa-de-racao/mercado-pago/callback?code=code-123&state=state-123")

        assert resp.status_code == 302
        account = StorePaymentAccount.query.filter_by(casa_de_racao_id=casa.id).one()
        assert account.status == "connected", account.error_message
        assert account.provider_user_id == "987654"
        assert account.access_token_encrypted != "seller-token"
        assert account.access_token == "seller-token"
        assert account.oauth_state is None


def test_checkout_uses_connected_store_token_and_marketplace_fee(app, client, monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key")
    clear_crypto_cache()
    app.config.update(
        MERCADOPAGO_MARKETPLACE_FEE_PERCENT=10,
        MERCADOPAGO_ACCESS_TOKEN="platform-token",
        WTF_CSRF_ENABLED=False,
    )
    captured = {}

    class FakePreference:
        def create(self, payload):
            captured["payload"] = payload
            return {"status": 201, "response": {"id": "pref-1", "init_point": "https://pay.test"}}

    class FakeSdk:
        def __init__(self, token):
            captured["token"] = token

        def preference(self):
            return FakePreference()

    with app.app_context():
        addr = Endereco(cep="11111-000", rua="Rua Tutor", cidade="Cidade", estado="SP")
        buyer = User(name="Comprador Teste", email="comprador@example.com")
        buyer.set_password("x")
        buyer.endereco = addr
        owner, casa = _create_owner_and_store()
        product = Product(
            name="Racao Premium",
            price=100,
            stock=5,
            casa_de_racao_id=casa.id,
            status="active",
        )
        db.session.add_all([addr, buyer, product])
        db.session.flush()
        order = Order(user_id=buyer.id)
        db.session.add(order)
        db.session.flush()
        # unit_price = preço público (taxa embutida): 100 * 1.10 = 110 (múltiplo de 5)
        db.session.add(OrderItem(order_id=order.id, product_id=product.id, item_name=product.name, quantity=1, unit_price=product.preco_publico))
        account = StorePaymentAccount(casa_de_racao_id=casa.id, provider="mercado_pago", status="connected")
        account.access_token = "seller-token"
        db.session.add(account)
        db.session.commit()

        _login(monkeypatch, buyer)
        runtime_app = sys.modules["petorlandia_app"]
        monkeypatch.setattr(runtime_app, "_get_current_order", lambda: order)
        monkeypatch.setattr(runtime_app, "mp_sdk", lambda token=None: FakeSdk(token))
        monkeypatch.setattr(runtime_app, "_mercadopago_notification_url", lambda: "https://example.test/notificacoes")
        class TestCheckoutForm(runtime_app.CheckoutForm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.address_id.choices = [(0, "addr")]

        monkeypatch.setattr(runtime_app, "CheckoutForm", TestCheckoutForm)

        resp = client.post("/checkout", data={"address_id": 0}, headers={"Accept": "text/html"})

        assert resp.status_code == 302, resp.get_data(as_text=True)
        assert captured["token"] == "seller-token"
        # Comprador paga o preço público (110); lojista recebe 100; plataforma 10.
        product_item = next(i for i in captured["payload"]["items"] if i["id"] == str(product.id))
        assert product_item["unit_price"] == 110.0
        assert captured["payload"]["marketplace_fee"] == 10.0


def test_checkout_reprices_stale_cart_items(app, client, monkeypatch):
    """Carrinhos abertos antes de mudança de preço são reprecificados no checkout."""
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key")
    clear_crypto_cache()
    app.config.update(
        MERCADOPAGO_ACCESS_TOKEN="platform-token",
        WTF_CSRF_ENABLED=False,
    )
    captured = {}

    class FakePreference:
        def create(self, payload):
            captured["payload"] = payload
            return {"status": 201, "response": {"id": "pref-2", "init_point": "https://pay.test"}}

    class FakeSdk:
        def __init__(self, token):
            captured["token"] = token

        def preference(self):
            return FakePreference()

    with app.app_context():
        addr = Endereco(cep="11111-000", rua="Rua Tutor", cidade="Cidade", estado="SP")
        buyer = User(name="Comprador Antigo", email="antigo@example.com")
        buyer.set_password("x")
        buyer.endereco = addr
        owner, casa = _create_owner_and_store()
        product = Product(
            name="Racao Estoque",
            price=100,
            stock=5,
            casa_de_racao_id=casa.id,
            status="active",
        )
        db.session.add_all([addr, buyer, product])
        db.session.flush()
        order = Order(user_id=buyer.id)
        db.session.add(order)
        db.session.flush()
        # unit_price defasado (pré-taxa-embutida): deve virar 110 no checkout
        stale_item = OrderItem(order_id=order.id, product_id=product.id, item_name=product.name, quantity=1, unit_price=100)
        db.session.add(stale_item)
        account = StorePaymentAccount(casa_de_racao_id=casa.id, provider="mercado_pago", status="connected")
        account.access_token = "seller-token"
        db.session.add(account)
        db.session.commit()

        _login(monkeypatch, buyer)
        runtime_app = sys.modules["petorlandia_app"]
        monkeypatch.setattr(runtime_app, "_get_current_order", lambda: order)
        monkeypatch.setattr(runtime_app, "mp_sdk", lambda token=None: FakeSdk(token))
        monkeypatch.setattr(runtime_app, "_mercadopago_notification_url", lambda: "https://example.test/notificacoes")

        class TestCheckoutForm(runtime_app.CheckoutForm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.address_id.choices = [(0, "addr")]

        monkeypatch.setattr(runtime_app, "CheckoutForm", TestCheckoutForm)

        resp = client.post("/checkout", data={"address_id": 0}, headers={"Accept": "text/html"})

        assert resp.status_code == 302, resp.get_data(as_text=True)
        product_item = next(i for i in captured["payload"]["items"] if i["id"] == str(product.id))
        assert product_item["unit_price"] == 110.0
        assert captured["payload"]["marketplace_fee"] == 10.0
        assert float(stale_item.unit_price) == 110.0


def test_renew_due_store_accounts_refreshes_expiring_token(app, monkeypatch):
    monkeypatch.setenv("FISCAL_MASTER_KEY", "test-master-key")
    clear_crypto_cache()
    with app.app_context():
        owner, casa = _create_owner_and_store()
        account = StorePaymentAccount(
            casa_de_racao_id=casa.id,
            provider="mercado_pago",
            status="connected",
            token_expires_at=utcnow() + timedelta(days=5),
        )
        account.access_token = "old-token"
        account.refresh_token = "old-refresh"
        db.session.add(account)
        db.session.commit()

        refreshed = SimpleNamespace(
            access_token="new-token",
            refresh_token="new-refresh",
            public_key="new-public",
            provider_user_id="collector-1",
            expires_at=utcnow() + timedelta(days=180),
        )
        monkeypatch.setattr("services.mercadopago_oauth.refresh_credentials", lambda refresh: refreshed)

        result = renew_due_store_accounts(db, StorePaymentAccount)

        assert result.checked == 1
        assert result.renewed == 1
        account = StorePaymentAccount.query.get(account.id)
        assert account.access_token == "new-token"
        assert account.refresh_token == "new-refresh"
        assert account.public_key == "new-public"
