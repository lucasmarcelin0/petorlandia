import pytest
from unittest.mock import Mock

from authz import can_view_clinic, can_manage_clinic

@pytest.fixture
def admin_user():
    return Mock(
        role="admin",
        worker=None,
        veterinario=None,
        clinicas=None,
        clinica_id=None,
        clinic_roles=None,
    )

@pytest.fixture
def owner_user():
    clinic = Mock(id=1)
    return Mock(
        role=None,
        worker=None,
        veterinario=None,
        clinicas=[clinic],
        clinica_id=None,
        clinic_roles=None,
    )

@pytest.fixture
def staff_user():
    return Mock(
        role=None,
        worker="staff",
        veterinario=None,
        clinicas=None,
        clinica_id=1,
        clinic_roles=None,
    )

@pytest.fixture
def vet_user():
    vet = Mock(clinica_id=1, clinicas=[])
    return Mock(
        role=None,
        worker="veterinario",
        veterinario=vet,
        clinicas=None,
        clinica_id=None,
        clinic_roles=None,
    )

@pytest.fixture
def intern_user():
    role = Mock(internship_active=True, clinic_id=1)
    return Mock(
        role=None,
        worker=None,
        veterinario=None,
        clinicas=None,
        clinica_id=None,
        clinic_roles=[role],
    )

@pytest.fixture
def tutor_user():
    return Mock(
        role=None,
        worker=None,
        veterinario=None,
        clinicas=None,
        clinica_id=None,
        clinic_roles=None,
    )


class TestCanViewClinic:
    def test_none_inputs(self, admin_user):
        assert not can_view_clinic(None, 1)
        assert not can_view_clinic(admin_user, None)
        assert not can_view_clinic(None, None)

    def test_admin_can_view_any_clinic(self, admin_user):
        assert can_view_clinic(admin_user, 1)
        assert can_view_clinic(admin_user, 999)

    def test_owner_can_view_own_clinic(self, owner_user):
        assert can_view_clinic(owner_user, 1)

    def test_owner_cannot_view_other_clinic(self, owner_user):
        assert not can_view_clinic(owner_user, 2)

    def test_staff_can_view_own_clinic(self, staff_user):
        assert can_view_clinic(staff_user, 1)

    def test_staff_cannot_view_other_clinic(self, staff_user):
        assert not can_view_clinic(staff_user, 2)

    def test_vet_can_view_own_clinic(self, vet_user):
        assert can_view_clinic(vet_user, 1)

    def test_vet_cannot_view_other_clinic(self, vet_user):
        assert not can_view_clinic(vet_user, 2)

    def test_intern_can_view_own_clinic(self, intern_user):
        assert can_view_clinic(intern_user, 1)

    def test_intern_cannot_view_other_clinic(self, intern_user):
        assert not can_view_clinic(intern_user, 2)

    def test_tutor_cannot_view_any_clinic(self, tutor_user):
        assert not can_view_clinic(tutor_user, 1)


class TestCanManageClinic:
    def test_none_inputs(self, admin_user):
        assert not can_manage_clinic(None, 1)
        assert not can_manage_clinic(admin_user, None)
        assert not can_manage_clinic(None, None)

    def test_admin_can_manage_any_clinic(self, admin_user):
        assert can_manage_clinic(admin_user, 1)
        assert can_manage_clinic(admin_user, 999)

    def test_owner_can_manage_own_clinic(self, owner_user):
        assert can_manage_clinic(owner_user, 1)

    def test_owner_cannot_manage_other_clinic(self, owner_user):
        assert not can_manage_clinic(owner_user, 2)

    def test_staff_cannot_manage_own_clinic(self, staff_user):
        assert not can_manage_clinic(staff_user, 1)

    def test_vet_cannot_manage_own_clinic(self, vet_user):
        assert not can_manage_clinic(vet_user, 1)

    def test_intern_cannot_manage_own_clinic(self, intern_user):
        assert not can_manage_clinic(intern_user, 1)

    def test_tutor_cannot_manage_any_clinic(self, tutor_user):
        assert not can_manage_clinic(tutor_user, 1)
