"""Matriz de acesso do prontuário hospitalar, sem herdar acesso do tutor."""

from types import SimpleNamespace

import pytest

from helpers import is_veterinarian as real_is_veterinarian
from services.internacao_access import (
    clinicas_internacao,
    pode_acessar_internacao,
    pode_operar_internacao,
    pode_prescrever_internacao,
)


def _user(**values):
    defaults = dict(
        id=10, is_authenticated=True, role='adotante', worker=None,
        clinica_id=None, clinicas=[], clinic_roles=[], veterinario=None,
        professional_active=False,
    )
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _vet(**values):
    defaults = dict(crmv='12345', is_estagiario=False, clinica_id=1, clinicas=[])
    defaults.update(values)
    return SimpleNamespace(**defaults)


@pytest.fixture(autouse=True)
def _professional_gate(monkeypatch):
    # O helper de produção segue responsável pela política da assinatura.
    # Variar o resultado comprova que o hospital não ignora essa autorização.
    monkeypatch.setattr(
        'helpers.is_veterinarian',
        lambda user: bool(getattr(user, 'professional_active', False)),
    )


@pytest.mark.parametrize('user', [None, _user(is_authenticated=False), _user(clinica_id=1)])
def test_tutor_or_anonymous_has_no_hospital_access(user):
    assert not pode_acessar_internacao(user)
    assert not pode_operar_internacao(user, 1)
    assert not pode_prescrever_internacao(user, 1)
    assert clinicas_internacao(user) == []


def test_admin_operates_globally_but_cannot_prescribe_without_qualification():
    user = _user(role='admin')
    assert pode_acessar_internacao(user)
    assert pode_operar_internacao(user, 2)
    assert not pode_prescrever_internacao(user, 2)


def test_owner_can_operate_only_owned_clinic_without_prescribing():
    user = _user(clinicas=[SimpleNamespace(id=1)])
    assert pode_operar_internacao(user, 1)
    assert not pode_operar_internacao(user, 2)
    assert not pode_prescrever_internacao(user, 1)


@pytest.mark.parametrize('worker', ['colaborador', 'staff', 'assistente'])
def test_regular_team_legacy_operates_only_its_clinic(worker):
    user = _user(worker=worker, clinica_id=1)
    assert pode_acessar_internacao(user)
    assert pode_operar_internacao(user, 1)
    assert not pode_operar_internacao(user, 2)
    assert not pode_prescrever_internacao(user, 1)


def test_explicit_regular_staff_link_handles_legacy_worker():
    user = _user(clinic_roles=[SimpleNamespace(clinic_id=1, is_intern=False)])
    assert pode_acessar_internacao(user)
    assert pode_operar_internacao(user, 1)
    assert not pode_operar_internacao(user, 2)


@pytest.mark.parametrize('active', [False, True])
def test_internship_does_not_grant_hospital_access_even_with_legacy_staff_worker(active):
    user = _user(
        worker='staff', clinica_id=1,
        clinic_roles=[SimpleNamespace(clinic_id=1, is_intern=True, internship_active=active)],
    )
    assert not pode_acessar_internacao(user)
    assert not pode_operar_internacao(user, 1)


@pytest.mark.parametrize('marker', [dict(role='estagiario'), dict(worker='estudante')])
def test_intern_account_markers_cannot_use_regular_team_or_ownership(marker):
    user = _user(
        **marker, clinicas=[SimpleNamespace(id=1)],
        clinic_roles=[SimpleNamespace(clinic_id=1, is_intern=False)],
    )
    assert not pode_operar_internacao(user, 1)
    assert not pode_acessar_internacao(user)


def test_vet_intern_profile_cannot_use_hospital_despite_crmv_or_admin_role():
    user = _user(role='admin', veterinario=_vet(is_estagiario=True), professional_active=True)
    assert not pode_operar_internacao(user, 1)
    assert not pode_prescrever_internacao(user, 1)


def test_vet_worker_without_profile_is_not_a_prescriber():
    user = _user(worker='veterinario', clinica_id=1, professional_active=True)
    assert not pode_acessar_internacao(user)
    assert not pode_prescrever_internacao(user, 1)


@pytest.mark.parametrize('crmv', [None, '', '   '])
def test_profile_without_crmv_cannot_prescribe_even_as_admin(crmv):
    user = _user(role='admin', veterinario=_vet(crmv=crmv), professional_active=True)
    assert not pode_prescrever_internacao(user, 1)


def test_active_vet_can_prescribe_in_primary_and_associated_clinics_only():
    user = _user(
        veterinario=_vet(clinicas=[SimpleNamespace(id=2)]), professional_active=True,
    )
    assert pode_operar_internacao(user, 1)
    assert pode_prescrever_internacao(user, 1)
    assert pode_prescrever_internacao(user, 2)
    assert not pode_operar_internacao(user, 3)
    assert not pode_prescrever_internacao(user, 3)


def test_inactive_vet_cannot_prescribe_even_with_ownership_or_staff_link():
    user = _user(
        veterinario=_vet(), clinicas=[SimpleNamespace(id=1)],
        clinic_roles=[SimpleNamespace(clinic_id=1, is_intern=False)],
    )
    assert pode_operar_internacao(user, 1)
    assert not pode_prescrever_internacao(user, 1)


def test_admin_vet_still_needs_local_binding_to_prescribe():
    user = _user(role='admin', veterinario=_vet(), professional_active=True)
    assert pode_operar_internacao(user, 2)
    assert not pode_prescrever_internacao(user, 2)


@pytest.mark.parametrize('clinic_id', [None, '', 0, -1, True, 'bad', 1.5, float('inf')])
def test_malformed_clinic_identifier_never_grants_access(clinic_id):
    user = _user(role='admin', veterinario=_vet(), professional_active=True)
    assert not pode_operar_internacao(user, clinic_id)
    assert not pode_prescrever_internacao(user, clinic_id)


def test_clinic_selector_is_scoped_and_admin_lists_all(app):
    from extensions import db
    from models import Clinica

    alpha = Clinica(nome='A - Internação')
    beta = Clinica(nome='B - Internação')
    db.session.add_all([alpha, beta])
    db.session.flush()
    user = _user(worker='staff', clinica_id=beta.id)
    assert [c.id for c in clinicas_internacao(user)] == [beta.id]
    assert [c.id for c in clinicas_internacao(_user(role='admin'))] == [alpha.id, beta.id]


def test_real_profile_membership_expiration_removes_prescribing_permission(app, monkeypatch):
    from datetime import timedelta

    from extensions import db
    from models import Clinica, User, Veterinario
    from time_utils import utcnow

    monkeypatch.setattr('helpers.is_veterinarian', real_is_veterinarian)
    clinic = Clinica(nome='Clínica do veterinário')
    user = User(
        name='Veterinário', email='vet-access@example.com', password_hash='test-only',
        worker='veterinario',
    )
    vet = Veterinario(user=user, clinica=clinic, crmv='SP-12345')
    db.session.add_all([clinic, user, vet])
    db.session.flush()
    assert pode_prescrever_internacao(user, clinic.id)

    vet.membership.trial_ends_at = utcnow() - timedelta(days=1)
    vet.membership.paid_until = None
    db.session.flush()
    assert not pode_prescrever_internacao(user, clinic.id)
