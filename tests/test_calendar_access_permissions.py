import json
import os
import re
from datetime import datetime, timedelta, date
from pathlib import Path
import sys
from types import SimpleNamespace

import flask_login.utils as login_utils
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')

DB_PATH = PROJECT_ROOT / 'tests' / 'calendar_access_test.sqlite'

from app import app as flask_app, db
from models import (
    Animal,
    Appointment,
    ClinicStaff,
    Clinica,
    ExamAppointment,
    User,
    Vacina,
    Veterinario,
)
from services.calendar_access import CalendarAccessScope


@pytest.fixture
def client():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{DB_PATH}",
    )
    with flask_app.test_client() as client:
        with flask_app.app_context():
            db.session.remove()
            try:
                db.engine.dispose()
            except Exception:  # pragma: no cover - defensive cleanup
                pass
            if DB_PATH.exists():
                DB_PATH.unlink()
            db.create_all()
        yield client
        with flask_app.app_context():
            db.drop_all()
        if DB_PATH.exists():
            DB_PATH.unlink()


def login(monkeypatch, user):
    user_id = getattr(user, 'id', user)

    def _load_user():
        return User.query.get(user_id)

    monkeypatch.setattr(login_utils, '_get_user', _load_user)


def extract_calendar_summary(html):
    vets_match = re.search(r"data-calendar-summary-vets='([^']*)'", html)
    assert vets_match, 'calendar summary vets metadata not found'
    vets = json.loads(vets_match.group(1))
    clinics_match = re.search(r"data-calendar-summary-clinic-ids='([^']*)'", html)
    clinics = json.loads(clinics_match.group(1)) if clinics_match else []
    return vets, clinics


def create_clinic_with_vets():
    clinic = Clinica(nome='Clínica Integrada')
    owner = User(name='Owner', email='owner@example.com', password_hash='x')
    vet_user = User(name='Vet One', email='vet1@example.com', password_hash='x', worker='veterinario')
    vet_two_user = User(name='Vet Two', email='vet2@example.com', password_hash='x', worker='veterinario')
    db.session.add_all([clinic, owner, vet_user, vet_two_user])
    db.session.commit()
    clinic.owner_id = owner.id
    db.session.add(clinic)
    vet = Veterinario(user_id=vet_user.id, crmv='CRMV1', clinica_id=clinic.id)
    vet_two = Veterinario(user_id=vet_two_user.id, crmv='CRMV2', clinica_id=clinic.id)
    db.session.add_all([vet, vet_two])
    db.session.commit()
    db.session.add_all([
        ClinicStaff(clinic_id=clinic.id, user_id=vet_user.id),
        ClinicStaff(clinic_id=clinic.id, user_id=vet_two_user.id),
    ])
    vet_user.clinica_id = clinic.id
    vet_two_user.clinica_id = clinic.id
    db.session.commit()
    return clinic, owner, vet_user, vet, vet_two_user, vet_two


