import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import app as app_module
from app import app as flask_app, mp_sdk, db
from io import BytesIO
from models import (
    User,
    Payment,
    PaymentStatus,
    DeliveryRequest,
    PaymentMethod,
    Order,
    Product,
    OrderItem,
    Animal,
    Message,
    Endereco,
    SavedAddress,
    AnimalDocumento,
    Veterinario,
    VeterinarianMembership,
    Clinica,
    Orcamento,
)
from flask import url_for
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import quote

@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
    )
    with flask_app.app_context():
        db.create_all()
    yield flask_app


def login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

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


def test_mp_statement_descriptor_in_config(app):
    assert 'MERCADOPAGO_STATEMENT_DESCRIPTOR' in app.config


def test_mp_binary_mode_in_config(app):
    assert 'MERCADOPAGO_BINARY_MODE' in app.config
from models import Animal


def test_index_page(app):
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200


def test_index_hides_professional_area_when_membership_inactive(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='Vet', email='vet@test', worker='veterinario')
        user.set_password('test')
        vet_profile = Veterinario(id=1, user=user, crmv='CRMV123')
        membership = VeterinarianMembership(
            veterinario=vet_profile,
            started_at=datetime.utcnow() - timedelta(days=60),
            trial_ends_at=datetime.utcnow() - timedelta(days=30),
            paid_until=None,
        )

        db.session.add_all([user, vet_profile, membership])
        db.session.commit()

        import flask_login.utils as login_utils

        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = (
                    lambda: {'unread_messages': 0}
                )

        response = client.get('/')
        html = response.get_data(as_text=True)

        assert 'Área profissional' not in html


def test_index_shows_professional_area_for_active_vet_without_worker_flag(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='Vet', email='vet@test', worker=None)
        user.set_password('test')
        vet_profile = Veterinario(id=1, user=user, crmv='CRMV123')
        membership = VeterinarianMembership(
            veterinario=vet_profile,
            started_at=datetime.utcnow() - timedelta(days=5),
            trial_ends_at=datetime.utcnow() + timedelta(days=25),
            paid_until=None,
        )

        db.session.add_all([user, vet_profile, membership])
        db.session.commit()

        import flask_login.utils as login_utils

        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = (
                    lambda: {'unread_messages': 0}
                )

        response = client.get('/')
        html = response.get_data(as_text=True)

        assert 'Área profissional' in html


