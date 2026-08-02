"""Cadastro de produto: salvar não pode falhar em silêncio.

O relato que originou estes testes: "a descrição fica desconfigurada" e
"ativar assinatura não muda nada na loja". Os dois viravam a mesma pergunta —
o vendedor não conseguia saber se o que ele fez chegou ao banco.
"""

from decimal import Decimal

from extensions import db
from models import Product, User


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _admin() -> User:
    admin = User(name='Admin', email='admin-produto@example.test', password_hash='x', role='admin')
    db.session.add(admin)
    db.session.commit()
    return admin


def _product(description='linha 1\nlinha 2') -> Product:
    product = Product(
        name='Shampoo Clorexidina',
        description=description,
        price=28.0,
        stock=4,
        status='active',
    )
    db.session.add(product)
    db.session.commit()
    return product


def _payload(**overrides) -> dict:
    data = {
        'upd-name': 'Shampoo Clorexidina',
        'upd-description': 'Fórmula: x\nModo de usar: y',
        'upd-price': '28.00',
        'upd-stock': '4',
        'upd-category': 'higiene',
        'upd-mp_category_id': 'others',
        'upd-subscription_discount_percent': '10.00',
        'upd-subscription_shipping_fee': '0.00',
        'upd-submit': 'Salvar',
    }
    data.update(overrides)
    return data


# ------------------------------------------------- formato brasileiro de número


def test_preco_com_virgula_e_aceito(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    response = client.post(f'/produto/{product_id}', data=_payload(
        **{'upd-price': '31,50', 'upd-subscription_discount_percent': '10,00'}
    ))

    assert response.status_code == 302
    with app.app_context():
        product = db.session.get(Product, product_id)
        assert float(product.price) == 31.50
        assert product.subscription_discount_percent == Decimal('10.00')


def test_preco_com_separador_de_milhar_e_aceito(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    client.post(f'/produto/{product_id}', data=_payload(**{'upd-price': '1.234,56'}))

    with app.app_context():
        assert float(db.session.get(Product, product_id).price) == 1234.56


def test_preco_invalido_avisa_em_vez_de_silenciar(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    response = client.post(
        f'/produto/{product_id}',
        data=_payload(**{'upd-price': 'abc'}),
        follow_redirects=True,
    )

    body = response.data.decode()
    assert 'não foi salvo' in body
    with app.app_context():
        assert float(db.session.get(Product, product_id).price) == 28.0


# ----------------------------------------------------------------- assinatura


def test_ativar_assinatura_persiste_e_aparece_na_loja(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    client.post(f'/produto/{product_id}', data=_payload(
        **{'upd-subscription_enabled': 'y'}
    ))

    with app.app_context():
        assert db.session.get(Product, product_id).subscription_enabled is True

    body = client.get(f'/produto/{product_id}').data.decode()
    assert 'Assinatura recorrente' in body
    assert 'Configurar assinatura' in body


def test_sem_assinatura_a_pagina_mostra_so_compra_unica(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    client.post(f'/produto/{product_id}', data=_payload())

    body = client.get(f'/produto/{product_id}').data.decode()
    assert 'Compra única' in body
    assert 'Configurar assinatura' not in body


def test_painel_informa_o_estado_gravado_da_assinatura(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        product.subscription_enabled = True
        product.subscription_discount_percent = Decimal('10.00')
        db.session.commit()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    body = client.get(f'/produto/{product_id}').data.decode()
    assert 'Ativa agora' in body


# ------------------------------------------------------------------ descrição


def test_quebras_de_linha_da_descricao_sobrevivem_ao_salvar(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    client.post(f'/produto/{product_id}', data=_payload(
        **{'upd-description': 'Fórmula: A\n\nIndicações: B\nModo de usar: C'}
    ))

    with app.app_context():
        salvo = db.session.get(Product, product_id).description
        assert salvo.count('\n') == 3


def test_descricao_e_exibida_preservando_paragrafos(app, client):
    with app.app_context():
        _product(description='Fórmula: A\nIndicações: B')
        product_id = Product.query.one().id

    body = client.get(f'/produto/{product_id}').data.decode()
    assert 'product-description' in body
    assert 'white-space: pre-line' in body


def test_campo_de_descricao_tem_espaco_para_uma_bula(app, client):
    with app.app_context():
        admin = _admin()
        product = _product()
        admin_id, product_id = admin.id, product.id

    _login(client, admin_id)
    body = client.get(f'/produto/{product_id}').data.decode()
    assert 'product-description-input' in body
    assert 'rows="14"' in body
