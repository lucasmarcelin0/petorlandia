import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import flask_login.utils as login_utils
from datetime import datetime, timedelta

from app import app as flask_app, db
from models import User, Veterinario, Clinica, Animal, ExamAppointment


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def test_confirmed_requested_exam_visible_with_status_badge(client, monkeypatch):
    with flask_app.app_context():
        clinic = Clinica(id=1, nome='Clinica')
        requester_user = User(
            id=1,
            name='Dr. Requester',
            email='requester@test',
            worker='veterinario',
            role='adotante',
        )
        requester_user.set_password('x')
        requester_vet = Veterinario(
            id=1,
            user=requester_user,
            crmv='REQ123',
            clinica=clinic,
        )

        specialist_user = User(
            id=2,
            name='Dr. Specialist',
            email='specialist@test',
            worker='veterinario',
        )
        specialist_user.set_password('y')
        specialist_vet = Veterinario(
            id=2,
            user=specialist_user,
            crmv='SPEC456',
            clinica=clinic,
        )

        tutor_user = User(
            id=3,
            name='Tutor',
            email='tutor@test',
            worker='adotante',
            role='adotante',
        )
        tutor_user.set_password('z')

        animal = Animal(
            id=1,
            name='Rex',
            status='available',
            user_id=tutor_user.id,
            clinica=clinic,
        )

        exam = ExamAppointment(
            id=1,
            animal=animal,
            specialist=specialist_vet,
            requester=requester_user,
            scheduled_at=datetime.utcnow() + timedelta(days=1),
            status='confirmed',
        )

        db.session.add_all(
            [
                clinic,
                requester_user,
                requester_vet,
                specialist_user,
                specialist_vet,
                tutor_user,
                animal,
                exam,
            ]
        )
        db.session.commit()

        requester_vet_id = requester_vet.id
        requester_user_id = requester_user.id
        requester_user_name = requester_user.name
        clinic_id = clinic.id

    fake_user = type(
        'U',
        (),
        {
            'id': requester_user_id,
            'worker': 'veterinario',
            'role': 'adotante',
            'name': requester_user_name,
            'is_authenticated': True,
            'veterinario': type(
                'V',
                (),
                {
                    'id': requester_vet_id,
                    'user_id': requester_user_id,
                    'user': type('WU', (), {'name': requester_user_name})(),
                    'clinica_id': clinic_id,
                },
            )(),
        },
    )()

    login(monkeypatch, fake_user)

    response = client.get('/appointments')
    assert response.status_code == 200
    html = response.data.decode()
    assert 'Exames aguardando outros profissionais' in html
    assert 'Rex' in html
    assert 'Confirmado' in html
    assert 'Confirmado pelo especialista' in html


def test_exam_default_deadline_attributes_present(client, monkeypatch):
    with flask_app.app_context():
        flask_app.config['EXAM_CONFIRM_DEFAULT_HOURS'] = 5

        clinic = Clinica(id=10, nome='Clinica')
        requester_user = User(
            id=10,
            name='Dra. Solicitação',
            email='requester2@test',
            worker='veterinario',
            role='adotante',
        )
        requester_user.set_password('abc')
        requester_vet = Veterinario(
            id=10,
            user=requester_user,
            crmv='REQ987',
            clinica=clinic,
        )

        specialist_user = User(
            id=20,
            name='Dr. Outro',
            email='specialist2@test',
            worker='veterinario',
        )
        specialist_user.set_password('def')
        specialist_vet = Veterinario(
            id=20,
            user=specialist_user,
            crmv='SPEC654',
            clinica=clinic,
        )

        tutor_user = User(
            id=30,
            name='Tutor 2',
            email='tutor2@test',
            worker='adotante',
            role='adotante',
        )
        tutor_user.set_password('ghi')

        animal = Animal(
            id=40,
            name='Bolt',
            status='available',
            user_id=tutor_user.id,
            clinica=clinic,
        )

        exam = ExamAppointment(
            id=50,
            animal=animal,
            specialist=specialist_vet,
            requester=requester_user,
            scheduled_at=datetime.utcnow() + timedelta(days=2),
            request_time=datetime(2024, 1, 2, 12, 0),
            status='confirmed',
        )
        exam.confirm_by = None

        db.session.add_all(
            [
                clinic,
                requester_user,
                requester_vet,
                specialist_user,
                specialist_vet,
                tutor_user,
                animal,
                exam,
            ]
        )
        db.session.commit()

        requester_vet_id = requester_vet.id
        requester_user_id = requester_user.id
        requester_user_name = requester_user.name
        clinic_id = clinic.id

    fake_user = type(
        'U',
        (),
        {
            'id': requester_user_id,
            'worker': 'veterinario',
            'role': 'adotante',
            'name': requester_user_name,
            'is_authenticated': True,
            'veterinario': type(
                'V',
                (),
                {
                    'id': requester_vet_id,
                    'user_id': requester_user_id,
                    'user': type('WU', (), {'name': requester_user_name})(),
                    'clinica_id': clinic_id,
                },
            )(),
        },
    )()

    login(monkeypatch, fake_user)

    response = client.get('/appointments')
    assert response.status_code == 200
    html = response.data.decode()
    assert 'data-exam-default-confirm-hours="5"' in html
    assert 'data-exam-requested-at="' in html
    assert 'data-exam-confirm-by=""' in html
    assert 'id="exam-requester-apply-default"' in html
    assert 'O prazo padrão é de 5 horas após a solicitação.' in html
