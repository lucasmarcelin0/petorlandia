from decimal import Decimal
from bs4 import BeautifulSoup
from extensions import db
from models import User, Product, Order, OrderItem, Payment, PaymentMethod, PaymentStatus


def test_purchase_history_identifies_items_and_preserves_paid_amount(client, app):
    with app.app_context():
        tutor = User(name='Juliana', email='buyer-presentation@example.test', password_hash='x')
        other = User(name='Outro tutor', email='private-presentation@example.test', password_hash='x')
        product = Product(name='Nome atual do catálogo', price=99, stock=3, image_url='img/produtos/cefalexina_500mg.png')
        no_image = Product(name='Produto sem foto', price=8, stock=1)
        db.session.add_all([tutor, other, product, no_image])
        db.session.flush()
        order = Order(user_id=tutor.id)
        private = Order(user_id=other.id)
        unpaid = Order(user_id=tutor.id)
        db.session.add_all([order, private, unpaid])
        db.session.flush()
        db.session.add_all([
            OrderItem(order_id=order.id, product_id=product.id, item_name='Produto comprado · 250 mg', quantity=2, unit_price=Decimal('12.50')),
            OrderItem(order_id=order.id, product_id=no_image.id, item_name='Segundo produto', quantity=1, unit_price=Decimal('6.11')),
            OrderItem(order_id=private.id, product_id=product.id, item_name='Produto privado', quantity=1, unit_price=1),
            Payment(order_id=order.id, user_id=tutor.id, amount=Decimal('36.11'), method=PaymentMethod.PIX, status=PaymentStatus.COMPLETED),
            Payment(order_id=private.id, user_id=other.id, amount=1, method=PaymentMethod.PIX, status=PaymentStatus.COMPLETED),
            Payment(order_id=unpaid.id, user_id=tutor.id, amount=7, method=PaymentMethod.PIX, status=PaymentStatus.PENDING),
        ])
        db.session.commit()
        user_id, order_id, private_id = tutor.id, order.id, private.id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    response = client.get('/minhas-compras')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    assert len(soup.select('.purchase-card')) == 1
    assert 'Produto comprado · 250 mg' in soup.text
    assert 'Segundo produto' in soup.text
    assert 'Produto privado' not in soup.text
    assert soup.select_one('.purchase-card__total strong').text == 'R$ 36,11'
    assert [el.text for el in soup.select('.purchase-item__price')] == ['R$ 25,00', 'R$ 6,11']
    assert soup.select_one('.purchase-item img')['src'] == '/static/img/produtos/cefalexina_500mg.png'
    assert soup.select_one('.product-media--empty')
    assert 'Pagamento aprovado' in soup.text
    assert 'Recebido em' not in soup.text
    assert 'Nome atual do catálogo' not in soup.text
    detail = client.get(f'/pedido/{order_id}')
    assert detail.status_code == 200  # A purchase without a delivery request remains readable.
    detail_text = BeautifulSoup(detail.data, 'html.parser').get_text(' ', strip=True)
    assert 'Produto comprado · 250 mg' in detail_text
    assert 'R$ 36,11' in detail_text and 'R$ 5,00' in detail_text
    assert 'Ainda não há informações de entrega' in detail_text
    assert client.get(f'/pedido/{private_id}', headers={'Accept': 'text/html'}).status_code == 403
