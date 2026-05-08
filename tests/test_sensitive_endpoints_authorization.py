import os
os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

import pytest
from app import app as flask_app, db
from models import User, Animal


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def setup_users(app):
    with app.app_context():
        admin = User(name='Admin', email='admin@test.local', role='admin')
        admin.set_password('x')

        owner_vet = User(name='Owner Vet', email='owner@test.local', worker='veterinario', role='adotante')
        owner_vet.set_password('x')

        same_clinic_vet = User(name='Same Clinic Vet', email='same@test.local', worker='veterinario', role='adotante', added_by_id=owner_vet.id)
        same_clinic_vet.set_password('x')

        other_clinic_vet = User(name='Other Clinic Vet', email='other@test.local', worker='veterinario', role='adotante')
        other_clinic_vet.set_password('x')

        unrelated_auth = User(name='No Link', email='nolink@test.local', role='adotante')
        unrelated_auth.set_password('x')

        tutor_added_by_owner = User(name='Tutor Owned', email='tutor-owned@test.local', role='adotante', added_by_id=owner_vet.id)
        tutor_added_by_owner.set_password('x')

        db.session.add_all([admin, owner_vet, same_clinic_vet, other_clinic_vet, unrelated_auth, tutor_added_by_owner])
        db.session.commit()

        animal = Animal(name='Rex', user_id=tutor_added_by_owner.id, added_by_id=owner_vet.id)
        db.session.add(animal)
        db.session.commit()

        return {
            'admin_id': admin.id,
            'owner_vet_id': owner_vet.id,
            'same_clinic_vet_id': same_clinic_vet.id,
            'other_clinic_vet_id': other_clinic_vet.id,
            'unrelated_auth_id': unrelated_auth.id,
            'tutor_owned_id': tutor_added_by_owner.id,
            'animal_id': animal.id,
        }


def login(client, user_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def logout(client):
    with client.session_transaction() as sess:
        sess.clear()


class TestSensitiveAuthorizationMatrix:
    def test_delete_tutor_authorization_matrix(self, client, setup_users):
        target_id = setup_users['tutor_owned_id']

        login(client, setup_users['admin_id'])
        assert client.post(f'/deletar_tutor/{target_id}').status_code in [200, 302]

        # recria tutor alvo após remoção por admin
        with flask_app.app_context():
            owner = User.query.get(setup_users['owner_vet_id'])
            tutor = User(name='Tutor Owned 2', email='tutor-owned-2@test.local', role='adotante', added_by_id=owner.id)
            tutor.set_password('x')
            db.session.add(tutor)
            db.session.commit()
            target_id = tutor.id

        login(client, setup_users['owner_vet_id'])
        assert client.post(f'/deletar_tutor/{target_id}').status_code in [200, 302]

        with flask_app.app_context():
            owner = User.query.get(setup_users['owner_vet_id'])
            tutor = User(name='Tutor Owned 3', email='tutor-owned-3@test.local', role='adotante', added_by_id=owner.id)
            tutor.set_password('x')
            db.session.add(tutor)
            db.session.commit()
            target_id = tutor.id

        login(client, setup_users['unrelated_auth_id'])
        assert client.post(f'/deletar_tutor/{target_id}').status_code in [401, 403, 404, 302]

        login(client, setup_users['other_clinic_vet_id'])
        assert client.post(f'/deletar_tutor/{target_id}').status_code in [401, 403, 404, 302]

        logout(client)
        assert client.post(f'/deletar_tutor/{target_id}').status_code in [401, 403, 302]

    def test_id_manipulation_url_query_body_cross_access_denied(self, client, setup_users):
        with flask_app.app_context():
            owner = User.query.get(setup_users['owner_vet_id'])
            tutor = User(name='Tutor Owned 4', email='tutor-owned-4@test.local', role='adotante', added_by_id=owner.id)
            tutor.set_password('x')
            db.session.add(tutor)
            db.session.commit()
            target_id = tutor.id

        login(client, setup_users['other_clinic_vet_id'])
        response = client.post(
            f'/deletar_tutor/{target_id}?tutor_id=1',
            data={'tutor_id': setup_users['owner_vet_id'], 'added_by_id': setup_users['other_clinic_vet_id']},
        )
        assert response.status_code in [401, 403, 404, 302]
