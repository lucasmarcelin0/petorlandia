"""A conta da equipe e o token de campo não autorizam fichas pessoais."""
import json
from pathlib import Path

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

from blueprints.sfa import bp


ROOT = Path(__file__).resolve().parents[1]


class SessionUser(UserMixin):
    def __init__(self, role):
        self.id = role
        self.role = role


@pytest.fixture()
def cadastro_app(tmp_path):
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config.update(TESTING=True, SECRET_KEY='test-only', LOGIN_DISABLED=True)
    login = LoginManager(app)
    login.user_loader(lambda role: SessionUser(role))
    app.jinja_env.globals['csrf_token'] = lambda: 'test-only'
    app.register_blueprint(bp)
    snapshot = {
        'collected_at': '2026-10-05T12:00:00-03:00',
        'collection_scope': 'Fixture privada de teste',
        'records': [{'property_code': '7', 'registration': '00.07', 'address': 'Rua Exemplo, 120',
                     'owner_name': 'Pessoa da amostra de teste', 'owner_code': '11', 'registry_number': ''}],
        'owners': [{'owner_code': '11', 'owner_name': 'Pessoa da amostra de teste', 'status': 'consultado',
                    'collected_at': '2026-10-05T12:00:00-03:00', 'source_url': '',
                    'fields': [{'label': 'CPF', 'value': '000.000.000-00'},
                               {'label': 'Telefone', 'value': '(00) 00000-0000'}]}],
    }
    path = tmp_path / 'private.json'
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    app.config['SFA_CADASTRO_PATH'] = str(path)
    return app


def authenticate(client, role):
    with client.session_transaction() as session:
        session['_user_id'] = role
        session['_fresh'] = True


@pytest.mark.parametrize('endpoint', ['/sfa/entomologia/cadastro/imoveis?q=Rua',
                                     '/sfa/entomologia/cadastro/imoveis/7'])
@pytest.mark.parametrize('role,status', [(None, 401), ('user', 403), ('Combate à dengue', 403), ('admin', 200)])
def test_real_admin_session_required(cadastro_app, monkeypatch, endpoint, role, status):
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '1')
    monkeypatch.setenv('SFA_ADMIN_TOKEN', 'field-token')
    client = cadastro_app.test_client()
    if role:
        authenticate(client, role)
    response = client.get(endpoint, headers={'X-SFA-Token': 'field-token'})
    assert response.status_code == status
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'Cookie' in response.headers['Vary']
    if status != 200:
        assert 'Pessoa da amostra' not in response.get_data(as_text=True)
        assert '000.000.000-00' not in response.get_data(as_text=True)


def test_search_has_no_documents_or_contacts_and_detail_is_private(cadastro_app):
    client = cadastro_app.test_client()
    authenticate(client, 'admin')
    search = client.get('/sfa/entomologia/cadastro/imoveis?q=Rua')
    assert len(search.json['results']) == 1
    assert '000.000.000-00' not in search.get_data(as_text=True)
    assert '(00) 00000-0000' not in search.get_data(as_text=True)
    detail = client.get('/sfa/entomologia/cadastro/imoveis/7')
    assert detail.json['owner']['fields'][0]['value'] == '000.000.000-00'
    with client.session_transaction() as session:
        session.clear()
    assert client.get('/sfa/entomologia/cadastro/imoveis/7').status_code == 401


def test_denied_requests_do_not_load_private_source(cadastro_app, monkeypatch):
    from services import entomologia_cadastro
    def fail(*_args, **_kwargs):
        pytest.fail('An unauthorized request tried to load private data')
    monkeypatch.setattr(entomologia_cadastro, 'search_cadastro', fail)
    monkeypatch.setattr(entomologia_cadastro, 'get_cadastro_property', fail)
    client = cadastro_app.test_client()
    assert client.get('/sfa/entomologia/cadastro/imoveis?q=Rua').status_code == 401
    assert client.get('/sfa/entomologia/cadastro/imoveis/7').status_code == 401


def test_missing_property_is_json_and_not_cached(cadastro_app):
    client = cadastro_app.test_client()
    authenticate(client, 'admin')
    response = client.get('/sfa/entomologia/cadastro/imoveis/unknown')
    assert response.status_code == 404
    assert response.is_json
    assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('role,enabled', [(None, False), ('user', False), ('admin', True)])
def test_page_only_embeds_admin_tools_for_real_admin(cadastro_app, monkeypatch, role, enabled):
    from blueprints import entomologia_routes
    monkeypatch.setattr(entomologia_routes, 'acoes_territoriais', lambda **_kwargs: [])
    monkeypatch.setattr(entomologia_routes, 'publicacao_vigente', lambda: None)
    monkeypatch.setattr(entomologia_routes, 'usuario_pode_alterar', lambda: False)
    client = cadastro_app.test_client()
    if role:
        authenticate(client, role)
    response = client.get('/sfa/entomologia')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert ('id="cadastre-panel"' in html) is enabled
    assert ('cadastre_search_url' in html) is enabled
    assert ('sfa_property_lookup.js' in html) is enabled
    assert 'Pessoa da amostra de teste' not in html
    assert '000.000.000-00' not in html
