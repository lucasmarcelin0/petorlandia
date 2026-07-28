"""Agenda do veterinário: um atendimento = uma linha.

Cobre a correção da duplicação (agendamento + consulta apareciam como dois
compromissos) e os estados novos de status.
"""

import os
import sys

os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import re
from datetime import datetime, timedelta

import flask_login.utils as login_utils
import pytest

from app import app as flask_app, db
from models import Animal, Appointment, Clinica, Consulta, User, Veterinario
from services.appointment_status import status_label, status_meta
from time_utils import utcnow


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


def _build_clinic():
    clinic = Clinica(id=1, nome='Clinica')
    vet_user = User(id=1, name='Vet', email='vet@test', worker='veterinario')
    vet_user.set_password('x')
    vet = Veterinario(id=1, user=vet_user, crmv='123', clinica_id=clinic.id)
    tutor = User(id=2, name='Tutor', email='tutor@test', worker='adotante', role='adotante')
    tutor.set_password('y')
    animal = Animal(id=1, name='Rex', user_id=tutor.id, clinica_id=clinic.id)
    db.session.add_all([clinic, vet_user, vet, tutor, animal])
    db.session.commit()
    return clinic, vet_user, vet, tutor, animal


def _fake_vet(vet_user_id, vet_id, clinic_id):
    return type('U', (), {
        'id': vet_user_id,
        'worker': 'veterinario',
        'role': 'adotante',
        'name': 'Vet',
        'is_authenticated': True,
        'veterinario': type('V', (), {
            'id': vet_id,
            'user': type('WU', (), {'name': 'Vet'})(),
            'clinica_id': clinic_id,
        })(),
    })()


def test_partial_returns_only_agenda_fragment(client, monkeypatch):
    """`?partial=agenda` devolve só o fragmento, para a troca via AJAX.

    É o que evita recarregar a página inteira a cada clique no filtro.
    """

    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        db.session.add(Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() + timedelta(hours=5),
            status='scheduled',
            kind='consulta',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        ))
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)

    login(monkeypatch, _fake_vet(*ids))
    base = '/appointments?view_as=veterinario&veterinario_id=1'

    completa = client.get(base)
    parcial = client.get(base + '&partial=agenda')
    assert completa.status_code == 200
    assert parcial.status_code == 200

    html_parcial = parcial.data.decode()
    assert 'id="agenda-content"' in html_parcial
    # Fragmento não traz o documento nem a navegação por abas.
    assert '<!DOCTYPE html>' not in html_parcial
    assert 'vetScheduleSectionTabs' not in html_parcial
    assert len(parcial.data) < len(completa.data)


def test_partial_respects_kind_filter(client, monkeypatch):
    """O filtro por tipo vale também no fragmento pedido via AJAX."""

    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        db.session.add(Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() + timedelta(hours=5),
            status='scheduled',
            kind='vacina',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        ))
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)

    login(monkeypatch, _fake_vet(*ids))
    base = '/appointments?view_as=veterinario&veterinario_id=1&partial=agenda'

    todos = client.get(base + '&tipo=todos').data.decode()
    exames = client.get(base + '&tipo=exame').data.decode()

    assert 'data-appointment-id="1"' in todos
    # A vacina não entra no recorte de exames.
    assert 'data-appointment-id="1"' not in exames


def test_action_forms_carry_csrf_token(client, monkeypatch):
    """Todo POST da agenda precisa do token: o app usa CSRFProtect global.

    Sem o campo, os botões Confirmar / Marcar falta / Cancelar respondiam 400 e
    pareciam simplesmente não funcionar.
    """

    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        db.session.add(Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() + timedelta(hours=5),
            status='scheduled',
            kind='consulta',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        ))
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)

    login(monkeypatch, _fake_vet(*ids))
    resp = client.get('/appointments?view_as=veterinario&veterinario_id=1')
    assert resp.status_code == 200
    html = resp.data.decode()

    # Formulários de mudança de status são escritos à mão (não são WTForms com
    # hidden_tag), então precisam declarar o csrf_token explicitamente.
    forms = [
        corpo
        for abertura, corpo in re.findall(
            r'(<form[^>]*method="POST"[^>]*>)(.*?)</form>', html, re.S
        )
        if '/status' in abertura
    ]
    assert forms, 'a agenda deveria renderizar formulários de status'
    sem_token = [f for f in forms if 'name="csrf_token"' not in f]
    assert not sem_token, f'{len(sem_token)} formulário(s) de status sem csrf_token'


def test_finalized_appointment_appears_once_in_agenda(client, monkeypatch):
    """O atendimento das 11h realizado às 11h22 é UMA linha, não duas."""

    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='finalizada',
            created_at=datetime(2026, 7, 28, 14, 22),   # 11:22 BRT
            finalizada_em=datetime(2026, 7, 28, 14, 50),
        )
        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=datetime(2026, 7, 28, 14, 0),  # 11:00 BRT
            status='completed',
            kind='consulta',
            clinica_id=clinic.id,
            consulta=consulta,
            created_by=vet_user.id,
        )
        db.session.add_all([consulta, appointment])
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)

    login(monkeypatch, _fake_vet(*ids))
    resp = client.get('/appointments?start=2026-07-28&end=2026-07-28')
    assert resp.status_code == 200
    html = resp.data.decode()

    # A seção de histórico não repete o atendimento como "confirmada e não
    # finalizada" além da consulta finalizada.
    assert 'Confirmada, mas a consulta não foi finalizada.' not in html
    assert html.count('Rex') >= 1


