import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime

import pytest
import flask_login.utils as login_utils

from app import app as flask_app, db, TUTOR_SEARCH_LIMIT
from models import User, Clinica, Appointment, Animal, Veterinario


@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )

    with flask_app.app_context():
        db.drop_all()
        db.create_all()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def login(monkeypatch, user):
    user_id = getattr(user, 'id', user)

    def _load_user():
        return User.query.get(user_id)

    monkeypatch.setattr(login_utils, '_get_user', _load_user)


def test_buscar_tutores_respects_limit(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome='Clínica 1')
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name='Staff',
            email='staff@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
        )
        db.session.add(staff)
        db.session.flush()

        for idx in range(TUTOR_SEARCH_LIMIT + 10):
            user = User(
                name=f"Tutor {idx:03d}",
                email=f"tutor{idx}@example.com",
                password_hash="hash",
                is_private=False,
                clinica_id=clinic.id,
            )
            db.session.add(user)
        db.session.commit()

        staff_id = staff.id

    login(monkeypatch, staff_id)

    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')

    assert response.status_code == 200

    data = response.get_json()

    assert len(data) == TUTOR_SEARCH_LIMIT
    names = [item['name'] for item in data]
    assert names == sorted(names)
    assert f"Tutor {TUTOR_SEARCH_LIMIT:03d}" not in names
    expected_keys = {
        'id',
        'name',
        'email',
        'cpf',
        'rg',
        'phone',
        'worker',
        'created_at',
        'date_of_birth',
        'address',
        'specialties',
        'veterinario_id',
    }
    assert set(data[0].keys()) == expected_keys
    assert data[0]['address'] is None
    assert isinstance(data[0]['specialties'], list)
    assert 'details' not in data[0]
    assert 'address_summary' not in data[0]


def test_buscar_tutores_sort_recent_added(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome='Clínica 1')
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name='Staff',
            email='staff@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
        )
        tutor_old = User(
            name='Tutor Antigo',
            email='antigo@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
            created_at=datetime(2023, 1, 1),
        )
        tutor_new = User(
            name='Tutor Novo',
            email='novo@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
            created_at=datetime(2024, 1, 1),
        )
        db.session.add_all([staff, tutor_old, tutor_new])
        db.session.commit()
        staff_id = staff.id

    login(monkeypatch, staff_id)
    client = app.test_client()
    response = client.get('/buscar_tutores', query_string={'q': 'Tutor', 'sort': 'recent_added'})
    assert response.status_code == 200
    data = response.get_json()
    names = [item['name'] for item in data]
    assert names[:2] == ['Tutor Novo', 'Tutor Antigo']
    assert isinstance(data[0]['specialties'], list)


def test_buscar_tutores_sort_recent_attended(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome='Clínica 1')
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name='Staff',
            email='staff@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
        )

        vet_user = User(
            name='Vet',
            email='vet@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            worker='veterinario',
            is_private=False,
        )
        db.session.add(vet_user)
        db.session.flush()

        vet = Veterinario(user_id=vet_user.id, crmv='12345', clinica_id=clinic.id)

        tutor_one = User(
            name='Tutor Um',
            email='tutor1@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
        )
        tutor_two = User(
            name='Tutor Dois',
            email='tutor2@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
        )
        db.session.add_all([staff, vet, tutor_one, tutor_two])
        db.session.flush()

        animal_one = Animal(
            name='Rex',
            user_id=tutor_one.id,
            clinica_id=clinic.id,
        )
        animal_two = Animal(
            name='Mia',
            user_id=tutor_two.id,
            clinica_id=clinic.id,
        )
        db.session.add_all([animal_one, animal_two])
        db.session.flush()

        appt_one = Appointment(
            animal_id=animal_one.id,
            tutor_id=tutor_one.id,
            veterinario_id=vet.id,
            scheduled_at=datetime(2024, 1, 1, 9, 0, 0),
            status='completed',
            clinica_id=clinic.id,
        )
        appt_two = Appointment(
            animal_id=animal_two.id,
            tutor_id=tutor_two.id,
            veterinario_id=vet.id,
            scheduled_at=datetime(2024, 2, 1, 9, 0, 0),
            status='completed',
            clinica_id=clinic.id,
        )
        db.session.add_all([appt_one, appt_two])
        db.session.commit()
        staff_id = staff.id

    login(monkeypatch, staff_id)
    client = app.test_client()
    response = client.get('/buscar_tutores', query_string={'q': 'Tutor', 'sort': 'recent_attended'})
    assert response.status_code == 200
    data = response.get_json()
    names = [item['name'] for item in data]
    assert names[:2] == ['Tutor Dois', 'Tutor Um']


