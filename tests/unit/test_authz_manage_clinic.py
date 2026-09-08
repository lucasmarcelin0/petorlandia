import pytest
from authz import can_manage_clinic

class MockUser:
    def __init__(self, role=None, worker=None, clinicas=None, clinic_roles=None, veterinario=None, admin=False, clinica_id=None):
        self.role = 'admin' if admin else role
        self.worker = worker
        self.clinicas = clinicas or []
        self.clinic_roles = clinic_roles or []
        self.veterinario = veterinario
        self.clinica_id = clinica_id

class MockClinic:
    def __init__(self, id):
        self.id = id

class MockClinicRole:
    def __init__(self, clinic_id, internship_active=False):
        self.clinic_id = clinic_id
        self.internship_active = internship_active

class MockVet:
    def __init__(self, clinica_id=None, clinicas=None):
        self.clinica_id = clinica_id
        self.clinicas = clinicas or []

def test_can_manage_clinic_admin(app):
    with app.app_context():
        admin = MockUser(admin=True)
        assert can_manage_clinic(admin, 1) is True

def test_can_manage_clinic_owner_manage(app):
    with app.app_context():
        clinic = MockClinic(1)
        owner = MockUser(clinicas=[clinic])
        assert can_manage_clinic(owner, 1) is True

def test_can_manage_clinic_owner_different_clinic(app):
    with app.app_context():
        clinic = MockClinic(2)
        owner = MockUser(clinicas=[clinic])
        assert can_manage_clinic(owner, 1) is False

def test_can_manage_clinic_staff_cannot_manage(app):
    with app.app_context():
        staff = MockUser(worker="staff", clinic_roles=[MockClinicRole(1)], clinica_id=1)
        assert can_manage_clinic(staff, 1) is False

def test_can_manage_clinic_intern_cannot_manage(app):
    with app.app_context():
        intern = MockUser(clinic_roles=[MockClinicRole(1, internship_active=True)])
        assert can_manage_clinic(intern, 1) is False

def test_can_manage_clinic_vet_cannot_manage(app):
    with app.app_context():
        vet = MockUser(worker="veterinario", veterinario=MockVet(clinica_id=1))
        assert can_manage_clinic(vet, 1) is False

def test_can_manage_clinic_tutor_cannot_manage(app):
    with app.app_context():
        tutor = MockUser()
        assert can_manage_clinic(tutor, 1) is False

def test_can_manage_clinic_no_clinic(app):
    with app.app_context():
        admin = MockUser(admin=True)
        assert can_manage_clinic(admin, None) is False
