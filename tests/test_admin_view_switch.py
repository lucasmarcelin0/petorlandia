import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from app import app as flask_app, db
from models import User, Animal, Veterinario, Clinica, Appointment


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.drop_all()
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def setup_data():
    clinic = Clinica(id=1, nome='Clinica')
    tutor = User(id=1, name='Tutor', email='tutor@test')
    tutor.set_password('x')
    admin = User(id=2, name='Admin', email='admin@test', role='admin')
    admin.set_password('x')
    vet_user = User(id=3, name='Vet', email='vet@test', worker='veterinario')
    vet_user.set_password('x')
    animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
    vet = Veterinario(id=1, user_id=vet_user.id, clinica_id=clinic.id, crmv='123')
    db.session.add_all([clinic, tutor, admin, vet_user, animal, vet])
    db.session.commit()
    return admin


def test_admin_can_switch_views(client, monkeypatch):
    with flask_app.app_context():
        admin = setup_data()
        admin_id = admin.id
    fake_admin = type(
        'U',
        (),
        {
            'id': admin_id,
            'role': 'admin',
            'worker': None,
            'is_authenticated': True,
            'clinica_id': None,
            'name': 'Admin',
        },
    )()
    login(monkeypatch, fake_admin)
    resp = client.get('/appointments?view_as=veterinario')
    assert resp.status_code == 200
    resp = client.get('/appointments?view_as=colaborador')
    assert resp.status_code == 200
    resp = client.get('/appointments?view_as=tutor')
    assert resp.status_code == 200
    resp = client.get('/appointments/manage')
    assert b'view_as=colaborador' in resp.data
    assert b'view_as=veterinario' in resp.data
    assert b'view_as=tutor' in resp.data


def test_non_admin_view_as_redirects(client, monkeypatch):
    with flask_app.app_context():
        setup_data()
        collaborator = User(
            id=10,
            name='Colab',
            email='colab@test',
            worker='colaborador',
            clinica_id=1,
        )
        collaborator.set_password('x')
        db.session.add(collaborator)
        db.session.commit()
        tutor = User.query.filter_by(email='tutor@test').first()
        tutor_id = tutor.id
        collab_id = collaborator.id

    fake_collaborator = type(
        'U',
        (),
        {
            'id': collab_id,
            'worker': 'colaborador',
            'role': 'adotante',
            'is_authenticated': True,
            'clinica_id': 1,
        },
    )()
    login(monkeypatch, fake_collaborator)
    resp = client.get('/appointments?view_as=veterinario')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/appointments')

    fake_tutor = type(
        'U',
        (),
        {
            'id': tutor_id,
            'worker': None,
            'role': 'adotante',
            'is_authenticated': True,
            'clinica_id': None,
        },
    )()
    login(monkeypatch, fake_tutor)
    resp = client.get('/appointments?view_as=veterinario')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/appointments')


def test_admin_collaborator_post_preserves_query_and_lists_new_appointment(client, monkeypatch):
    with flask_app.app_context():
        setup_data()
        admin = User.query.filter_by(role='admin').first()
        animal = Animal.query.first()
        vet = Veterinario.query.first()
        vet_id = vet.id
        admin_id = admin.id
        animal_id = animal.id

    fake_admin = type(
        'U',
        (),
        {
            'id': admin_id,
            'role': 'admin',
            'worker': None,
            'is_authenticated': True,
            'clinica_id': None,
            'name': 'Admin',
        },
    )()

    login(monkeypatch, fake_admin)

    query_string = f'?view_as=colaborador&veterinario_id={vet_id}'
    resp = client.post(
        f'/appointments{query_string}',
        data={
            'appointment-animal_id': str(animal_id),
            'appointment-veterinario_id': str(vet_id),
            'appointment-date': '2024-05-20',
            'appointment-time': '09:00',
            'appointment-kind': 'consulta',
            'appointment-reason': 'Checkup',
            'appointment-submit': True,
        },
    )

    assert resp.status_code == 302
    location = resp.headers['Location']
    assert 'view_as=colaborador' in location
    assert f'veterinario_id={vet_id}' in location

    with flask_app.app_context():
        appt = Appointment.query.one()
        appointment_id = appt.id

    follow_resp = client.get(f'/appointments{query_string}')
    assert follow_resp.status_code == 200
    assert b'Nova Consulta' in follow_resp.data
    assert f'data-appointment-id="{appointment_id}"'.encode() in follow_resp.data


