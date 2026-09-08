import pytest
from datetime import timedelta
from unittest.mock import patch
from helpers import get_appointment_duration

@patch('helpers.get_appointment_duration_minutes')
def test_get_appointment_duration(mock_get_minutes):
    """Test get_appointment_duration delegates correctly to get_appointment_duration_minutes."""
    # Setup mock to return a predictable value
    mock_get_minutes.return_value = 45

    # Test valid kind
    result = get_appointment_duration('consulta')

    # Verify mock was called with correct argument
    mock_get_minutes.assert_called_once_with('consulta')

    # Verify result is correct timedelta based on mock return value
    assert result == timedelta(minutes=45)

    # Reset mock for another test
    mock_get_minutes.reset_mock()

    # Test None kind
    mock_get_minutes.return_value = 30
    result = get_appointment_duration(None)
    mock_get_minutes.assert_called_once_with(None)
    assert result == timedelta(minutes=30)
