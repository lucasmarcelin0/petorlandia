"""Regression coverage for work-first dashboard layouts."""

import pytest

from extensions import db
from models import User, Veterinario


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


@pytest.mark.parametrize(
    ('user_kwargs', 'create_vet', 'work_area'),
    [
        ({'name': 'Veterinária', 'email': 'vet-dashboard@example.test'}, True, 'professional'),
        ({'name': 'Parceiro', 'email': 'partner-dashboard@example.test', 'role': 'parceiro'}, False, 'partner'),
        ({'name': 'Entregador', 'email': 'delivery-dashboard@example.test', 'worker': 'delivery'}, False, 'delivery'),
    ],
)
def test_work_area_precedes_personal_pets_area(client, app, user_kwargs, create_vet, work_area):
    with app.app_context():
        user = User(password_hash='x', **user_kwargs)
        db.session.add(user)
        if create_vet:
            db.session.add(Veterinario(user=user, crmv='CRMV-SP 200'))
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    page = client.get('/').get_data(as_text=True)

    assert page.index(f'data-dashboard-area="{work_area}"') < page.index(
        'data-dashboard-area="personal-pets"'
    )
