from datetime import timedelta
from types import SimpleNamespace

from bs4 import BeautifulSoup
import flask_login.utils as login_utils
import pytest

import authz
from extensions import db
from models import CasaDeRacao, ClinicStaff, Clinica, Product, User, Veterinario
from models import DeliveryRequest, Order, OrderItem, Payment, PaymentMethod, PaymentStatus, ProductEvent
from services.workspaces import current_experience
from time_utils import utcnow


def user_for(monkeypatch, role='tutor', worker=None):
    user = User(name='Pessoa Teste', email='workspace@example.test', role=role, worker=worker)
    user.set_password('test-password')
    db.session.add(user)
    db.session.commit()
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)
    return user


@pytest.mark.parametrize('role,worker,expected', [
    ('tutor', None, None), ('adotante', None, None), ('doador', None, None),
    ('admin', None, 'admin'), ('parceiro', None, 'partner'),
    ('vacinador', None, 'vaccinator'), ('tutor', 'delivery', 'delivery'),
    ('tutor', 'colaborador', 'professional'), ('tutor', 'estudante', 'student'),
    ('gestor', None, 'accounting'), ('master', None, 'accounting'),
])
def test_home_and_navigation_share_workspaces(app, client, monkeypatch, role, worker, expected):
    user_for(monkeypatch, role, worker)
    response = client.get('/')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    assert len(soup.find_all('main')) == 1
    areas = soup.select('[data-dashboard-area]')
    if expected:
        assert areas[0]['data-dashboard-area'] == expected
    else:
        assert not soup.select('.dashboard-work-area')
    assert 'Tudo em dia por aqui' not in response.get_data(as_text=True)


def test_pending_store_is_primary_and_can_prepare_but_not_publish(app, client, monkeypatch):
    owner = user_for(monkeypatch)
    store = CasaDeRacao(nome='Loja Teste', owner_id=owner.id, status='pendente')
    db.session.add(store)
    db.session.commit()
    response = client.get('/')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('.dashboard-work-area')['data-dashboard-area'] == 'store'
    assert client.get(f'/casa-de-racao/{store.id}/produtos').status_code == 200
    response = client.post(f'/casa-de-racao/{store.id}/produtos', data={
        'name': 'Produto preparado', 'price': '15', 'stock': '4', 'category': '',
        'subscription_discount_percent': '0', 'subscription_shipping_fee': '0',
    })
    assert response.status_code == 302
    product = Product.query.filter_by(name='Produto preparado').one()
    assert product.status == 'pending'
    assert client.get(f'/produto/{product.id}').status_code == 404
    client.post(f'/casa-de-racao/{store.id}/produto/{product.id}/toggle')
    db.session.refresh(product)
    assert product.status == 'pending'
    cart = client.post(f'/carrinho/adicionar/{product.id}', data={'quantity': 1}, headers={'Accept': 'application/json'})
    assert cart.status_code == 409
    store.status = 'ativa'
    db.session.commit()
    client.post(f'/casa-de-racao/{store.id}/produto/{product.id}/toggle')
    db.session.refresh(product)
    assert product.status == 'active'
    assert client.get(f'/produto/{product.id}').status_code == 200


def test_invalid_dashboard_product_keeps_values_and_errors(app, client, monkeypatch):
    owner = user_for(monkeypatch)
    store = CasaDeRacao(nome='Loja', owner_id=owner.id, status='pendente')
    db.session.add(store)
    db.session.commit()
    response = client.post(f'/casa-de-racao/{store.id}', data={
        '_action': 'add_product', 'name': 'Produto em preenchimento', 'price': 'abc', 'stock': '4',
    })
    assert response.status_code == 400
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('input[name="name"]')['value'] == 'Produto em preenchimento'
    assert soup.select_one('form[enctype="multipart/form-data"]')['action'].endswith('/produtos')


def test_expired_internship_never_appears_as_operational_workspace(app, monkeypatch):
    user = user_for(monkeypatch, worker='estudante')
    clinic = Clinica(nome='Clínica')
    db.session.add(clinic)
    db.session.flush()
    db.session.add(ClinicStaff(clinic_id=clinic.id, user_id=user.id, is_intern=True,
                              internship_ends_at=utcnow() - timedelta(days=1)))
    db.session.commit()
    with app.test_request_context('/'):
        experience = current_experience()
        assert 'internship' not in experience.capabilities
        assert 'start_consultation' not in experience.capabilities


@pytest.mark.parametrize('profile', ['tutor', 'clinica', 'veterinario', 'estudante'])
def test_public_ctas_match_selected_profile(client, profile):
    response = client.get('/?perfil=' + profile)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    assert len(soup.find_all('main')) == 1
    panel = soup.select_one('[data-profile-panel]')
    assert panel['data-profile-panel'] == profile
    assert all(link['href'] == panel['data-primary-url'] for link in soup.select('[data-profile-primary]'))
    assert soup.select_one('[role="tab"][aria-selected="true"]')['tabindex'] == '0'