def setup_vet_calendar_events(*, can_view_full_calendar=True):
    clinic_a = Clinica(nome='Clínica Norte')
    clinic_b = Clinica(nome='Clínica Sul')
    viewer_user = User(
        name='Viewer Vet',
        email='viewer@example.com',
        password_hash='x',
        worker='veterinario',
    )
    colleague_user = User(
        name='Colleague Vet',
        email='colleague@example.com',
        password_hash='x',
        worker='veterinario',
    )
    tutor_user = User(
        name='Tutor',
        email='tutor@example.com',
        password_hash='x',
    )
    db.session.add_all([clinic_a, clinic_b, viewer_user, colleague_user, tutor_user])
    db.session.commit()

    viewer_vet = Veterinario(user_id=viewer_user.id, crmv='CRMV-VIEW', clinica_id=clinic_a.id)
    colleague_vet = Veterinario(user_id=colleague_user.id, crmv='CRMV-COL', clinica_id=clinic_a.id)
    colleague_vet.clinicas.append(clinic_b)
    db.session.add_all([viewer_vet, colleague_vet])
    db.session.commit()

    viewer_user.clinica_id = clinic_a.id
    colleague_user.clinica_id = clinic_a.id
    db.session.add_all([
        ClinicStaff(
            clinic_id=clinic_a.id,
            user_id=viewer_user.id,
            can_view_full_calendar=can_view_full_calendar,
        ),
        ClinicStaff(
            clinic_id=clinic_b.id,
            user_id=viewer_user.id,
            can_view_full_calendar=can_view_full_calendar,
        ),
    ])
    db.session.commit()

    animal_a = Animal(name='Rex', user_id=tutor_user.id, clinica_id=clinic_a.id)
    animal_b = Animal(name='Luna', user_id=tutor_user.id, clinica_id=clinic_b.id)
    db.session.add_all([animal_a, animal_b])
    db.session.commit()

    now = datetime.utcnow()
    appointment_a = Appointment(
        animal_id=animal_a.id,
        tutor_id=tutor_user.id,
        veterinario_id=colleague_vet.id,
        scheduled_at=now + timedelta(days=1),
        clinica_id=clinic_a.id,
    )
    db.session.add(appointment_a)
    db.session.flush()

    colleague_vet.clinica_id = clinic_b.id
    db.session.add(colleague_vet)
    db.session.flush()

    appointment_b = Appointment(
        animal_id=animal_b.id,
        tutor_id=tutor_user.id,
        veterinario_id=colleague_vet.id,
        scheduled_at=now + timedelta(days=1, hours=1),
        clinica_id=clinic_b.id,
    )
    db.session.add(appointment_b)
    db.session.flush()

    colleague_vet.clinica_id = clinic_a.id
    db.session.add(colleague_vet)
    db.session.flush()

    exam_a = ExamAppointment(
        animal_id=animal_a.id,
        specialist_id=colleague_vet.id,
        requester_id=viewer_user.id,
        scheduled_at=now + timedelta(days=2),
        status='confirmed',
    )
    exam_b = ExamAppointment(
        animal_id=animal_b.id,
        specialist_id=colleague_vet.id,
        requester_id=viewer_user.id,
        scheduled_at=now + timedelta(days=2, hours=1),
        status='confirmed',
    )
    vaccine_a = Vacina(
        animal_id=animal_a.id,
        nome='Vacina A',
        aplicada=True,
        aplicada_em=date.today(),
        aplicada_por=colleague_user.id,
    )
    vaccine_b = Vacina(
        animal_id=animal_b.id,
        nome='Vacina B',
        aplicada=True,
        aplicada_em=date.today(),
        aplicada_por=colleague_user.id,
    )
    db.session.add_all([
        exam_a,
        exam_b,
        vaccine_a,
        vaccine_b,
    ])
    db.session.commit()

    return SimpleNamespace(
        viewer_user=viewer_user,
        viewer_vet=viewer_vet,
        colleague_vet=colleague_vet,
        clinic_a=clinic_a,
        clinic_b=clinic_b,
        animal_a=animal_a,
        animal_b=animal_b,
        appointment_a=appointment_a,
        appointment_b=appointment_b,
        exam_a=exam_a,
        exam_b=exam_b,
        vaccine_a=vaccine_a,
        vaccine_b=vaccine_b,
    )


def test_veterinarian_with_full_access_sees_colleagues(client, monkeypatch):
    with flask_app.app_context():
        clinic, _, vet_user, vet, vet_two_user, vet_two = create_clinic_with_vets()
        vet_id = vet.id
        vet_two_id = vet_two.id
        clinic_id = clinic.id
        vet_user_id = vet_user.id
    login(monkeypatch, vet_user_id)
    response = client.get('/appointments')
    assert response.status_code == 200
    vets, clinics = extract_calendar_summary(response.get_data(as_text=True))
    vet_ids = {entry['id'] for entry in vets}
    assert vet_id in vet_ids
    assert vet_two_id in vet_ids
    assert clinic_id in clinics


def test_clinic_owner_veterinarian_sees_colleagues_despite_other_restrictions(
    client, monkeypatch
):
    with flask_app.app_context():
        owned_clinic = Clinica(nome='Clínica Principal')
        other_clinic = Clinica(nome='Clínica Secundária')
        db.session.add_all([owned_clinic, other_clinic])
        db.session.commit()

        owner_user = User(
            name='Owner Vet',
            email='owner-vet@example.com',
            password_hash='x',
            worker='veterinario',
        )
        colleague_user = User(
            name='Colleague Vet',
            email='colleague-owner@example.com',
            password_hash='x',
            worker='veterinario',
        )
        db.session.add_all([owner_user, colleague_user])
        db.session.commit()

        owned_clinic.owner_id = owner_user.id
        db.session.add(owned_clinic)
        db.session.commit()

        owner_vet = Veterinario(
            user_id=owner_user.id,
            crmv='OWN-1',
            clinica_id=owned_clinic.id,
        )
        colleague_vet = Veterinario(
            user_id=colleague_user.id,
            crmv='COL-1',
            clinica_id=owned_clinic.id,
        )
        db.session.add_all([owner_vet, colleague_vet])
        db.session.commit()

        owner_user.clinica_id = owned_clinic.id
        db.session.add(owner_user)

        db.session.add_all(
            [
                ClinicStaff(
                    clinic_id=owned_clinic.id,
                    user_id=owner_user.id,
                    can_view_full_calendar=True,
                ),
                ClinicStaff(
                    clinic_id=other_clinic.id,
                    user_id=owner_user.id,
                    can_view_full_calendar=False,
                ),
            ]
        )
        db.session.commit()

        owner_id = owner_user.id
        colleague_vet_id = colleague_vet.id
        clinic_id = owned_clinic.id

    login(monkeypatch, owner_id)
    response = client.get('/appointments')
    assert response.status_code == 200
    vets, clinics = extract_calendar_summary(response.get_data(as_text=True))
    vet_ids = {entry['id'] for entry in vets}
    assert colleague_vet_id in vet_ids
    assert clinic_id in clinics


