from flask import Flask, Blueprint
import pytest
from blueprint_utils import _is_blueprint_registered, _register_with_alias, register_domain_blueprints


def test_is_blueprint_registered():
    app = Flask(__name__)
    bp = Blueprint('test_bp', __name__)

    assert not _is_blueprint_registered(app, bp)
    app.register_blueprint(bp)
    assert _is_blueprint_registered(app, bp)


def test_is_blueprint_registered_by_endpoint():
    app = Flask(__name__)
    bp = Blueprint('test_bp', __name__)

    @app.route('/hello')
    def test_bp_hello():
        return 'hello'

    app.view_functions['test_bp.hello'] = test_bp_hello
    assert _is_blueprint_registered(app, bp)


def test_register_with_alias():
    app = Flask(__name__)
    bp = Blueprint('test_bp', __name__)

    @bp.route('/hello')
    def hello():
        return 'hello'

    _register_with_alias(app, bp)

    assert 'test_bp.hello' in app.view_functions
    assert 'hello' in app.view_functions
    assert app.view_functions['test_bp.hello'] is app.view_functions['hello']


def test_register_with_alias_existing_view():
    app = Flask(__name__)
    bp = Blueprint('test_bp', __name__)

    @bp.route('/hello')
    def hello():
        return 'hello'

    app.add_url_rule('/existing', endpoint='hello', view_func=lambda: 'existing')
    _register_with_alias(app, bp)

    assert 'test_bp.hello' in app.view_functions
    assert 'hello' in app.view_functions
    assert app.view_functions['test_bp.hello'] is not app.view_functions['hello']


def test_register_with_alias_already_registered_rule():
    app = Flask(__name__)
    bp = Blueprint('test_bp', __name__)

    @bp.route('/hello')
    def hello():
        return 'hello'

    app.add_url_rule('/hello', endpoint='hello', view_func=hello)
    _register_with_alias(app, bp)


def test_register_domain_blueprints_registers_expected_blueprints():
    app = Flask(__name__)
    register_domain_blueprints(app)

    expected_blueprints = {
        'admin_routes', 'consulta_routes', 'site_routes', 'vacina_pmo_routes', 'pacientes_routes',
        'agendamentos_routes', 'api_routes', 'auth_routes', 'bulario_routes', 'casa_de_racao_routes',
        'clinica_routes', 'financeiro_routes', 'fiscal_routes', 'loja_routes', 'mensagens_routes',
        'oauth_routes', 'parceiro_routes', 'petsitter_routes', 'planos_routes', 'push_routes', 'sfa_routes', 'sim_portal'
    }

    assert expected_blueprints.issubset(set(app.blueprints.keys()))
    assert 'sim_portal' in app.blueprints
    register_domain_blueprints(app)
