from datetime import datetime

import app as app_module
import flask_login.utils as login_utils
from flask_login import AnonymousUserMixin

from extensions import db
from models import (
    AdminActionNotification,
    CasaDeRacao,
    DeliveryRequest,
    Order,
    OrderItem,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Product,
    User,
)


def _admin_and_buyer(monkeypatch):
    admin = User(id=1, name='Admin', email='admin@test.com', password_hash='x', role='admin')
    buyer = User(id=2, name='Cliente', email='cliente@test.com', password_hash='x')
    db.session.add_all([admin, buyer])
    db.session.commit()
    monkeypatch.setattr(login_utils, '_get_user', lambda: admin)
    monkeypatch.setattr(app_module, '_is_admin', lambda: True)
    return admin, buyer


def test_admin_notifications_support_ajax_without_full_layout(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        admin, _ = _admin_and_buyer(monkeypatch)
        note = AdminActionNotification(
            recipient_user_id=admin.id,
            event_type='store_purchase',
            entity_type='order',
            entity_id=42,
            title='Nova compra na loja',
            body='Uma cliente realizou uma compra.',
            priority='high',
            status='unread',
            idempotency_key='store-purchase-42',
        )
        db.session.add(note)
        db.session.commit()

        response = client.get(
            '/admin/notificacoes?status=open',
            headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert 'admin-notifications-panel' in payload['html']
        assert 'Nova compra na loja' in payload['html']
        assert '<html' not in payload['html'].lower()

        response = client.post(
            f'/admin/notificacoes/{note.id}/ler',
            headers={'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
        )
        assert response.status_code == 200
        assert response.is_json
        assert db.session.get(AdminActionNotification, note.id).status == 'read'


def test_admin_notifications_page_has_ajax_navigation(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        _admin_and_buyer(monkeypatch)

        response = client.get('/admin/notificacoes')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'Central de notificações' in html
        assert "'X-Requested-With': 'XMLHttpRequest'" in html
        assert 'history.pushState' in html
        assert 'data-notifications-filter' in html


def test_delivery_overview_shows_requests_before_collapsed_products(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        admin, buyer = _admin_and_buyer(monkeypatch)
        product = Product(id=1, name='Ração teste', price=10, stock=8)
        order = Order(id=1, user_id=buyer.id, created_at=datetime.utcnow())
        request_item = DeliveryRequest(
            id=1,
            order_id=order.id,
            requested_by_id=buyer.id,
            tipo_entrega='plataforma',
        )
        db.session.add_all([product, order, request_item])
        db.session.commit()

        response = client.get('/admin/delivery_overview')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert html.index('Solicitacoes abertas') < html.index('Ver produtos em estoque')
        assert html.index('Pesquisa com tutores') < html.index('Ver produtos em estoque')
        assert 'class="collapse mt-3" id="products-stock"' in html


def test_admin_can_see_and_accept_available_delivery(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        admin, buyer = _admin_and_buyer(monkeypatch)
        order = Order(id=1, user_id=buyer.id, created_at=datetime.utcnow())
        request_item = DeliveryRequest(
            id=1,
            order_id=order.id,
            requested_by_id=buyer.id,
            tipo_entrega='plataforma',
        )
        db.session.add_all([order, request_item])
        db.session.commit()

        page = client.get('/delivery_requests')
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert 'Disponíveis' in html
        assert 'Aceitar' in html
        assert 'Pedido\xa0#1' in html

        response = client.post(
            '/delivery_requests/1/accept',
            headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        )
        payload = response.get_json()
        accepted = db.session.get(DeliveryRequest, request_item.id)

        assert response.status_code == 200
        assert accepted.worker_id == admin.id
        assert accepted.status == 'em_andamento'
        assert payload['redirect'] == '/admin/delivery/1'

        counts = client.get('/api/delivery_counts').get_json()
        assert counts['available_total'] == 0
        assert counts['doing'] == 1


def _paid_store_order(monkeypatch):
    admin, buyer = _admin_and_buyer(monkeypatch)
    buyer.phone = '16999998888'
    store = CasaDeRacao(
        nome='PetOrlândia Centro',
        owner_id=admin.id,
        status='ativa',
        valor_frete=5,
        modo_entrega='plataforma',
    )
    db.session.add(store)
    db.session.flush()
    product = Product(
        id=1,
        name='Produto com repasse privado',
        price=28,
        stock=5,
        status='active',
        casa_de_racao_id=store.id,
    )
    order = Order(
        id=1,
        user_id=buyer.id,
        created_at=datetime.utcnow(),
        shipping_address='Rua Segura, 123',
    )
    db.session.add_all([product, order])
    db.session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        item_name=product.name,
        quantity=1,
        unit_price=31.11,
        seller_unit_amount=28,
        platform_fee_amount=3.11,
        seller_type='casa_de_racao',
        seller_id=store.id,
    )
    payment = Payment(
        order_id=order.id,
        user_id=buyer.id,
        method=PaymentMethod.PIX,
        status=PaymentStatus.COMPLETED,
        amount=36.11,
        transaction_id='mp-secret-123',
    )
    delivery = DeliveryRequest(
        id=1,
        order_id=order.id,
        requested_by_id=buyer.id,
        casa_de_racao_id=store.id,
        tipo_entrega='plataforma',
    )
    db.session.add_all([item, payment, delivery])
    db.session.commit()
    return admin, buyer, order, payment


def test_buyer_never_sees_seller_payout_or_internal_ids(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        _admin, buyer, order, _payment = _paid_store_order(monkeypatch)
        monkeypatch.setattr(login_utils, '_get_user', lambda: buyer)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)

        response = client.get(f'/pedido/{order.id}')
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert order.public_reference in html
        assert 'Subtotal dos produtos' in html and 'R$ 31.11' in html
        assert 'Frete' in html and 'R$ 5.00' in html
        assert 'Total pago' in html and 'R$ 36.11' in html
        assert 'R$ 28.00' not in html
        assert 'Pedido #1' not in html
        assert 'ID 2' not in html


def test_admin_purchase_summary_contains_operational_and_financial_details(monkeypatch, app):
    from blueprints.loja import _order_paid_admin_body

    with app.app_context():
        _admin, _buyer, order, payment = _paid_store_order(monkeypatch)
        body = _order_paid_admin_body(order, payment)

        assert 'Pedido interno: #1' in body
        assert f'Referência do cliente: {order.public_reference}' in body
        assert 'Cliente: Cliente' in body
        assert 'E-mail: cliente@test.com' in body
        assert 'Telefone: 16999998888' in body
        assert 'Endereço de entrega: Rua Segura, 123' in body
        assert 'Pagamento: PIX' in body
        assert 'Produtos cobrados: R$ 31,11' in body
        assert 'Frete cobrado: R$ 5,00' in body
        assert 'Total pago: R$ 36,11' in body
        assert 'Repasse dos produtos: R$ 28,00' in body
        assert 'Margem da plataforma nos produtos: R$ 3,11' in body
        assert 'Produto com repasse privado: 1 x R$ 31,11 = R$ 31,11' in body
        assert 'PetOrlândia Centro: R$ 5,00 · Entrega pela plataforma' in body


def test_payment_status_requires_owner_and_hides_technical_ids(monkeypatch, app):
    client = app.test_client()
    with app.app_context():
        _admin, buyer, _order, payment = _paid_store_order(monkeypatch)

        monkeypatch.setattr(login_utils, '_get_user', lambda: AnonymousUserMixin())
        anonymous = client.get(f'/payment_status/{payment.id}?status=success')
        assert anonymous.status_code == 302
        assert '/login' in anonymous.headers['Location']

        outsider = User(id=3, name='Outra pessoa', email='outra@test.com', password_hash='x')
        db.session.add(outsider)
        db.session.commit()
        monkeypatch.setattr(login_utils, '_get_user', lambda: outsider)
        monkeypatch.setattr(app_module, '_is_admin', lambda: False)
        assert client.get(f'/payment_status/{payment.id}?status=success').status_code in {403, 404}
        assert client.get(f'/api/payment_status/{payment.id}').status_code in {403, 404}

        monkeypatch.setattr(login_utils, '_get_user', lambda: buyer)
        response = client.get(f'/payment_status/{payment.id}?status=success')
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert payment.transaction_id not in html
        assert 'Detalhes técnicos do pagamento' not in html
        assert 'Status interno' not in html
