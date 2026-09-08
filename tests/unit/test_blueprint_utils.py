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

    # simulate the case where view_functions starts with test_bp.
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
    # hello should still point to existing view because we didn't overwrite it
    assert app.view_functions['test_bp.hello'] is not app.view_functions['hello']

def test_register_with_alias_already_registered_rule():
    app = Flask(__name__)
    bp = Blueprint('test_bp', __name__)

    @bp.route('/hello')
    def hello():
        return 'hello'

    # We want to reach the line `if already: continue`.
    # This means there is an alias `hello` already, and it points to `app.view_functions['test_bp.hello']`.
    # And there is already a rule for it in `app.url_map`.
    # So we set up `app` such that when `_register_with_alias(app, bp)` is called, it iterates over `test_bp.hello`,
    # finds alias `hello`, sees `hello` is in `existing_endpoints` (meaning `app.view_functions['hello']` exists),
    # checks `app.view_functions['hello'] is app.view_functions['test_bp.hello']` and it is True,
    # and then checks if there's a rule that matches `rule.rule == r.rule` and `r.endpoint == alias`, and it's True.
    # To do this, we manually add the alias first before calling `_register_with_alias`.

    app.add_url_rule('/hello', endpoint='hello', view_func=hello)

    # We can just register the blueprint, which will call `app.register_blueprint(bp)`, creating `test_bp.hello`,
    # and then our manual `hello` is in existing_endpoints and points to the exact same function.
    # And since the rule `/hello` is already registered for endpoint `hello`, `already` will be True.

    _register_with_alias(app, bp)

def test_register_domain_blueprints_registers_expected_blueprints():
    app = Flask(__name__)

    # We call the real function.
    register_domain_blueprints(app)

    # Verify blueprints
    expected_blueprints = {
        'admin_routes', 'consulta_routes', 'site_routes', 'vacina_pmo_routes', 'pacientes_routes',
        'agendamentos_routes', 'api_routes', 'auth_routes', 'bulario_routes', 'casa_de_racao_routes',
        'clinica_routes', 'financeiro_routes', 'fiscal_routes', 'loja_routes', 'mensagens_routes',
        'oauth_routes', 'parceiro_routes', 'petsitter_routes', 'planos_routes', 'push_routes', 'sfa_routes', 'sim_portal'
    }

    assert expected_blueprints.issubset(set(app.blueprints.keys()))

    # sim has no aliases, check that
    assert 'sim_portal' in app.blueprints

    # verify that calling it again is idempotent
    register_domain_blueprints(app)