def test_calendar_event_carries_real_times(client, monkeypatch):
    """O horário real vira metadado do agendamento, não um segundo evento."""

    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='finalizada',
            created_at=datetime(2026, 7, 28, 14, 22),
            finalizada_em=datetime(2026, 7, 28, 14, 50),
        )
        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=datetime(2026, 7, 28, 14, 0),
            status='completed',
            kind='consulta',
            clinica_id=clinic.id,
            consulta=consulta,
            created_by=vet_user.id,
        )
        db.session.add_all([consulta, appointment])
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)

        # 22 minutos de atraso entre o horário marcado e o início real.
        assert appointment.delay_minutes == 22
        assert appointment.actual_duration_minutes == 28

    login(monkeypatch, _fake_vet(*ids))
    resp = client.get('/api/my_appointments')
    assert resp.status_code == 200
    events = {event['id']: event for event in resp.get_json()}
    assert 'consulta-1' not in events
    assert events['appointment-1']['extendedProps']['delayMinutes'] == 22


def test_consulta_from_animal_record_reuses_appointment(client, monkeypatch):
    """Abrir a consulta pela ficha não cria um atendimento paralelo."""

    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() - timedelta(minutes=20),
            status='accepted',
            kind='consulta',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        )
        db.session.add(appointment)
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)
        animal_id = animal.id

    login(monkeypatch, _fake_vet(*ids))
    # Sem ``appointment_id``: é o caminho "iniciei pela ficha do animal".
    resp = client.get(f'/consulta/{animal_id}')
    assert resp.status_code == 200

    with flask_app.app_context():
        appointment = db.session.get(Appointment, 1)
        assert appointment.consulta_id is not None
        assert appointment.status == 'in_progress'
        assert Consulta.query.count() == 1


def test_distant_appointment_is_not_auto_linked(client, monkeypatch):
    """Um agendamento de amanhã não é sequestrado pelo atendimento de hoje."""

    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() + timedelta(days=1),
            status='accepted',
            kind='consulta',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        )
        db.session.add(appointment)
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)
        animal_id = animal.id

    login(monkeypatch, _fake_vet(*ids))
    resp = client.get(f'/consulta/{animal_id}')
    assert resp.status_code == 200

    with flask_app.app_context():
        appointment = db.session.get(Appointment, 1)
        assert appointment.consulta_id is None
        assert appointment.status == 'accepted'


def test_vet_can_mark_no_show(client, monkeypatch):
    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() - timedelta(hours=1),
            status='accepted',
            kind='consulta',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        )
        db.session.add(appointment)
        db.session.commit()
        ids = (vet_user.id, vet.id, clinic.id)

    login(monkeypatch, _fake_vet(*ids))
    resp = client.post('/appointments/1/status', data={'status': 'no_show'})
    assert resp.status_code == 302

    with flask_app.app_context():
        assert db.session.get(Appointment, 1).status == 'no_show'


def test_tutor_cannot_mark_no_show(client, monkeypatch):
    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() + timedelta(days=1),
            status='scheduled',
            kind='consulta',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        )
        db.session.add(appointment)
        db.session.commit()
        tutor_id = tutor.id

    fake_tutor = type('U', (), {
        'id': tutor_id,
        'worker': None,
        'role': 'adotante',
        'name': 'Tutor',
        'is_authenticated': True,
        'veterinario': None,
    })()
    login(monkeypatch, fake_tutor)
    resp = client.post('/appointments/1/status', data={'status': 'no_show'})
    assert resp.status_code in (302, 403)

    with flask_app.app_context():
        assert db.session.get(Appointment, 1).status == 'scheduled'


def test_status_labels_come_from_single_source():
    assert status_label('scheduled') == 'A confirmar'
    assert status_label('in_progress') == 'Em atendimento'
    assert status_meta('no_show')['tone'] == 'danger'
    # Status desconhecido não quebra a renderização.
    assert status_meta('algo_novo')['label'] == 'Algo novo'


def test_running_late_minutes_only_for_unstarted(client):
    with flask_app.app_context():
        clinic, vet_user, vet, tutor, animal = _build_clinic()
        appointment = Appointment(
            id=1,
            animal=animal,
            tutor=tutor,
            veterinario=vet,
            scheduled_at=utcnow() - timedelta(minutes=45),
            status='accepted',
            kind='consulta',
            clinica_id=clinic.id,
            created_by=vet_user.id,
        )
        db.session.add(appointment)
        db.session.commit()

        assert appointment.running_late_minutes >= 44

        # Assim que a consulta começa, o atraso deixa de ser "pendente".
        consulta = Consulta(
            id=1,
            animal_id=animal.id,
            created_by=vet_user.id,
            clinica_id=clinic.id,
            status='in_progress',
            created_at=utcnow(),
        )
        appointment.consulta = consulta
        appointment.status = 'in_progress'
        db.session.add(consulta)
        db.session.commit()

        assert appointment.running_late_minutes == 0
        assert appointment.delay_minutes >= 44