def test_buscar_tutores_hides_private_profiles_for_guests(app):
    with app.app_context():
        clinic = Clinica(nome='Clínica 1')
        db.session.add(clinic)
        db.session.flush()

        public_user = User(
            name='Tutor Público',
            email='public@example.com',
            password_hash='hash',
            is_private=False,
        )
        private_user = User(
            name='Tutor Privado',
            email='private@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=True,
        )
        db.session.add_all([public_user, private_user])
        db.session.commit()

    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')
    assert response.status_code == 200
    assert response.get_json() == []


def test_buscar_tutores_shows_private_profiles_to_own_clinic(app, monkeypatch):
    with app.app_context():
        clinic = Clinica(nome='Clínica 1')
        db.session.add(clinic)
        db.session.flush()

        staff = User(
            name='Staff',
            email='staff@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=False,
        )
        private_user = User(
            name='Tutor Privado',
            email='private@example.com',
            password_hash='hash',
            clinica_id=clinic.id,
            is_private=True,
        )
        outsider = User(
            name='Tutor de Outra Clínica',
            email='other@example.com',
            password_hash='hash',
            clinica_id=None,
            is_private=False,
        )
        db.session.add_all([staff, private_user, outsider])
        db.session.commit()
        staff_id = staff.id

    login(monkeypatch, staff_id)
    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')
    assert response.status_code == 200
    names = {item['name'] for item in response.get_json()}
    assert 'Tutor Privado' in names
    assert 'Tutor de Outra Clínica' not in names


def test_buscar_tutores_ignores_other_clinics(app, monkeypatch):
    with app.app_context():
        clinic1 = Clinica(nome='Clínica 1')
        clinic2 = Clinica(nome='Clínica 2')
        db.session.add_all([clinic1, clinic2])
        db.session.flush()

        staff = User(
            name='Staff',
            email='staff@example.com',
            password_hash='hash',
            clinica_id=clinic1.id,
        )
        tutor_same = User(
            name='Tutor da Clínica 1',
            email='c1@example.com',
            password_hash='hash',
            clinica_id=clinic1.id,
        )
        tutor_other = User(
            name='Tutor da Clínica 2',
            email='c2@example.com',
            password_hash='hash',
            clinica_id=clinic2.id,
        )
        db.session.add_all([staff, tutor_same, tutor_other])
        db.session.commit()

        staff_id = staff.id

    login(monkeypatch, staff_id)

    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')

    assert response.status_code == 200
    names = {item['name'] for item in response.get_json()}
    assert 'Tutor da Clínica 1' in names
    assert 'Tutor da Clínica 2' not in names


def test_buscar_tutores_veterinario_sem_clinica_ve_tutors_que_cadastrou(app, monkeypatch):
    with app.app_context():
        vet_user = User(
            name='Vet Sem Clínica',
            email='vet-sem-clinica@example.com',
            password_hash='hash',
            worker='veterinario',
        )
        db.session.add(vet_user)
        db.session.flush()

        tutor_proprio = User(
            name='Tutor Proprio',
            email='tutor-proprio@example.com',
            password_hash='hash',
            added_by_id=vet_user.id,
        )

        outra_clinica = Clinica(nome='Outra Clínica')
        db.session.add(outra_clinica)
        db.session.flush()

        tutor_externo = User(
            name='Tutor Externo',
            email='tutor-externo@example.com',
            password_hash='hash',
            clinica_id=outra_clinica.id,
        )

        db.session.add_all([tutor_proprio, tutor_externo])
        db.session.commit()

        vet_user_id = vet_user.id

    login(monkeypatch, vet_user_id)
    client = app.test_client()
    response = client.get('/buscar_tutores?q=Tutor')

    assert response.status_code == 200

    data = response.get_json()
    names = [item['name'] for item in data]

    assert names == ['Tutor Proprio']
