import os
import pathlib
import sys

import pytest
from datetime import datetime, timedelta, date
import flask_login.utils as login_utils

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')

from app import app as flask_app, db
from models import (
    User,
    Clinica,
    Veterinario,
    Animal,
    Appointment,
    Consulta,
    BlocoPrescricao,
    Prescricao,
    BlocoExames,
    ExameSolicitado,
    Vacina,
    ExamAppointment,
    Message,
    DeliveryRequest,
    Order,
    OrderItem,
    Product,
)


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )
    flask_app.config['SQLALCHEMY_BINDS'] = {}
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.session.remove()
            try:
                db.engine.dispose()
            except Exception:
                pass
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    """Stub Flask-Login to always return a fresh instance of ``user``."""

    user_id = getattr(user, 'id', user)

    def _load_user():
        return User.query.get(user_id)

    monkeypatch.setattr(login_utils, '_get_user', _load_user)


def create_basic_clinic_data():
    clinic = Clinica(id=1, nome='Clínica Central', cnpj='123')
    admin = User(id=1, name='Admin', email='admin@test', role='admin')
    admin.set_password('secret')
    tutor = User(id=2, name='Tutor', email='tutor@test')
    tutor.set_password('secret')
    vet_user = User(id=3, name='Dra. Vet', email='vet@test', role='veterinario', worker='veterinario')
    vet_user.set_password('secret')
    vet = Veterinario(id=1, user=vet_user, crmv='CRMV123', clinica=clinic)
    animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica=clinic)
    db.session.add_all([clinic, admin, tutor, vet_user, vet, animal])
    db.session.commit()
    return admin, tutor, vet_user, vet, animal, clinic