def test_veterinarian_request_new_trial_requires_admin_for_activation(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(id=1, name='Admin', email='admin@test', role='admin')
        admin.set_password('secret')
        vet_user = User(
            id=2,
            name='Vet',
            email='vet@test',
            role='veterinario',
            worker='veterinario',
        )
        vet_user.set_password('test')
        vet_profile = Veterinario(id=1, user=vet_user, crmv='CRMV123')
        expired_started_at = datetime(2024, 1, 1, 12, 0, 0)
        expired_trial_ends = datetime(2024, 1, 15, 12, 0, 0)
        membership = VeterinarianMembership(
            veterinario=vet_profile,
            started_at=expired_started_at,
            trial_ends_at=expired_trial_ends,
            paid_until=None,
        )

        db.session.add_all([admin, vet_user, vet_profile, membership])
        db.session.commit()
        membership_id = membership.id
        admin_id = admin.id
        vet_user_id = vet_user.id

        import flask_login.utils as login_utils

        monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet_user_id))

    response = client.post(
        f'/veterinario/assinatura/{membership_id}/nova_avaliacao',
        data={'submit': '1'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/conversa_admin')

    with app.app_context():
        unchanged_membership = VeterinarianMembership.query.get(membership_id)
        assert unchanged_membership.started_at == expired_started_at
        assert unchanged_membership.trial_ends_at == expired_trial_ends

        admin = User.query.get(admin_id)
        messages = Message.query.filter_by(
            sender_id=vet_user_id,
            receiver_id=admin_id,
        ).all()
        assert messages
        assert any('reativa' in msg.content for msg in messages)

        import flask_login.utils as login_utils

        monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(admin_id))

    response = client.post(
        f'/veterinario/assinatura/{membership_id}/nova_avaliacao',
        data={'submit': '1'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith(f'/conversa_admin/{vet_user_id}')

    with app.app_context():
        refreshed_membership = VeterinarianMembership.query.get(membership_id)
        assert refreshed_membership.started_at > expired_started_at
        assert refreshed_membership.trial_ends_at > expired_trial_ends


def test_veterinarian_membership_route_allows_admin(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(id=1, name='Admin', email='admin@test', role='admin')
        admin.set_password('secret')

        db.session.add(admin)
        db.session.commit()

        import flask_login.utils as login_utils

        admin_id = admin.id

        monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(admin_id))

    response = client.get('/veterinario/assinatura')

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


def test_painel_requires_admin_role(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='User', email='user@test')
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils

        monkeypatch.setattr(login_utils, '_get_user', lambda: user)

        response = client.get('/painel')
        assert response.status_code == 403


def test_painel_allows_admin(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(id=1, name='Admin', email='admin@test', role='admin')
        admin.set_password('secret')
        db.session.add(admin)
        db.session.commit()

        import flask_login.utils as login_utils

        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)

        response = client.get('/painel')
        assert response.status_code == 200


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
        def options(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def paginate(self, page=None, per_page=None, error_out=True):
            return FakePagination()

    with app.app_context():
        monkeypatch.setattr(Animal, 'query', FakeQuery())

    response = client.get('/animals')
    assert response.status_code == 200


def test_admin_toggle_all_animals(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(id=1, name='Admin', email='admin@test', role='admin')
        admin.set_password('x')
        tutor = User(id=2, name='Tutor', email='tutor@test')
        tutor.set_password('x')
        adopted = Animal(id=1, name='Adopted', modo='adotado', user_id=tutor.id)
        available = Animal(id=2, name='Available', modo='doação', user_id=tutor.id)
        db.session.add_all([admin, tutor, adopted, available])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)
        monkeypatch.setattr(app_module, '_is_admin', lambda: True)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp1 = client.get('/animals')
        assert resp1.status_code == 200
        assert b'Adopted' not in resp1.data

        resp2 = client.get('/animals?show_all=1')
        assert resp2.status_code == 200
        assert b'Adopted' in resp2.data


def test_payment_status_updates_from_api(monkeypatch, app):
    client = app.test_client()

    class FakePayment:
        id = 1
        status = PaymentStatus.PENDING
        transaction_id = "abc123"
        order_id = 1
        user_id = 1
        method = PaymentMethod.PIX
        order = type('O', (), {
            'items': [],
            'total_value': lambda self: 0,
            'created_at': datetime.utcnow()
        })()

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

        class FakeOrder:
            id = 1
            created_at = datetime.utcnow()
            user_id = 1
            payment = type('P', (), {'status': PaymentStatus.COMPLETED})()
            items = []
            def total_value(self):
                return 10.0

        class FakeOrderPagination:
            items = [FakeOrder()]
            pages = 1
            page = 1

        class FakeOrderQuery:
            def join(self, *a, **k):
                return self
            def options(self, *a, **k):
                return self
            def filter(self, *a, **k):
                return self
            def order_by(self, *a, **k):
                return self
            def paginate(self, page=1, per_page=20, error_out=False):
                return FakeOrderPagination()
            def get_or_404(self, _):
                return FakeOrder()

        monkeypatch.setattr(Order, 'query', FakeOrderQuery())

        class FakePaymentAPI:
            def get(self, _):
                return {"status": 200, "response": {"status": "approved"}}

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: type('O', (), {'payment': lambda: FakePaymentAPI()})())

        response = client.get('/payment_status/1?status=success', follow_redirects=False)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Resumo do Pedido' in html
        assert 'Previsão de entrega' in html


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


def test_pedido_detail_buttons_for_buyer(monkeypatch, app):
    client = app.test_client()

    class FakeProduct:
        price = 10.0
        name = 'P'
        image_url = None

    class FakeItem:
        product = FakeProduct()
        quantity = 1

    class FakeReq:
        id = 5
        status = 'pendente'
        requested_at = datetime.utcnow()
        accepted_at = None
        completed_at = None
        canceled_at = None
        worker = None

    class FakeBuyer:
        id = 1
        name = 'Buyer'
        email = 'b@example.com'

    class FakeOrderObj:
        id = 1
        user_id = 1
        created_at = datetime.utcnow()
        items = [FakeItem()]
        payment = None
        delivery_requests = [FakeReq()]
        user = FakeBuyer()
        shipping_address = 'Rua'
        def total_value(self):
            return 10.0

    class FakeQuery:
        def options(self, *a, **k):
            return self
        def get_or_404(self, _):
            return FakeOrderObj()

    with app.app_context():
        monkeypatch.setattr(Order, 'query', FakeQuery())
        class FakeMsgQuery:
            def filter_by(self, **kwargs):
                return self
            def count(self):
                return 0
        monkeypatch.setattr(Message, 'query', FakeMsgQuery())
        import flask_login.utils as login_utils
        class FakeUser:
            is_authenticated = True
            id = 1
            worker = None
            name = 'Buyer'
            role = 'buyer'
        monkeypatch.setattr(login_utils, '_get_user', lambda: FakeUser())
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        response = client.get('/pedido/1')
        html = response.get_data(as_text=True)
        assert 'Cancelar pedido' in html


def test_pedido_detail_hides_cancel_button_when_canceled(monkeypatch, app):
    client = app.test_client()

    class FakeReq:
        id = 5
        status = 'cancelada'
        requested_at = datetime.utcnow()
        accepted_at = None
        completed_at = None
        canceled_at = datetime.utcnow()
        worker = None

    class FakeOrderObj:
        id = 1
        user_id = 1
        created_at = datetime.utcnow()
        items = []
        payment = None
        delivery_requests = [FakeReq()]
        user = type('FakeBuyer', (), {'id': 1, 'name': 'Buyer', 'email': 'b@example.com'})()
        shipping_address = 'Rua'
        def total_value(self):
            return 10.0

    class FakeQuery:
        def options(self, *a, **k):
            return self
        def get_or_404(self, _):
            return FakeOrderObj()

    with app.app_context():
        monkeypatch.setattr(Order, 'query', FakeQuery())
        class FakeMsgQuery:
            def filter_by(self, **kwargs):
                return self
            def count(self):
                return 0
        monkeypatch.setattr(Message, 'query', FakeMsgQuery())
        import flask_login.utils as login_utils
        class FakeUser:
            is_authenticated = True
            id = 1
            worker = None
            name = 'Buyer'
            role = 'buyer'
        monkeypatch.setattr(login_utils, '_get_user', lambda: FakeUser())
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        response = client.get('/pedido/1')
        html = response.get_data(as_text=True)
        assert 'Cancelar pedido' not in html


def test_delivery_requests_show_canceled_status(monkeypatch, app):
    client = app.test_client()

    class FakeReq:
        id = 1
        status = 'cancelada'
        order_id = 1
        order = type('Order', (), {'user': type('U', (), {'name': 'Buyer'})(), 'payment': None, 'total_value': lambda self: 10.0})()
        canceled_at = datetime.utcnow()
        requested_at = datetime.utcnow()
        accepted_at = None
        completed_at = None

    fake_req = FakeReq()

    class FakeQuery:
        def order_by(self, *a, **k):
            return self
        def options(self, *a, **k):
            return self
        def filter_by(self, **kwargs):
            self._status = kwargs.get('status')
            return self
        def all(self):
            if getattr(self, '_status', None) == 'cancelada':
                return [fake_req]
            return []

    with app.app_context():
        monkeypatch.setattr(DeliveryRequest, 'query', FakeQuery())
        import flask_login.utils as login_utils
        class FakeUser:
            is_authenticated = True
            id = 1
            worker = None
            name = 'Buyer'
            role = 'buyer'
        monkeypatch.setattr(login_utils, '_get_user', lambda: FakeUser())
        class FakeMsgQuery:
            def filter_by(self, **kwargs):
                return self
            def count(self):
                return 0
        monkeypatch.setattr(Message, 'query', FakeMsgQuery())

        response = client.get('/delivery_requests')
        html = response.get_data(as_text=True)
        assert 'Cancelado' in html


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


def test_cart_decrease_last_item_redirects(monkeypatch, app):
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

        resp = client.post(
            f'/carrinho/decrease/{item.id}',
            headers={'Accept': 'application/json'}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        with flask_app.test_request_context():
            expected_url = url_for('ver_carrinho')
        assert data['redirect'] == expected_url
        assert OrderItem.query.get(item.id) is None


def test_cart_merges_duplicates(monkeypatch, app):
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
        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        assert OrderItem.query.count() == 1
        item = OrderItem.query.first()
        assert item.quantity == 2


def test_cart_add_missing_product_redirects(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp = client.post('/carrinho/adicionar/999', data={'quantity': 1})

        with flask_app.test_request_context():
            expected_url = url_for('loja')

        assert resp.status_code == 302
        assert resp.headers['Location'].endswith(expected_url)


def test_cart_add_missing_product_json(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp = client.post(
            '/carrinho/adicionar/999',
            data={'quantity': 1},
            headers={'Accept': 'application/json'}
        )

        assert resp.status_code == 404
        assert resp.get_json() == {'success': False, 'error': 'product not found'}


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


def test_admin_messages_requires_login(app):
    client = app.test_client()
    response = client.get('/mensagens_admin')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_admin_messages_display(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(id=1, name='Admin', email='admin@test', role='admin')
        admin.set_password('x')
        user = User(id=2, name='Tester', email='user@test')
        user.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=user.id)
        db.session.add_all([admin, user, animal])
        db.session.commit()

        msg1 = Message(sender_id=user.id, receiver_id=admin.id, animal_id=animal.id, content='Hi')
        msg2 = Message(sender_id=admin.id, receiver_id=user.id, content='Update')
        db.session.add_all([msg1, msg2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)
        monkeypatch.setattr(app_module, '_is_admin', lambda: True)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.get('/mensagens_admin')
        assert response.status_code == 200
        assert b'Tester' in response.data


def test_admin_messages_show_only_user_initiated_conversations(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(id=1, name='Admin', email='admin@test', role='admin')
        admin.set_password('x')
        user1 = User(id=2, name='User1', email='u1@test')
        user1.set_password('x')
        user2 = User(id=3, name='User2', email='u2@test')
        user2.set_password('x')
        db.session.add_all([admin, user1, user2])
        db.session.commit()

        # user1 enviou mensagem ao admin
        m1 = Message(sender_id=user1.id, receiver_id=admin.id, content='oi')
        # admin enviou mensagem para user2 sem resposta
        m2 = Message(sender_id=admin.id, receiver_id=user2.id, content='hello')
        db.session.add_all([m1, m2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)
        monkeypatch.setattr(app_module, '_is_admin', lambda: True)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.get('/mensagens_admin')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'User1' in data
        assert 'User2' not in data


def test_admin_messages_include_messages_to_any_admin(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin1 = User(id=1, name='Admin1', email='a1@test', role='admin')
        admin1.set_password('x')
        admin2 = User(id=2, name='Admin2', email='a2@test', role='admin')
        admin2.set_password('x')
        user = User(id=3, name='User', email='u@test')
        user.set_password('x')
        db.session.add_all([admin1, admin2, user])
        db.session.commit()

        msg = Message(sender_id=user.id, receiver_id=admin1.id, content='hello')
        db.session.add(msg)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin2)
        monkeypatch.setattr(app_module, '_is_admin', lambda: True)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.get('/mensagens_admin')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'User' in data


def test_conversa_admin_shows_message_for_any_admin(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        admin1 = User(id=1, name='Admin1', email='a1@test', role='admin')
        admin1.set_password('x')
        admin2 = User(id=2, name='Admin2', email='a2@test', role='admin')
        admin2.set_password('x')
        user = User(id=3, name='User', email='u@test')
        user.set_password('x')
        db.session.add_all([admin1, admin2, user])
        db.session.commit()

        msg = Message(sender_id=user.id, receiver_id=admin1.id, content='hello')
        db.session.add(msg)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin2)
        monkeypatch.setattr(app_module, '_is_admin', lambda: True)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.get('/conversa_admin/3')
        assert response.status_code == 200
        assert b'hello' in response.data


def test_conversa_allows_current_user_as_url_participant(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        owner = User(id=1, name='Owner', email='owner@test')
        owner.set_password('x')
        interested = User(id=2, name='Interested', email='user@test')
        interested.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=owner.id)

        db.session.add_all([owner, interested, animal])
        db.session.commit()

        message = Message(
            sender_id=owner.id,
            receiver_id=interested.id,
            animal_id=animal.id,
            content='Hello!',
        )
        db.session.add(message)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: interested)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.get('/conversa/1/2')
        assert response.status_code == 200
        data = response.get_data(as_text=True)
        assert 'Hello!' in data


def test_chat_api_get_post(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user1 = User(id=1, name='User1', email='u1@test')
        user1.set_password('x')
        user2 = User(id=2, name='User2', email='u2@test')
        user2.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=user2.id)
        db.session.add_all([user1, user2, animal])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user1)

        resp = client.get('/chat/1')
        assert resp.status_code == 200
        assert resp.get_json() == []

        resp = client.post('/chat/1', json={
            'sender_id': 1,
            'receiver_id': 2,
            'content': 'hello'
        })
        assert resp.status_code == 201

        resp = client.get('/chat/1')
        assert len(resp.get_json()) == 1


def test_change_password_requires_login(app):
    client = app.test_client()
    response = client.get('/change_password')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_delete_account_requires_login(app):
    client = app.test_client()
    response = client.post('/delete_account')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_change_password_updates_user(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x@test')
        user.set_password('old')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.post('/change_password', data={
            'current_password': 'old',
            'new_password': 'newpass',
            'confirm_password': 'newpass'
        }, follow_redirects=True)
        assert b'Senha atualizada com sucesso' in response.data
        assert user.check_password('newpass')


def test_delete_account_removes_user(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x@test')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.post('/delete_account', data={'submit': True}, follow_redirects=True)
        assert 'Sua conta foi excluída'.encode() in response.data
        assert User.query.get(user.id) is None


def test_delete_account_removes_payments(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='Tester', email='x@test')
        user.set_password('x')
        product = Product(id=1, name='Prod', price=10.0)
        order = Order(id=1, user=user)
        payment = Payment(id=1, order=order, method=PaymentMethod.PIX, user=user)
        db.session.add_all([user, product, order, payment])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.post('/delete_account', data={'submit': True}, follow_redirects=True)
        assert 'Sua conta foi excluída'.encode() in response.data
        assert User.query.get(user.id) is None
        assert Payment.query.first() is None


def test_delete_account_removes_saved_addresses(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='Tester', email='x@test')
        user.set_password('x')
        addr1 = SavedAddress(user_id=1, address='Rua 1 – Cidade/SP – CEP 00000-000')
        addr2 = SavedAddress(user_id=1, address='Rua 2 – Cidade/SP – CEP 11111-111')
        db.session.add_all([user, addr1, addr2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.post('/delete_account', data={'submit': True}, follow_redirects=True)
        assert 'Sua conta foi excluída'.encode() in response.data
        assert User.query.get(user.id) is None
        assert SavedAddress.query.count() == 0


def test_delete_account_removes_messages(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='Tester', email='x@test')
        user.set_password('x')
        other = User(id=2, name='Other', email='o@test')
        other.set_password('x')
        msg1 = Message(sender=user, receiver=other, content='hi')
        msg2 = Message(sender=other, receiver=user, content='hi2')
        db.session.add_all([user, other, msg1, msg2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        response = client.post('/delete_account', data={'submit': True}, follow_redirects=True)
        assert 'Sua conta foi excluída'.encode() in response.data
        assert User.query.get(user.id) is None
        assert Message.query.count() == 0


def test_salvar_endereco(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x@test')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp = client.post('/carrinho/salvar_endereco', data={
            'cep': '12345-678',
            'rua': 'Rua Teste',
            'numero': '10',
            'bairro': 'Centro',
            'cidade': 'Cidade',
            'estado': 'SP'
        })
        assert resp.status_code == 302
        assert SavedAddress.query.count() == 1


def test_salvar_endereco_invalid(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Tester', email='x@test')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp = client.post('/carrinho/salvar_endereco', data={
            'cep': '',
            'rua': 'Rua Teste',
            'cidade': 'Cidade',
            'estado': 'SP'
        })
        assert resp.status_code == 302
        assert SavedAddress.query.count() == 0


def test_cart_shows_saved_address_below_default(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr = Endereco(cep='11111-000', rua='Rua Tutor', cidade='Cidade', estado='SP')
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        user.endereco = addr
        product = Product(id=1, name='Prod', price=10.0)
        saved = SavedAddress(user_id=1, address='Rua Salva – Cidade/SP – CEP 22222-222')
        db.session.add_all([addr, user, product, saved])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        resp = client.get('/carrinho')
        html = resp.get_data(as_text=True)
        assert 'Rua Tutor' in html
        assert 'Rua Salva' in html
        assert html.index('Rua Salva') > html.index('Rua Tutor')


def test_checkout_uses_selected_address(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr = Endereco(cep='11111-000', rua='Rua Tutor', cidade='Cidade', estado='SP')
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        user.endereco = addr
        product = Product(id=1, name='Prod', price=10.0)
        db.session.add_all([addr, user, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        class FakePrefService:
            def create(self, data):
                return {'status': 201, 'response': {'id': '123', 'init_point': 'http://mp'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        class TestCheckoutForm(app_module.CheckoutForm):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.address_id.choices = [(0, 'addr')]

        monkeypatch.setattr(app_module, 'CheckoutForm', TestCheckoutForm)

        resp = client.post('/checkout', data={'address_id': 0})

        order = Order.query.first()
        assert order.shipping_address == user.endereco.full
        payment = Payment.query.first()
        assert payment is not None
        assert resp.status_code == 302
        assert resp.headers['Location'] == 'http://mp'


def test_checkout_sends_external_reference(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr = Endereco(cep='11111-000', rua='Rua Tutor', cidade='Cidade', estado='SP')
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        user.endereco = addr
        product = Product(id=1, name='Prod', price=10.0, description='Prod desc')
        db.session.add_all([addr, user, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        captured = {}
        class FakePrefService:
            def create(self, data):
                captured['payload'] = data
                return {'status': 201, 'response': {'id': '123', 'init_point': 'http://mp'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        class TestCheckoutForm(app_module.CheckoutForm):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.address_id.choices = [(0, 'addr')]

        monkeypatch.setattr(app_module, 'CheckoutForm', TestCheckoutForm)

        resp = client.post('/checkout', data={'address_id': 0})
        payment = Payment.query.first()
        payload = captured['payload']
        assert payload['external_reference'] == str(payment.id)
        assert payload['payer']['first_name'] == 'Tester'

        assert payload['payer']['last_name'] == 'Tester'

        assert payload['payer']['address']['street_name'] == user.endereco.full
        assert payload['items'][0]['id'] == '1'
        assert payload['items'][0]['description'] == 'Prod desc'
        assert payload['items'][0]['category_id'] == 'others'


def test_checkout_falls_back_to_email_when_name_missing(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr = Endereco(cep='11111-000', rua='Rua Tutor', cidade='Cidade', estado='SP')
        user = User(id=1, name='', email='buyer@example.com')
        user.set_password('x')
        user.endereco = addr
        product = Product(id=1, name='Prod', price=10.0)
        db.session.add_all([addr, user, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        captured = {}
        class FakePrefService:
            def create(self, data):
                captured['payload'] = data
                return {'status': 201, 'response': {'id': '123', 'init_point': 'http://mp'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        class TestCheckoutForm(app_module.CheckoutForm):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.address_id.choices = [(0, 'addr')]

        monkeypatch.setattr(app_module, 'CheckoutForm', TestCheckoutForm)

        client.post('/checkout', data={'address_id': 0})
        payload = captured['payload']
        assert payload['payer']['first_name'] == 'buyer'
        assert payload['payer']['last_name'] == 'buyer'


def test_checkout_uses_full_last_name(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr = Endereco(cep='11111-000', rua='Rua Tutor', cidade='Cidade', estado='SP')
        user = User(id=1, name='Maria da Silva Souza', email='x')
        user.set_password('x')
        user.endereco = addr
        product = Product(id=1, name='Prod', price=10.0, description='Prod desc')
        db.session.add_all([addr, user, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        captured = {}
        class FakePrefService:
            def create(self, data):
                captured['payload'] = data
                return {'status': 201, 'response': {'id': '123', 'init_point': 'http://mp'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        class TestCheckoutForm(app_module.CheckoutForm):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.address_id.choices = [(0, 'addr')]

        monkeypatch.setattr(app_module, 'CheckoutForm', TestCheckoutForm)

        client.post('/checkout', data={'address_id': 0})
        payload = captured['payload']
        assert payload['payer']['first_name'] == 'Maria'
        assert payload['payer']['last_name'] == 'da Silva Souza'


def test_checkout_includes_phone_and_cpf(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr = Endereco(cep='11111-000', rua='Rua Tutor', cidade='Cidade', estado='SP')
        user = User(
            id=1,
            name='Tester',
            email='u@test',
            phone='11 91234-5678',
            cpf='123.456.789-09',
        )
        user.set_password('x')
        user.endereco = addr
        product = Product(id=1, name='Prod', price=10.0)
        db.session.add_all([addr, user, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        captured = {}
        class FakePrefService:
            def create(self, data):
                captured['payload'] = data
                return {'status': 201, 'response': {'id': '123', 'init_point': 'http://mp'}}

        class FakeSDK:
            def preference(self):
                return FakePrefService()

        monkeypatch.setattr(app_module, 'mp_sdk', lambda: FakeSDK())
        class TestCheckoutForm(app_module.CheckoutForm):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.address_id.choices = [(0, 'addr')]

        monkeypatch.setattr(app_module, 'CheckoutForm', TestCheckoutForm)

        client.post('/checkout', data={'address_id': 0})
        payload = captured['payload']
        assert payload['payer']['phone']['area_code'] == '11'
        assert payload['payer']['phone']['number'] == '912345678'
        assert payload['payer']['identification']['number'] == '12345678909'

def test_checkout_confirm_renders(monkeypatch, app):
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

        class TestCheckoutForm(app_module.CheckoutForm):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.address_id.choices = [(0, 'addr')]

        monkeypatch.setattr(app_module, 'CheckoutForm', TestCheckoutForm)

        resp = client.post('/checkout/confirm', data={'address_id': 0})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Confirmar Compra' in html
        assert 'Prod' in html
        assert 'addr' in html
    assert 'name="address_id"' in html


def test_checkout_confirm_uses_posted_address(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr1 = Endereco(cep='11111-000', rua='Rua1', cidade='Cidade', estado='SP')
        addr2 = Endereco(cep='22222-000', rua='Rua2', cidade='Cidade', estado='SP')
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        user.endereco = addr1
        saved = SavedAddress(id=42, user_id=1, address=addr2.full)
        product = Product(id=1, name='Prod', price=10.0)
        db.session.add_all([addr1, addr2, user, saved, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        with client.session_transaction() as sess:
            sess['last_address_id'] = str(saved.id)

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        class TestCheckoutForm(app_module.CheckoutForm):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.address_id.choices = [(0, addr1.full), (saved.id, saved.address)]

        monkeypatch.setattr(app_module, 'CheckoutForm', TestCheckoutForm)

        resp = client.post('/checkout/confirm', data={'address_id': 0})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert addr1.full in html
        assert 'name="address_id" value="0"' in html


def test_cart_uses_session_string_address_id(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()
        addr = Endereco(cep='11111-000', rua='Rua Tutor', cidade='Cidade', estado='SP')
        user = User(id=1, name='Tester', email='x')
        user.set_password('x')
        user.endereco = addr
        saved = SavedAddress(id=42, user_id=1, address='Rua Salva – Cidade/SP – CEP 22222-222')
        product = Product(id=1, name='Prod', price=10.0)
        db.session.add_all([addr, user, saved, product])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        with client.session_transaction() as sess:
            sess['last_address_id'] = str(saved.id)

        client.post('/carrinho/adicionar/1', data={'quantity': 1})

        resp = client.get('/carrinho')
        html = resp.get_data(as_text=True)
        assert f'value="{saved.id}" selected' in html
        assert 'value="0" selected' not in html


def test_accept_delivery_redirects(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        worker = User(id=1, name='Worker', email='w@x.com', worker='delivery')
        worker.set_password('x')
        buyer = User(id=2, name='Buyer', email='b@x.com')
        buyer.set_password('x')
        order = Order(id=1, user_id=2)
        req = DeliveryRequest(id=1, order_id=1, requested_by_id=2)
        db.session.add_all([worker, buyer, order, req])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: worker)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        resp = client.post(
            f'/delivery_requests/{req.id}/accept',
            headers={'Accept': 'application/json'}
        )
        assert resp.status_code == 200
        db_req = DeliveryRequest.query.get(req.id)
        assert db_req.worker_id == worker.id


def test_accept_delivery_without_location(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        worker = User(id=1, name='Worker', email='w@x.com', worker='delivery')
        worker.set_password('x')
        buyer = User(id=2, name='Buyer', email='b@x.com')
        buyer.set_password('x')
        order = Order(id=1, user_id=2)
        req = DeliveryRequest(id=1, order_id=1, requested_by_id=2)
        db.session.add_all([worker, buyer, order, req])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: worker)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        resp = client.post(
            f'/delivery_requests/{req.id}/accept',
            headers={'Accept': 'application/json'}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['category'] == 'success'


def test_accept_delivery_json_payload(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        worker = User(id=1, name='Worker', email='w@x.com', worker='delivery')
        worker.set_password('x')
        buyer = User(id=2, name='Buyer', email='b@x.com')
        buyer.set_password('x')
        order = Order(id=1, user_id=2)
        req = DeliveryRequest(id=1, order_id=1, requested_by_id=2)
        db.session.add_all([worker, buyer, order, req])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: worker)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        resp = client.post(
            f'/delivery_requests/{req.id}/accept',
            headers={'Accept': 'application/json'}
        )

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['message'] == 'Entrega aceita.'
        assert payload['category'] == 'success'
        with flask_app.test_request_context():
            assert payload['redirect'] == url_for('worker_delivery_detail', req_id=req.id)


def test_accept_delivery_denied_json(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='Tutor', email='t@x.com')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        resp = client.post(
            '/delivery_requests/99/accept',
            headers={'Accept': 'application/json'}
        )

        assert resp.status_code == 403
        payload = resp.get_json()
        assert payload['message'] == 'Apenas entregadores podem realizar esta ação.'
        assert payload['category'] == 'danger'
        assert payload['redirect'] is None


def test_accept_delivery_invalid_status_json(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        worker = User(id=1, name='Worker', email='w@x.com', worker='delivery')
        worker.set_password('x')
        buyer = User(id=2, name='Buyer', email='b@x.com')
        buyer.set_password('x')
        order = Order(id=1, user_id=2)
        req = DeliveryRequest(id=1, order_id=1, requested_by_id=2, status='em_andamento')
        db.session.add_all([worker, buyer, order, req])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: worker)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        resp = client.post(
            f'/delivery_requests/{req.id}/accept',
            headers={'Accept': 'application/json'}
        )

        assert resp.status_code == 400
        payload = resp.get_json()
        assert payload['message'] == 'Solicitação não disponível.'
        assert payload['category'] == 'warning'


def test_complete_delivery_csrf_error_returns_json(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        worker = User(id=1, name='Worker', email='w@x.com', worker='delivery')
        worker.set_password('x')
        buyer = User(id=2, name='Buyer', email='b@x.com')
        buyer.set_password('x')
        order = Order(id=1, user_id=2)
        req = DeliveryRequest(id=1, order_id=1, requested_by_id=2, worker_id=1)
        db.session.add_all([worker, buyer, order, req])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: worker)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        monkeypatch.setattr(
            DeliveryRequest.query.__class__,
            'get_or_404',
            lambda *a, **k: (_ for _ in ()).throw(app_module.CSRFError('csrf')),
        )

        resp = client.post(
            f'/delivery_requests/{req.id}/complete',
            headers={'Accept': 'application/json'}
        )

        assert resp.status_code == 400
        payload = resp.get_json()
        assert payload['message'] == 'Falha de validação. Recarregue a página e tente novamente.'
        assert payload['category'] == 'warning'
        assert payload['redirect'] is None


def test_update_tutor_duplicate_cpf(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        vet = User(id=10, name='Vet', email='vet@test', worker='veterinario')
        vet.set_password('x')
        tutor1 = User(id=1, name='Tutor1', email='t1@test', cpf='11111111111')
        tutor1.set_password('x')
        tutor2 = User(id=2, name='Tutor2', email='t2@test', cpf='22222222222')
        tutor2.set_password('x')
        db.session.add_all([vet, tutor1, tutor2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: vet)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp = client.post(f'/update_tutor/{tutor1.id}', data={'cpf': '22222222222'}, follow_redirects=True)
        assert b'CPF j\xc3\xa1 cadastrado' in resp.data
        assert User.query.get(tutor1.id).cpf == '11111111111'


def test_update_tutor_profile_photo(monkeypatch, app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        vet = User(id=10, name='Vet', email='vet@test', worker='veterinario')
        vet.set_password('x')
        tutor = User(id=1, name='Tutor', email='t@test')
        tutor.set_password('x')
        db.session.add_all([vet, tutor])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: vet)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        monkeypatch.setattr(app_module, 'upload_to_s3', lambda *a, **k: 'http://img')

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp = client.post(
            f'/update_tutor/{tutor.id}',
            data={
                'name': 'Tutor',
                'profile_photo': (BytesIO(b'img'), 'photo.jpg')
            },
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert resp.status_code == 200
        assert User.query.get(tutor.id).profile_photo == 'http://img'


def test_archive_and_unarchive_delivery(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(id=1, name='Admin', email='a@a', password_hash='x', role='admin')
        db.session.add(admin)
        order = Order(id=1, user_id=1, created_at=datetime.utcnow())
        db.session.add(order)
        req = DeliveryRequest(id=1, order_id=1, requested_by_id=1)
        db.session.add(req)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)
        monkeypatch.setattr(app_module, '_is_admin', lambda: True)

        client.post('/admin/delivery_requests/1/archive')
        assert DeliveryRequest.query.get(1).archived is True

        resp = client.get('/admin/delivery_overview')
        assert b'Pedido #1' not in resp.data

        resp = client.get('/admin/delivery_archive')
        assert b'Pedido #1' in resp.data
        assert b'Voltar' in resp.data
        assert b'href="/admin/delivery_overview"' in resp.data

        client.post('/admin/delivery_requests/1/unarchive')
        assert DeliveryRequest.query.get(1).archived is False


def test_delivery_overview_shows_relatorio_racoes_link(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(id=1, name='Admin', email='a@a', password_hash='x', role='admin')
        db.session.add(admin)
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: admin)
        monkeypatch.setattr(app_module, '_is_admin', lambda: True)

        resp = client.get('/admin/delivery_overview')
        assert b'href="/relatorio/racoes"' in resp.data


def test_relatorio_racoes_includes_navbar(app):
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(id=1, name='User', email='user@test.com')
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()

    login_resp = client.post(
        '/login',
        data={'email': 'user@test.com', 'password': 'secret'},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    response = client.get('/relatorio/racoes')
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert '<li class="nav-item dropdown"' in html or 'js/navbar-dropdown.js' in html


def test_delivery_requests_hide_archived(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(id=1, name='Buyer', email='b@b')
        user.set_password('x')
        order1 = Order(id=1, user_id=1, created_at=datetime.utcnow())
        order2 = Order(id=2, user_id=1, created_at=datetime.utcnow())
        db.session.add_all([user, order1, order2])
        dr1 = DeliveryRequest(id=1, order_id=1, requested_by_id=1, status='em_andamento')
        dr2 = DeliveryRequest(id=2, order_id=2, requested_by_id=1, status='em_andamento', archived=True)
        db.session.add_all([dr1, dr2])
        db.session.commit()

        import flask_login.utils as login_utils
        monkeypatch.setattr(login_utils, '_get_user', lambda: user)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        for idx, fn in enumerate(flask_app.template_context_processors[None]):
            if fn.__name__ == 'inject_unread_count':
                flask_app.template_context_processors[None][idx] = lambda: {'unread_messages': 0}

        resp = client.get('/delivery_requests')
        html = resp.get_data(as_text=True)
        assert 'Pedido\xa0#1' in html
        assert 'Pedido\xa0#2' not in html

        resp = client.get('/delivery_archive')
        html = resp.get_data(as_text=True)
        assert 'Pedido #2' in html
        assert 'Pedido #1' not in html



def test_upload_document(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(id=1, name='Tutor', email='t@t')
        tutor.set_password('x')
        vet = User(id=2, name='Vet', email='v@v', worker='veterinario')
        vet.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=tutor.id)
        db.session.add_all([tutor, vet, animal])
        db.session.commit()
        animal_id = animal.id
        vet_id = vet.id

    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet_id))
    monkeypatch.setattr(app_module, 'upload_to_s3', lambda *a, **k: 'http://doc')

    resp = client.post(
        f'/animal/{animal_id}/documentos',
        data={'documento': (BytesIO(b'data'), 'resultado.pdf')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert AnimalDocumento.query.filter_by(animal_id=animal_id).count() == 1


def test_upload_document_redirects_to_referrer(app, monkeypatch):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(id=1, name='Tutor', email='t@t')
        tutor.set_password('x')
        vet = User(id=2, name='Vet', email='v@v', worker='veterinario')
        vet.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=tutor.id)
        db.session.add_all([tutor, vet, animal])
        db.session.commit()
        animal_id = animal.id
        vet_id = vet.id

    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet_id))
    monkeypatch.setattr(app_module, 'upload_to_s3', lambda *a, **k: 'http://doc')

    resp = client.post(
        f'/animal/{animal_id}/documentos',
        data={'documento': (BytesIO(b'data'), 'resultado.pdf')},
        content_type='multipart/form-data',
        headers={'Referer': f'/consulta/{animal_id}'},
    )
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/consulta/{animal_id}')


def test_consulta_page_shows_documentos_tab(app, monkeypatch):
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(id=1, name='Tutor', email='t@t')
        tutor.set_password('x')
        vet = User(id=2, name='Vet', email='v@v', worker='veterinario')
        vet.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=tutor.id)
        db.session.add_all([tutor, vet, animal])
        db.session.commit()
        animal_id = animal.id
        vet_id = vet.id

    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet_id))

    resp = client.get(f'/consulta/{animal_id}')
    assert resp.status_code == 200
    assert 'Documentos' in resp.get_data(as_text=True)


def test_delete_document_by_veterinarian(app, monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(id=1, name='Tutor', email='t@t')
        tutor.set_password('x')
        vet = User(id=2, name='Vet', email='v@v', worker='veterinario')
        vet.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=tutor.id)
        doc = AnimalDocumento(id=1, animal_id=animal.id, veterinario_id=vet.id, filename='res.pdf', file_url='http://doc')
        db.session.add_all([tutor, vet, animal, doc])
        db.session.commit()
        animal_id = animal.id
        doc_id = doc.id
        vet_id = vet.id

    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(vet_id))

    class DummyS3:
        def delete_object(self, *a, **k):
            pass

    monkeypatch.setattr(app_module, '_s3', lambda: DummyS3())

    client = app.test_client()
    resp = client.post(
        f'/animal/{animal_id}/documentos/{doc_id}/delete',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert AnimalDocumento.query.get(doc_id) is None


def test_documentos_whatsapp_button_rendered(app):
    with app.app_context():
        with flask_app.test_request_context():
            template = flask_app.jinja_env.get_template('partials/documentos.html')
            tutor = SimpleNamespace(name='Fulano', phone='+55 (11) 98765-4321')
            doc = SimpleNamespace(id=1, veterinario_id=1, filename='doc.pdf', file_url='http://example.com/doc.pdf')
            animal = SimpleNamespace(id=1, documentos=[doc])
            current_user = SimpleNamespace(role='admin', worker='veterinario', id=1)
            rendered = template.render(animal=animal, tutor=tutor, current_user=current_user)
            phone_digits = ''.join(filter(str.isdigit, tutor.phone))
            expected_text = quote(f'Olá {tutor.name}! Segue o documento: {doc.file_url}', safe='/')
            expected_url = f'https://api.whatsapp.com/send?phone={phone_digits}&text={expected_text}'
            assert expected_url in rendered


def test_delete_document_by_admin(app, monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()
        tutor = User(id=1, name='Tutor', email='t@t')
        tutor.set_password('x')
        vet = User(id=2, name='Vet', email='v@v', worker='veterinario')
        vet.set_password('x')
        admin = User(id=3, name='Admin', email='a@a', role='admin')
        admin.set_password('x')
        animal = Animal(id=1, name='Dog', user_id=tutor.id)
        doc = AnimalDocumento(id=1, animal_id=animal.id, veterinario_id=vet.id, filename='res.pdf', file_url='http://doc')
        db.session.add_all([tutor, vet, admin, animal, doc])
        db.session.commit()
        animal_id = animal.id
        doc_id = doc.id
        admin_id = admin.id

    import flask_login.utils as login_utils
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(admin_id))

    class DummyS3:
        def delete_object(self, *a, **k):
            pass

    monkeypatch.setattr(app_module, '_s3', lambda: DummyS3())

    client = app.test_client()
    resp = client.post(
        f'/animal/{animal_id}/documentos/{doc_id}/delete',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert AnimalDocumento.query.get(doc_id) is None


def _create_orcamento_fixture():
    db.drop_all()
    db.create_all()
    owner = User(id=1, name='Owner', email='owner@test', worker='veterinario')
    owner.set_password('secret')
    clinic = Clinica(id=1, nome='Clinica Teste', owner_id=owner.id)
    owner.clinica_id = clinic.id
    budget = Orcamento(id=1, clinica_id=clinic.id, descricao='Orçamento Teste', status='draft')
    db.session.add_all([owner, clinic, budget])
    db.session.commit()
    return SimpleNamespace(owner_id=owner.id, clinic_id=clinic.id, orcamento_id=budget.id)


def test_atualizar_status_orcamento_sucesso(app):
    with app.app_context():
        data = _create_orcamento_fixture()
        orcamento_id = data.orcamento_id
        owner_id = data.owner_id

    client = app.test_client()
    login(client, owner_id)
    resp = client.patch(
        f'/orcamento/{orcamento_id}/status',
        json={'status': 'approved'},
        headers={'Accept': 'application/json'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'approved'

    with app.app_context():
        updated = Orcamento.query.get(orcamento_id)
        assert updated.status == 'approved'


def test_atualizar_status_orcamento_invalido(app):
    with app.app_context():
        data = _create_orcamento_fixture()
        orcamento_id = data.orcamento_id
        owner_id = data.owner_id

    client = app.test_client()
    login(client, owner_id)
    resp = client.patch(
        f'/orcamento/{orcamento_id}/status',
        json={'status': 'unknown'},
        headers={'Accept': 'application/json'},
    )
    assert resp.status_code == 400


def test_atualizar_status_orcamento_sem_acesso_retorna_403(app):
    with app.app_context():
        data = _create_orcamento_fixture()
        orcamento_id = data.orcamento_id
        other_clinic_owner = User(id=2, name='Outro', email='other@test', worker='veterinario')
        other_clinic_owner.set_password('secret')
        other_clinic = Clinica(id=2, nome='Outra Clinica', owner_id=other_clinic_owner.id)
        other_clinic_owner.clinica_id = other_clinic.id
        db.session.add_all([other_clinic_owner, other_clinic])
        db.session.commit()
        other_id = other_clinic_owner.id

    client = app.test_client()
    login(client, other_id)
    resp = client.patch(
        f'/orcamento/{orcamento_id}/status',
        json={'status': 'approved'},
        headers={'Accept': 'application/json'},
    )
    assert resp.status_code == 403
