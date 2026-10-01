import pytest
from unittest.mock import patch, MagicMock
from flask import url_for
from models import Consulta, Animal, User


def test_criar_prescricao_open_redirect_prevention(app, client):
    """Test that criar_prescricao sanitizes referrer headers and prevents open redirects or errors when referrer is missing."""
    with app.test_request_context():
        # Create mock objects
        mock_animal = MagicMock(spec=Animal)
        mock_animal.id = 123
        mock_animal.clinica_id = 1

        mock_consulta = MagicMock(spec=Consulta)
        mock_consulta.id = 456
        mock_consulta.animal_id = 123
        mock_consulta.clinica_id = 1
        mock_consulta.animal = mock_animal

        mock_user = MagicMock(spec=User)
        mock_user.id = 789
        mock_user.is_authenticated = True

    with patch("blueprints.consulta.get_consulta_or_404", return_value=mock_consulta), \
         patch("blueprints.consulta.is_veterinarian", return_value=True), \
         patch("flask_login.utils._get_user", return_value=mock_user), \
         patch("blueprints.consulta.current_user", mock_user):

        # Test case 1: Missing medicamento with malicious external Referer header
        response = client.post(
            f"/consulta/{mock_consulta.id}/prescricao",
            data={"medicamento": ""},
            headers={"Referer": "https://attacker.com/evil"},
        )
        assert response.status_code == 302
        assert response.location != "https://attacker.com/evil"
        assert response.location.startswith("/") or response.location.startswith("http://localhost/")

        # Test case 2: Missing medicamento with NO Referer header (must not raise ValueError / 500)
        response = client.post(
            f"/consulta/{mock_consulta.id}/prescricao",
            data={"medicamento": ""},
        )
        assert response.status_code == 302
        assert response.location is not None
        assert not response.location.startswith("https://attacker.com")


def test_criar_prescricao_non_vet_open_redirect_prevention(app, client):
    """Test that non-veterinarian check in criar_prescricao sanitizes Referer."""
    with app.test_request_context():
        mock_consulta = MagicMock(spec=Consulta)
        mock_consulta.id = 456
        mock_consulta.animal_id = 123

        mock_user = MagicMock(spec=User)
        mock_user.id = 789
        mock_user.is_authenticated = True

    with patch("blueprints.consulta.get_consulta_or_404", return_value=mock_consulta), \
         patch("blueprints.consulta.is_veterinarian", return_value=False), \
         patch("flask_login.utils._get_user", return_value=mock_user), \
         patch("blueprints.consulta.current_user", mock_user):

        response = client.post(
            f"/consulta/{mock_consulta.id}/prescricao",
            data={"medicamento": "Amoxicilina"},
            headers={"Referer": "https://attacker.com/phishing"},
        )
        assert response.status_code == 302
        assert response.location != "https://attacker.com/phishing"
        assert response.location.startswith("/") or response.location.startswith("http://localhost/")