def test_manage_appointments_json_and_delete(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        appointments = []
        for idx in range(3):
            appt = Appointment(
                id=idx + 1,
                animal_id=animal.id,
                tutor_id=tutor.id,
                veterinario_id=vet.id,
                scheduled_at=datetime.utcnow() + timedelta(days=idx + 1),
                status='scheduled',
                clinica_id=clinic.id,
            )
            appointments.append(appt)
            db.session.add(appt)
        db.session.commit()
        first_appointment_id = appointments[0].id
        admin_id = admin.id
    login(monkeypatch, admin_id)

    response = client.get('/appointments/manage?per_page=2', headers={'Accept': 'application/json'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['next_page'] == 2
    assert 'Tutor' in data['html']

    delete_response = client.post(
        f'/appointments/{first_appointment_id}/delete',
        headers={'Accept': 'application/json'},
        data={},
    )
    assert delete_response.status_code == 200
    delete_data = delete_response.get_json()
    assert delete_data['success'] is True

    with flask_app.app_context():
        remaining_ids = {appt.id for appt in Appointment.query.all()}
        assert first_appointment_id not in remaining_ids
        assert len(remaining_ids) == 2


def test_ficha_animal_ajax_sections(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()

        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='finalizada',
            created_at=datetime.utcnow() - timedelta(days=10),
        )
        db.session.add(consulta)

        retorno = Appointment(
            id=10,
            animal_id=animal.id,
            tutor_id=tutor.id,
            veterinario_id=vet.id,
            scheduled_at=datetime.utcnow() + timedelta(days=2),
            status='scheduled',
            clinica_id=clinic.id,
            consulta_id=consulta.id,
        )
        db.session.add(retorno)

        exam_request = ExamAppointment(
            id=1,
            animal_id=animal.id,
            specialist_id=vet.id,
            requester_id=vet_user.id,
            scheduled_at=datetime.utcnow() + timedelta(days=5),
            status='pending',
        )
        db.session.add(exam_request)

        futura_vacina = Vacina(
            id=1,
            animal_id=animal.id,
            nome='Vacina Antirrábica',
            aplicada=False,
            aplicada_em=date.today() + timedelta(days=15),
        )
        vacina_atrasada = Vacina(
            id=2,
            animal_id=animal.id,
            nome='Reforço',
            aplicada=False,
            aplicada_em=date.today() - timedelta(days=3),
        )
        vacina_aplicada = Vacina(
            id=3,
            animal_id=animal.id,
            nome='V8',
            aplicada=True,
            aplicada_em=date.today() - timedelta(days=40),
        )
        db.session.add_all([futura_vacina, vacina_atrasada, vacina_aplicada])

        bloco_prescricao = BlocoPrescricao(id=1, animal_id=animal.id)
        prescricao = Prescricao(
            id=1,
            bloco_id=1,
            medicamento='Antibiótico',
            animal_id=animal.id,
        )
        bloco_exames = BlocoExames(id=1, animal_id=animal.id)
        exame_solicitado = ExameSolicitado(
            id=1,
            bloco_id=1,
            nome='Hemograma',
        )
        db.session.add_all([bloco_prescricao, prescricao, bloco_exames, exame_solicitado])
        db.session.commit()
        animal_id = animal.id
        admin_id = admin.id
    login(monkeypatch, admin_id)

    events_resp = client.get(
        f'/animal/{animal_id}/ficha?section=events',
        headers={'Accept': 'application/json'},
    )
    assert events_resp.status_code == 200
    events_data = events_resp.get_json()
    assert events_data['success'] is True
    assert 'Vacinas Agendadas' in events_data['html']
    assert 'Retornos' in events_data['html']

    history_resp = client.get(
        f'/animal/{animal_id}/ficha?section=history',
        headers={'Accept': 'application/json'},
    )
    assert history_resp.status_code == 200
    history_data = history_resp.get_json()
    assert history_data['success'] is True
    assert 'Prescrições' in history_data['html']
    assert 'Vacinas Aplicadas' in history_data['html']


def test_mensagens_admin_ajax(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        other_user = User(id=50, name='Cliente', email='cliente@test')
        other_user.set_password('secret')
        db.session.add(other_user)
        db.session.commit()

        animal_message = Message(
            id=1,
            sender_id=other_user.id,
            receiver_id=admin.id,
            animal_id=animal.id,
            content='Olá, preciso de ajuda',
            timestamp=datetime.utcnow(),
        )
        general_message = Message(
            id=2,
            sender_id=other_user.id,
            receiver_id=admin.id,
            content='Mensagem geral',
            timestamp=datetime.utcnow() - timedelta(minutes=5),
        )
        db.session.add_all([animal_message, general_message])
        db.session.commit()
        admin_id = admin.id
    login(monkeypatch, admin_id)

    animal_resp = client.get(
        '/mensagens_admin?kind=animals&per_page=1',
        headers={'Accept': 'application/json'},
    )
    assert animal_resp.status_code == 200
    animal_data = animal_resp.get_json()
    assert 'Cliente' in animal_data['html']
    assert 'Sobre o animal' in animal_data['html']

    general_resp = client.get(
        '/mensagens_admin?kind=general&per_page=1',
        headers={'Accept': 'application/json'},
    )
    assert general_resp.status_code == 200
    general_data = general_resp.get_json()
    assert 'Cliente' in general_data['html']
    assert 'Ver Conversa' in general_data['html']


def test_delivery_detail_ajax(client, monkeypatch):
    with flask_app.app_context():
        admin, tutor, vet_user, vet, animal, clinic = create_basic_clinic_data()
        buyer = tutor
        product = Product(id=1, name='Ração', price=59.9)
        order = Order(id=1, user=buyer, shipping_address='Rua das Flores, 123')
        item = OrderItem(
            id=1,
            order=order,
            product=product,
            quantity=2,
            item_name=product.name,
            unit_price=product.price,
        )
        delivery = DeliveryRequest(
            id=1,
            order=order,
            requested_by_id=buyer.id,
            requested_at=datetime.utcnow() - timedelta(hours=1),
            status='pendente',
        )
        db.session.add_all([product, order, item, delivery])
        db.session.commit()
        admin_id = admin.id
    login(monkeypatch, admin_id)

    resp = client.get('/delivery/1', headers={'Accept': 'application/json'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['status'] == 'pendente'
    assert any(event['label'] == 'Solicitado' for event in data['timeline'])