@pytest.mark.parametrize('permission', [authz.can_view_budget, authz.can_manage_budget,
    authz.can_view_financial, authz.can_view_fiscal_documents, authz.can_manage_fiscal_documents])
def test_global_admin_scope_is_consistent_without_expanding_other_users(permission):
    admin = SimpleNamespace(id=1, role='admin', worker=None, clinicas=[], clinic_roles=[])
    tutor = SimpleNamespace(id=2, role='tutor', worker=None, clinicas=[], clinic_roles=[], clinica_id=100)
    staff = SimpleNamespace(id=3, role='tutor', worker='colaborador', clinicas=[], clinic_roles=[], clinica_id=100)
    assert permission(admin, 200)
    assert not permission(admin, None)
    assert not permission(tutor, 100)
    assert not permission(staff, 200)


def test_tutor_clinic_link_does_not_become_operational_access(app, client, monkeypatch):
    user = user_for(monkeypatch)
    clinic = Clinica(nome='Clínica do tutor')
    db.session.add(clinic)
    db.session.flush()
    user.clinica_id = clinic.id
    db.session.commit()
    soup = BeautifulSoup(client.get('/').data, 'html.parser')
    assert not soup.select('.dashboard-work-area')


def make_order(user, product, status):
    order = Order(user_id=user.id)
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=product.id, item_name=product.name,
                             quantity=1, unit_price=20))
    db.session.add(Payment(order_id=order.id, user_id=user.id, amount=20,
                           method=PaymentMethod.PIX, status=status))
    db.session.commit()
    return order


def test_repurchase_is_private_and_only_lists_current_public_products(app, client, monkeypatch):
    user = user_for(monkeypatch)
    product = Product(name='Produto comprável', price=18, stock=2, status='active')
    db.session.add(product)
    db.session.commit()
    order = make_order(user, product, PaymentStatus.COMPLETED)
    url = f'/pedidos/{order.id}/comprar-novamente'
    response = client.get(url)
    assert response.status_code == 200
    assert 'Produto comprável' in response.get_data(as_text=True)
    product.status = 'inactive'
    db.session.commit()
    response = client.get(url)
    assert 'Nenhum produto desta compra' in response.get_data(as_text=True)
    other = User(name='Outro', email='other@example.test', password_hash='x')
    db.session.add(other)
    db.session.commit()
    monkeypatch.setattr(login_utils, '_get_user', lambda: other)
    assert client.get(url).status_code == 404


def test_store_sales_excludes_unpaid_carts(app, client, monkeypatch):
    user = user_for(monkeypatch)
    store = CasaDeRacao(nome='Loja', owner_id=user.id, status='ativa')
    db.session.add(store)
    db.session.flush()
    product = Product(name='Produto', price=18, stock=4, casa_de_racao_id=store.id)
    db.session.add(product)
    db.session.commit()
    paid = make_order(user, product, PaymentStatus.COMPLETED)
    pending = make_order(user, product, PaymentStatus.PENDING)
    response = client.get(f'/casa-de-racao/{store.id}/vendas')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert f'# {paid.id}' in html
    assert f'# {pending.id}' not in html
    assert 'Vendas confirmadas (produtos)' in html
    dashboard = client.get(f'/casa-de-racao/{store.id}')
    soup = BeautifulSoup(dashboard.data, 'html.parser')
    assert dashboard.status_code == 200
    assert len(soup.find_all('h1')) == 1
    sales_metric = soup.select_one('.store-metrics a[href$="/vendas"]')
    assert sales_metric.select_one('.fw-bold').get_text(strip=True) == '1'


@pytest.mark.parametrize('name', ['order_repurchase', 'workspace_open', 'home_next_action'])
def test_workspace_conversion_events_are_recorded(app, client, name):
    response = client.post('/eventos/cta', json={'name': name, 'path': '/', 'text': 'Ação'})
    assert response.status_code == 204
    assert ProductEvent.query.filter_by(event_name=name).count() == 1


@pytest.mark.parametrize('action', ['complete', 'cancel'])
def test_terminal_delivery_cannot_transition_again(app, client, monkeypatch, action):
    user = user_for(monkeypatch, worker='delivery')
    order = Order(user_id=user.id)
    db.session.add(order)
    db.session.flush()
    delivery = DeliveryRequest(order_id=order.id, requested_by_id=user.id, worker_id=user.id,
                               status='concluida', tipo_entrega='plataforma')
    db.session.add(delivery)
    db.session.commit()
    response = client.post(f'/delivery_requests/{delivery.id}/{action}', headers={'Accept': 'application/json'})
    assert response.status_code == 409
    db.session.refresh(delivery)
    assert delivery.status == 'concluida'
