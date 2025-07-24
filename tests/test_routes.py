import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, mp_sdk, db
from models import (
    User,
    Payment,
    PaymentStatus,
    DeliveryRequest,
    PaymentMethod,
    Order,
    Product,
    OrderItem,
)
from datetime import datetime

@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
    )
    yield flask_app

def test_login_page(app):
    client = app.test_client()
    response = client.get('/login')
    assert response.status_code == 200

def test_login_invalid_credentials(monkeypatch, app):
    client = app.test_client()

    class FakeQuery:
        def filter_by(self, **kw):
            return self
        def first(self):
            return None

    with app.app_context():
        monkeypatch.setattr(User, 'query', FakeQuery())

    response = client.post('/login', data={'email': 'foo@bar.com', 'password': 'x'}, follow_redirects=True)
    assert b'Email ou senha inv\xc3\xa1lidos' in response.data

def test_add_animal_requires_login(app):
    client = app.test_client()
    response = client.get('/add-animal')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']

def test_loja_requires_login(app):
    client = app.test_client()
    response = client.get('/loja')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_mp_token_in_config(app):
    assert 'MERCADOPAGO_ACCESS_TOKEN' in app.config


def test_mp_webhook_secret_in_config(app):
    assert 'MERCADOPAGO_WEBHOOK_SECRET' in app.config
from models import Animal


def test_index_page(app):
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200


def test_register_page(app):
    client = app.test_client()
    response = client.get('/register')
    assert response.status_code == 200


def test_reset_password_request_page(app):
    client = app.test_client()
    response = client.get('/reset_password_request')
    assert response.status_code == 200


def test_logout_requires_login(app):
    client = app.test_client()
    response = client.get('/logout')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_profile_requires_login(app):
    client = app.test_client()
    response = client.get('/profile')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_animals_page(monkeypatch, app):
    client = app.test_client()

    class FakePagination:
        def __init__(self):
            self.items = []
            self.pages = 0

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self
        def filter_by(self, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def paginate(self, page=None, per_page=None, error_out=True):
            return FakePagination()

    with app.app_context():
        monkeypatch.setattr(Animal, 'query', FakeQuery())

    response = client.get('/animals')
    assert response.status_code == 200


def test_payment_status_updates_from_api(monkeypatch, app):
    client = app.test_client()

    class FakePayment:
        id = 1
        status = PaymentStatus.PENDING
        transaction_id = "abc123"
        order_id = 99
        user_id = 1
        method = PaymentMethod.PIX
        order = type('O', (), {'items': [], 'total_value': lambda self: 0})()

    class FakePaymentQuery:
        def get_or_404(self, _):
            return FakePayment()

    class FakeDRQuery:
        def filter_by(self, **kw):
            class R:
                def first(self_inner):
                    return None
            return R()

    with app.app_context():
        monkeypatch.setattr(Payment, 'query', FakePaymentQuery())
        monkeypatch.setattr(DeliveryRequest, 'query', FakeDRQuery())
        monkeypatch.setattr(db.session, 'add', lambda *a, **k: None)
        monkeypatch.setattr(db.session, 'commit', lambda *a, **k: None)
        # Substitui o context processor que consulta o banco
        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        # Finge que o usuário está logado
        import flask_login.utils as login_utils
        class FakeUser:
            is_authenticated = True
            id = 1
            name = "Tester"
            email = "u@x.com"
        monkeypatch.setattr(login_utils, '_get_user', lambda: FakeUser())
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        class FakePaymentAPI:
            def get(self, _):
                return {"status": 200, "response": {"status": "approved"}}

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: type('O', (), {'payment': lambda: FakePaymentAPI()})())

        response = client.get('/payment_status/1?status=success')
        assert response.status_code == 200


def test_api_minhas_compras_filters_by_user(monkeypatch, app):
    client = app.test_client()

    class FakeOrder:
        id = 1
        created_at = datetime.utcnow()
        user_id = 1
        payment = type('P', (), {'status': PaymentStatus.COMPLETED})
        items = []
        def total_value(self):
            return 10.0

    class FakeQuery:
        def options(self, *a, **k):
            return self
        def filter_by(self, **kw):
            assert kw.get('user_id') == 1
            return self
        def order_by(self, *a, **k):
            return self
        def all(self):
            return [FakeOrder()]

    with app.app_context():
        monkeypatch.setattr(Order, 'query', FakeQuery())
        import flask_login.utils as login_utils
        class FakeUser:
            is_authenticated = True
            id = 1
            email = 'x'
        monkeypatch.setattr(login_utils, '_get_user', lambda: FakeUser())
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        response = client.get('/api/minhas-compras')
        assert response.status_code == 200
        data = response.get_json()
        assert data[0]['id'] == 1


def test_pedido_detail_forbidden(monkeypatch, app):
    client = app.test_client()

    class FakeOrderObj:
        id = 2
        user_id = 2
        created_at = datetime.utcnow()
        items = []
        payment = None
        delivery_requests = []
        def total_value(self):
            return 0

    class FakeQuery:
        def options(self, *a, **k):
            return self
        def get_or_404(self, _):
            return FakeOrderObj()

    with app.app_context():
        monkeypatch.setattr(Order, 'query', FakeQuery())
        import flask_login.utils as login_utils
        class FakeUser:
            is_authenticated = True
            id = 1
            email = 'x'
        monkeypatch.setattr(login_utils, '_get_user', lambda: FakeUser())
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        response = client.get('/pedido/2')
        assert response.status_code == 403


def test_cart_quantity_updates(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        product = Product(id=1, name='Prod', price=10.0)
        db.session.add_all([user, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        client.post('/carrinho/adicionar/1', data={'quantity': 1})
        item = OrderItem.query.first()
        assert item.quantity == 1

        client.post(f'/carrinho/increase/{item.id}')
        assert OrderItem.query.get(item.id).quantity == 2

        client.post(f'/carrinho/decrease/{item.id}')
        assert OrderItem.query.get(item.id).quantity == 1

        client.post(f'/carrinho/decrease/{item.id}')
        assert OrderItem.query.get(item.id) is None


def test_product_detail_requires_login(app):
    client = app.test_client()
    response = client.get('/produto/1')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_product_detail_page(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        product = Product(id=1, name='Prod', price=10.0)
        db.session.add_all([user, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.get('/produto/1')
        assert response.status_code == 200