def test_owner_toggle_limits_calendar_summary(client, monkeypatch):
    with flask_app.app_context():
        clinic, owner, vet_user, vet, vet_two_user, vet_two = create_clinic_with_vets()
        clinic_id = clinic.id
        vet_id = vet.id
        vet_two_id = vet_two.id
        vet_user_id = vet_user.id
        owner_id = owner.id
        staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=vet_user.id).first()
        assert staff and staff.can_view_full_calendar is True
    login(monkeypatch, owner_id)
    response = client.post(
        f'/clinica/{clinic_id}/funcionario/{vet_user_id}/permissoes',
        data={'submit': 'Salvar'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with flask_app.app_context():
        staff = ClinicStaff.query.filter_by(clinic_id=clinic_id, user_id=vet_user_id).first()
        assert staff.can_view_full_calendar is False
    login(monkeypatch, vet_user_id)
    appointments_response = client.get('/appointments')
    assert appointments_response.status_code == 200
    vets, clinics = extract_calendar_summary(appointments_response.get_data(as_text=True))
    vet_ids = {entry['id'] for entry in vets}
    assert vet_id in vet_ids
    assert vet_two_id not in vet_ids
    assert clinic_id in clinics
    detail_response = client.get(f'/veterinario/{vet_id}')
    assert detail_response.status_code == 200
    detail_vets, detail_clinics = extract_calendar_summary(detail_response.get_data(as_text=True))
    detail_ids = {entry['id'] for entry in detail_vets}
    assert detail_ids == {vet_id}
    assert clinic_id in detail_clinics


def test_duplicate_memberships_respect_calendar_permission(client, monkeypatch):
    with flask_app.app_context():
        clinic, _, vet_user, vet, vet_two_user, vet_two = create_clinic_with_vets()
        # Simulate stale duplicate membership rows where one still has the
        # permission disabled.
        duplicate = ClinicStaff(
            clinic_id=clinic.id,
            user_id=vet_user.id,
            can_view_full_calendar=False,
        )
        db.session.add(duplicate)
        db.session.commit()
        vet_id = vet.id
        vet_two_id = vet_two.id
        clinic_id = clinic.id
        vet_user_id = vet_user.id
    login(monkeypatch, vet_user_id)
    response = client.get('/appointments')
    assert response.status_code == 200
    vets, clinics = extract_calendar_summary(response.get_data(as_text=True))
    vet_ids = {entry['id'] for entry in vets}
    assert vet_id in vet_ids
    assert vet_two_id in vet_ids, 'full calendar permission should include colleagues'
    assert clinic_id in clinics


def test_veterinarian_colleague_api_filters_by_scope(client, monkeypatch):
    with flask_app.app_context():
        data = setup_vet_calendar_events(can_view_full_calendar=True)
        viewer_user_id = data.viewer_user.id
        colleague_vet_id = data.colleague_vet.id
        clinic_a_id = data.clinic_a.id
        allowed_event_ids = {
            f'appointment-{data.appointment_a.id}',
            f'exam-{data.exam_a.id}',
            f'vaccine-{data.vaccine_a.id}',
        }
        blocked_event_ids = {
            f'appointment-{data.appointment_b.id}',
            f'exam-{data.exam_b.id}',
            f'vaccine-{data.vaccine_b.id}',
        }

    def _limited_scope(user):
        assert user.id == viewer_user_id
        return CalendarAccessScope(clinic_ids={clinic_a_id}, veterinarian_ids=None)

    monkeypatch.setattr('app.get_calendar_access_scope', _limited_scope)
    login(monkeypatch, viewer_user_id)
    response = client.get(f'/api/vet_appointments/{colleague_vet_id}')
    assert response.status_code == 200
    events = response.get_json()
    event_ids = {event['id'] for event in events}
    assert event_ids == allowed_event_ids
    assert not (event_ids & blocked_event_ids)


def test_veterinarian_colleague_api_forbidden_without_permission(client, monkeypatch):
    with flask_app.app_context():
        data = setup_vet_calendar_events(can_view_full_calendar=False)
        viewer_user_id = data.viewer_user.id
        colleague_vet_id = data.colleague_vet.id

    login(monkeypatch, viewer_user_id)
    response = client.get(f'/api/vet_appointments/{colleague_vet_id}')
    assert response.status_code == 403
