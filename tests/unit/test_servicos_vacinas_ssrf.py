"""Unit test for SSRF validation in servicos_vacinas_cidade_por_local."""

from unittest.mock import patch, MagicMock
from models import User
from flask_login import login_user


def test_servicos_vacinas_cidade_por_local_ssrf_blocked(app, client):
    """Test that servicos_vacinas_cidade_por_local blocks request when SSRF check fails."""
    with app.test_request_context():
        user = User(email="test@example.com", name="Test User", role="user")
        user.id = 100
        with client.session_transaction() as sess:
            sess['_user_id'] = '100'

        with patch('blueprints.site.is_url_ssrf_safe', return_value=False), \
             patch('flask_login.utils._get_user', return_value=user):
            response = client.get('/servicos/vacinas/cidade-por-local?lat=-20.7186&lng=-47.8824')
            assert response.status_code == 502
            data = response.get_json()
            assert data['success'] is False
            assert 'indisponível' in data['message']


def test_servicos_vacinas_cidade_por_local_ssrf_allowed(app, client):
    """Test that servicos_vacinas_cidade_por_local proceeds when SSRF check passes."""
    with app.test_request_context():
        user = User(email="test@example.com", name="Test User", role="user")
        user.id = 100
        with client.session_transaction() as sess:
            sess['_user_id'] = '100'

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'address': {
                'city': 'Orlândia'
            }
        }
        mock_resp.raise_for_status.return_value = None

        with patch('blueprints.site.is_url_ssrf_safe', return_value=True), \
             patch('blueprints.site.requests.get', return_value=mock_resp), \
             patch('flask_login.utils._get_user', return_value=user):
            response = client.get('/servicos/vacinas/cidade-por-local?lat=-20.7186&lng=-47.8824')
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True
            assert data['cidade_detectada'] == 'Orlândia'
