"""O acesso fiscal não pode se apoiar só no vínculo com a clínica.

O wizard de onboarding cadastra o emissor e guarda o certificado A1; o export
entrega os XMLs autorizados. A matriz RBAC (authz.ROLE_PERMISSION_MATRIX) já
reserva ``fiscal_documents`` a admin e dono — estes testes garantem que as
rotas realmente consultam essa política.
"""

from types import SimpleNamespace

import flask_login.utils as login_utils
import pytest

from app import db, fiscal_exports_xmls, fiscal_onboarding_step
from models import Clinica


def _login(monkeypatch, user):
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)


def _vet_user(clinic_id):
    """Veterinário da clínica: sem permissão fiscal na matriz RBAC.

    O ``veterinario.id`` é obrigatório — os context processors do layout
    montam consultas com ele ao renderizar qualquer página.
    """
    return SimpleNamespace(
        id=10,
        is_authenticated=True,
        role=None,
        worker="veterinario",
        clinica_id=clinic_id,
        veterinario=SimpleNamespace(id=99, clinica_id=clinic_id, clinicas=[]),
        clinicas=[],
        clinic_roles=[],
    )


def _owner_user(clinic, clinic_id):
    return SimpleNamespace(
        id=11,
        is_authenticated=True,
        role=None,
        worker=None,
        clinica_id=clinic_id,
        veterinario=None,
        clinicas=[clinic],
        clinic_roles=[],
    )


@pytest.fixture
def clinic_id(app):
    with app.app_context():
        clinic = Clinica(nome="Clinica Fiscal")
        db.session.add(clinic)
        db.session.commit()
        return clinic.id


def test_fiscal_onboarding_denies_veterinarian_without_fiscal_permission(
    app, client, monkeypatch, clinic_id
):
    _login(monkeypatch, _vet_user(clinic_id))

    with app.test_request_context("/fiscal/onboarding/step/1"):
        with pytest.raises(Exception) as exc_info:
            fiscal_onboarding_step(1)

    assert getattr(exc_info.value, "code", None) == 403


def test_fiscal_xml_export_denies_veterinarian_without_fiscal_permission(
    app, client, monkeypatch, clinic_id
):
    _login(monkeypatch, _vet_user(clinic_id))

    with app.test_request_context("/fiscal/exports/xmls"):
        with pytest.raises(Exception) as exc_info:
            fiscal_exports_xmls()

    assert getattr(exc_info.value, "code", None) == 403


def test_fiscal_onboarding_still_allows_clinic_owner(app, client, monkeypatch, clinic_id):
    """O gate não pode trancar quem precisa emitir nota."""
    with app.app_context():
        clinic = db.session.get(Clinica, clinic_id)
        _login(monkeypatch, _owner_user(clinic, clinic_id))

        with app.test_request_context("/fiscal/onboarding/step/1"):
            response = fiscal_onboarding_step(1)

    assert "emissor" in response.lower()
