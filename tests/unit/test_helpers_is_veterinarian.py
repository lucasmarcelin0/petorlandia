import pytest
from unittest.mock import MagicMock, patch

from helpers import is_veterinarian


@patch("helpers.has_veterinarian_profile")
@patch("helpers.ensure_veterinarian_membership")
def test_is_veterinarian_with_explicit_user(mock_ensure_membership, mock_has_profile):
    mock_user = MagicMock()

    # Case 1: User does not have a veterinarian profile
    mock_has_profile.return_value = False
    assert is_veterinarian(mock_user) is False
    mock_has_profile.assert_called_with(mock_user)

    # Case 2: User has profile, require_membership is False
    mock_has_profile.return_value = True
    assert is_veterinarian(mock_user, require_membership=False) is True

    # Case 3: User has profile, require_membership is True, but no membership
    mock_ensure_membership.return_value = None
    assert is_veterinarian(mock_user, require_membership=True) is False
    mock_ensure_membership.assert_called_with(mock_user.veterinario)

    # Case 4: User has profile, require_membership is True, membership is not active
    mock_membership = MagicMock()
    mock_membership.is_active.return_value = False
    mock_ensure_membership.return_value = mock_membership
    assert is_veterinarian(mock_user, require_membership=True) is False
    mock_membership.is_active.assert_called_once()

    # Case 5: User has profile, require_membership is True, membership is active
    mock_membership.is_active.return_value = True
    assert is_veterinarian(mock_user, require_membership=True) is True


@patch("helpers.has_veterinarian_profile")
@patch("helpers.ensure_veterinarian_membership")
@patch("helpers.current_user")
def test_is_veterinarian_with_current_user(mock_current_user, mock_ensure_membership, mock_has_profile):
    # Case 1: current_user is not authenticated
    mock_current_user.is_authenticated = False
    mock_has_profile.return_value = False # None doesn't have profile

    assert is_veterinarian() is False
    mock_has_profile.assert_called_with(None)

    # Case 2: current_user is authenticated
    mock_current_user.is_authenticated = True
    mock_has_profile.return_value = True

    mock_membership = MagicMock()
    mock_membership.is_active.return_value = True
    mock_ensure_membership.return_value = mock_membership

    assert is_veterinarian() is True
    mock_has_profile.assert_called_with(mock_current_user)
    mock_ensure_membership.assert_called_with(mock_current_user.veterinario)
