import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import date, time

import pytest
import flask_login.utils as login_utils
from sqlalchemy.pool import StaticPool
from app import app as flask_app, db
from models import User, Animal, Veterinario, Clinica, Appointment, AppointmentRequest, Message, VetSchedule


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()


def login(monkeypatch, user):
    monkeypatch.setattr(login_utils, '_get_user', lambda: user)


def _seed():
    clinic = Clinica(id=1, nome='Clinica')
    tutor = User(id=1, name='Tutor', email='t@t', role='adotante')
    tutor.set_password('x')
    vet_user = User(id=2, name='Dra Vet', email='v@v', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(id=1, user_id=2, crmv='123', clinica_id=1)
    animal = Animal(id=1, name='Rex', user_id=1, clinica_id=1)
    horario = VetSchedule(
        veterinario_id=1,
        dia_semana='Quinta',
        hora_inicio=time(13, 0),
        hora_fim=time(16, 0),
    )
    db.session.add_all([clinic, tutor, vet_user, vet, animal, horario])
    db.session.commit()


def _tutor():
    return type('U', (), {
        'id': 1, 'role': 'adotante', 'worker': None, 'name': 'Tutor',
        'is_authenticated': True, 'veterinario': None,
    })()


def _vet():
    return type('U', (), {
        'id': 2, 'role': 'adotante', 'worker': 'veterinario', 'name': 'Dra Vet',
        'is_authenticated': True, 'veterinario': type('V', (), {'id': 1})(),
    })()


def test_tutor_solicita_e_vet_confirma(client, monkeypatch):
    with flask_app.app_context():
        _seed()

    # --- Tutor cria a solicitação ---
    login(monkeypatch, _tutor())
    with client.session_transaction() as s:
        s['user_id'] = 1

    resp = client.post('/veterinario/1/solicitar', data={
        'animal_id': 1, 'kind': 'vacina', 'mode': 'domicilio',
        'preferred_date': '2026-07-01', 'preferred_time': '09:00', 'notes': 'V10',
    })
    assert resp.status_code == 302

    with flask_app.app_context():
        req = AppointmentRequest.query.one()
        assert req.status == 'pending'
        assert req.kind == 'vacina' and req.mode == 'domicilio'
        assert Message.query.filter_by(receiver_id=2).count() == 1  # vet notificado
        rid = req.id

    # --- Privacidade: tutor vê o perfil público, NÃO a agenda de gestão ---
    body = client.get('/veterinario/1').get_data(as_text=True)
    assert 'Solicitar agendamento' in body
    assert 'Agenda do veterinário' not in body
    assert 'Adicionar Horário' not in body

    # --- Vet confirma, gerando o Appointment real ---
    login(monkeypatch, _vet())
    with client.session_transaction() as s:
        s['user_id'] = 2

    resp = client.post(f'/solicitacoes/{rid}/responder', data={
        'action': 'confirm', 'date': '2026-07-02', 'time': '14:30', 'response_note': 'Confirmado',
    })
    assert resp.status_code == 302

    with flask_app.app_context():
        req = AppointmentRequest.query.get(rid)
        assert req.status == 'confirmed'
        assert req.appointment_id is not None
        appt = Appointment.query.get(req.appointment_id)
        assert appt is not None
        assert appt.kind == 'vacina' and appt.status == 'scheduled'
        assert Message.query.filter_by(receiver_id=1).count() == 1  # tutor notificado


def test_vet_recusa_solicitacao(client, monkeypatch):
    with flask_app.app_context():
        _seed()

    login(monkeypatch, _tutor())
    with client.session_transaction() as s:
        s['user_id'] = 1
    client.post('/veterinario/1/solicitar', data={
        'animal_id': 1, 'kind': 'consulta', 'mode': 'clinica', 'preferred_date': '2026-07-01',
    })
    with flask_app.app_context():
        rid = AppointmentRequest.query.one().id

    login(monkeypatch, _vet())
    with client.session_transaction() as s:
        s['user_id'] = 2
    resp = client.post(f'/solicitacoes/{rid}/responder', data={
        'action': 'decline', 'response_note': 'Agenda cheia',
    })
    assert resp.status_code == 302

    with flask_app.app_context():
        req = AppointmentRequest.query.get(rid)
        assert req.status == 'declined'
        assert Appointment.query.count() == 0
        assert Message.query.filter_by(receiver_id=1).count() == 1


def test_vet_nao_confirma_fora_da_carga_horaria(client, monkeypatch):
    with flask_app.app_context():
        _seed()

    login(monkeypatch, _tutor())
    with client.session_transaction() as s:
        s['user_id'] = 1
    client.post('/veterinario/1/solicitar', data={
        'animal_id': 1, 'kind': 'consulta', 'mode': 'clinica',
        'preferred_date': '2026-07-01', 'preferred_time': '09:00',
    })
    with flask_app.app_context():
        rid = AppointmentRequest.query.one().id

    login(monkeypatch, _vet())
    with client.session_transaction() as s:
        s['user_id'] = 2
    resp = client.post(f'/solicitacoes/{rid}/responder', data={
        'action': 'confirm', 'date': '2026-07-02', 'time': '18:30',
    })
    assert resp.status_code == 302

    with flask_app.app_context():
        req = AppointmentRequest.query.get(rid)
        assert req.status == 'pending'
        assert Appointment.query.count() == 0


def test_tutor_nao_acessa_solicitacoes_de_outro(client, monkeypatch):
    with flask_app.app_context():
        _seed()
        outro_tutor = User(id=3, name='Outro', email='o@o', role='adotante')
        outro_tutor.set_password('x')
        outro_animal = Animal(id=2, name='Mia', user_id=3, clinica_id=1)
        req = AppointmentRequest(
            tutor_id=3,
            animal_id=2,
            veterinario_id=1,
            clinica_id=1,
            kind='consulta',
            mode='clinica',
            preferred_date=date(2026, 7, 1),
            preferred_time=time(9, 0),
            status='pending',
        )
        db.session.add_all([outro_tutor, outro_animal, req])
        db.session.commit()
        rid = req.id

    # O tutor 1 não pode cancelar a solicitação de outro tutor.
    login(monkeypatch, _tutor())
    with client.session_transaction() as s:
        s['user_id'] = 1
    resp = client.post(f'/solicitacoes/{rid}/cancelar')
    assert resp.status_code in {403, 404}
    with flask_app.app_context():
        assert AppointmentRequest.query.get(rid).status == 'pending'
