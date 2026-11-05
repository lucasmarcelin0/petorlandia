import pytest
from unittest.mock import patch
from types import SimpleNamespace
from authz import can_view_budget, can_manage_budget

def test_can_view_budget_delegates_to_can_clinic_resource():
    user = SimpleNamespace(id=1, role='admin', worker=None, clinicas=[], clinic_roles=[])
    clinic_id = 42

    with patch('authz._can_clinic_resource') as mock_can_clinic_resource:
        mock_can_clinic_resource.return_value = True

        result = can_view_budget(user, clinic_id)

        assert result is True
        mock_can_clinic_resource.assert_called_once_with(user, clinic_id, "budget", "view")

def test_can_view_budget_with_consultation_id_ignores_it():
    user = SimpleNamespace(id=1, role='admin', worker=None, clinicas=[], clinic_roles=[])
    clinic_id = 42
    consultation_id = 99

    with patch('authz._can_clinic_resource') as mock_can_clinic_resource:
        mock_can_clinic_resource.return_value = True

        result = can_view_budget(user, clinic_id, consultation_id=consultation_id)

        assert result is True
        mock_can_clinic_resource.assert_called_once_with(user, clinic_id, "budget", "view")

def test_can_manage_budget_delegates_to_can_clinic_resource():
    user = SimpleNamespace(id=1, role='admin', worker=None, clinicas=[], clinic_roles=[])
    clinic_id = 42

    with patch('authz._can_clinic_resource') as mock_can_clinic_resource:
        mock_can_clinic_resource.return_value = True

        result = can_manage_budget(user, clinic_id)

        assert result is True
        mock_can_clinic_resource.assert_called_once_with(user, clinic_id, "budget", "manage")

def test_can_manage_budget_with_consultation_id_ignores_it():
    user = SimpleNamespace(id=1, role='admin', worker=None, clinicas=[], clinic_roles=[])
    clinic_id = 42
    consultation_id = 99

    with patch('authz._can_clinic_resource') as mock_can_clinic_resource:
        mock_can_clinic_resource.return_value = True

        result = can_manage_budget(user, clinic_id, consultation_id=consultation_id)

        assert result is True
        mock_can_clinic_resource.assert_called_once_with(user, clinic_id, "budget", "manage")