def test_admin_vet_defaults_to_own_agenda_and_other_agendas_deactivated(client, monkeypatch):
    with flask_app.app_context():
        setup_data()
        clinic = Clinica.query.first()
        admin_vet_user = User(id=99, name='Dra Admin', email='dra_admin@test', role='admin', worker='veterinario')
        admin_vet_user.set_password('x')
        db.session.add(admin_vet_user)
        db.session.commit()
        admin_vet = Veterinario(id=99, user_id=admin_vet_user.id, clinica_id=clinic.id, crmv='9999')
        db.session.add(admin_vet)
        db.session.commit()
        admin_vet_id = admin_vet.id
        admin_user_id = admin_vet_user.id

    fake_admin_vet = type(
        'U',
        (),
        {
            'id': admin_user_id,
            'role': 'admin',
            'worker': 'veterinario',
            'is_authenticated': True,
            'clinica_id': 1,
            'name': 'Dra Admin',
            'veterinario': type('V', (), {'id': admin_vet_id, 'user': type('VU', (), {'name': 'Dra Admin'})(), 'clinica_id': 1, 'specialty_list': []})(),
        },
    )()

    login(monkeypatch, fake_admin_vet)

    # 1. Acesso padrão /appointments sem parâmetros: abre diretamente a agenda do próprio admin vet
    resp = client.get('/appointments')
    assert resp.status_code == 200
    assert b'Agenda \xe2\x80\x93 Dra Admin' in resp.data or b'Dra Admin' in resp.data
    # O seletor de outras agendas deve estar desativado por padrão
    assert b'admin-agenda-picker' not in resp.data
    # O gatilho do Easter Egg no ícone deve estar presente
    assert b'data-admin-other-agendas-toggle' in resp.data
    assert b'data-active="false"' in resp.data

    # 2. Ativação do modo multi-agendas via parâmetro other_agendas=1
    resp_active = client.get('/appointments?other_agendas=1')
    assert resp_active.status_code == 200
    assert b'data-active="true"' in resp_active.data
    assert b'Multi-agendas' in resp_active.data
    # Agora o seletor de outras agendas deve aparecer
    assert b'data-admin-agenda-switcher' in resp_active.data

    # 3. Desativação via other_agendas=0
    resp_inactive = client.get('/appointments?other_agendas=0')
    assert resp_inactive.status_code == 200
    assert b'data-active="false"' in resp_inactive.data
    assert b'admin-agenda-picker' not in resp_inactive.data


def test_toggle_other_agendas_api_endpoint(client, monkeypatch):
    with flask_app.app_context():
        setup_data()
        admin = User.query.filter_by(role='admin').first()
        admin_id = admin.id

    fake_admin = type(
        'U',
        (),
        {
            'id': admin_id,
            'role': 'admin',
            'worker': None,
            'is_authenticated': True,
            'clinica_id': None,
            'name': 'Admin',
        },
    )()

    login(monkeypatch, fake_admin)

    # Chamada POST para alternar para ativo
    resp = client.post(
        '/api/admin/toggle_other_agendas',
        json={'active': True},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    json_data = resp.get_json()
    assert json_data['success'] is True
    assert json_data['active'] is True
    assert 'other_agendas=1' in json_data['redirect_url']

    # Chamada POST para alternar para inativo
    resp2 = client.post(
        '/api/admin/toggle_other_agendas',
        json={'active': False},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp2.status_code == 200
    json_data2 = resp2.get_json()
    assert json_data2['success'] is True
    assert json_data2['active'] is False
    assert 'other_agendas=0' in json_data2['redirect_url']
