import pytest
from datetime import timedelta
from unittest.mock import patch
from helpers import get_appointment_duration


@patch('helpers.get_appointment_duration_minutes')
def test_get_appointment_duration(mock_get_minutes):
    mock_get_minutes.return_value = 45

    result = get_appointment_duration('consulta')

    mock_get_minutes.assert_called_once_with('consulta')
    assert result == timedelta(minutes=45)

    mock_get_minutes.reset_mock()

    mock_get_minutes.return_value = 30
    result = get_appointment_duration(None)
    mock_get_minutes.assert_called_once_with(None)
    assert result == timedelta(minutes=30)
