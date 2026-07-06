from extensions import db
from models import CasaDeRacao, Product, User


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def _setup_foreign_pending_store():
    admin = User(name='Admin Produtos', email='admin-produtos@test', password_hash='x', role='admin')
    owner = User(name='Dono Loja', email='dono-loja@test', password_hash='x')
    outsider = User(name='Sem Acesso', email='sem-acesso-loja@test', password_hash='x')
    db.session.add_all([admin, owner, outsider])
    db.session.flush()
    store = CasaDeRacao(nome='Loja Alheia', owner_id=owner.id, status='pendente')
    db.session.add(store)
    db.session.commit()
    return admin.id, owner.id, outsider.id, store.id


def test_admin_manages_products_of_foreign_pending_store(app, client):
    with app.app_context():
        admin_id, _, _, store_id = _setup_foreign_pending_store()

    _login(client, admin_id)
    dashboard = client.get(f'/casa-de-racao/{store_id}#produtos')
    assert dashboard.status_code == 200
    assert b'Publicar produto' in dashboard.data
    assert b'aguardando aprova' not in dashboard.data

    created = client.post(
        f'/casa-de-racao/{store_id}',
        data={
            '_action': 'add_product', 'name': 'Racao Administrada',
            'description': 'Criada pelo administrador', 'price': '49.90',
            'stock': '8', 'category': '', 'mp_category_id': 'pet_supplies',
        },
    )
    assert created.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(casa_de_racao_id=store_id, name='Racao Administrada').one()
        product_id = product.id

    edited = client.post(
        f'/casa-de-racao/{store_id}/produto/{product_id}/editar',
        data={
            'name': 'Racao Revisada', 'description': 'Editada pelo administrador',
            'price': '59.90', 'stock': '12', 'category': '',
            'mp_category_id': 'pet_supplies',
        },
    )
    assert edited.status_code == 302
    assert client.post(f'/casa-de-racao/{store_id}/produto/{product_id}/toggle').status_code == 302
    with app.app_context():
        product = db.session.get(Product, product_id)
        assert product.name == 'Racao Revisada'
        assert product.status == 'inactive'


def test_pending_store_owner_cannot_publish_before_approval(app, client):
    with app.app_context():
        _, owner_id, _, store_id = _setup_foreign_pending_store()
    _login(client, owner_id)
    response = client.post(
        f'/casa-de-racao/{store_id}',
        data={'_action': 'add_product', 'name': 'Produto Prematuro', 'price': '10.00', 'stock': '1', 'category': ''},
    )
    assert response.status_code == 302
    with app.app_context():
        assert Product.query.filter_by(casa_de_racao_id=store_id).count() == 0


def test_unrelated_user_cannot_manage_store_products(app, client):
    with app.app_context():
        _, _, outsider_id, store_id = _setup_foreign_pending_store()
    _login(client, outsider_id)
    assert client.get(f'/casa-de-racao/{store_id}/produtos').status_code == 404
