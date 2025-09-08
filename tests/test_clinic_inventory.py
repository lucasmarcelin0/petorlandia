import pytest
import routes.app as app_module
from routes.app import app as flask_app, db
from models import User, Clinica, ClinicInventoryItem
import flask_login.utils as login_utils


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    yield flask_app


def test_clinic_inventory_page(app, monkeypatch):
    client = app.test_client()
    with app.app_context():
        user = User(id=999, email="u@example.com", name="User", password_hash="x")
        clinic = Clinica(nome="Clinic", owner_id=user.id)
        db.session.add_all([user, clinic])
        db.session.commit()
        clinic_id = clinic.id
        user_id = user.id
    monkeypatch.setattr(login_utils, '_get_user', lambda: User.query.get(user_id))
    monkeypatch.setattr(app_module, '_is_admin', lambda: False)

    response = client.get(f'/clinica/{clinic_id}')
    assert response.status_code == 200
    assert b'Estoque' in response.data

    response = client.post(
        f'/clinica/{clinic_id}/estoque',
        data={'name': 'Seringa', 'quantity': 10, 'unit': 'caixa'},
        follow_redirects=True,
    )
    assert b'Seringa' in response.data
    with app.app_context():
        item = ClinicInventoryItem.query.filter_by(clinica_id=clinic_id, name='Seringa').first()
        assert item is not None
        assert item.quantity == 10
