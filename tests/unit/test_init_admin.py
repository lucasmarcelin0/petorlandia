import pytest
from flask import Flask
from admin import init_admin
from extensions import db


def test_init_admin_registers_views():
    """Test that init_admin registers the correct views on a Flask app."""
    # Create a minimal Flask app for testing the isolated function
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions required by admin views
    db.init_app(app)

    with app.app_context():
        # Call the target function directly
        init_admin(app)

        # Check if admin extension was registered by init_admin
        admin_ext = app.extensions.get('admin')
        assert admin_ext is not None, "Admin extension should be registered on the app"

        admin_instance = admin_ext[0]

        registered_endpoints = {view.endpoint for view in admin_instance._views}

        expected_endpoints = {
            'painel_admin', 'animal', 'species', 'breed', 'user', 'message',
            'transaction', 'medicamento', 'prescricao', 'clinica',
            'contabilidadeconfigview', 'clinichours', 'vetschedule',
            'veterinariansettingsview', 'veterinarianmembership', 'waitlistlead',
            'veterinario', 'clinicstaff', 'specialty', 'examemodelo',
            'protocoloclinico', 'protocoloclinicoexame', 'protocoloclinicomedicamento',
            'protocoloclinicoretorno', 'auditoriasugestaoclinica', 'consulta',
            'vacinamodelo', 'apresentacaomedicamento', 'tiporacao', 'product',
            'productcategory', 'casaderacao', 'casaderacaohorario',
            'storepaymentaccount', 'healthplan', 'healthsubscription', 'order',
            'orderitem', 'deliveryrequest', 'pickuplocation'
        }

        missing_endpoints = expected_endpoints - registered_endpoints
        assert not missing_endpoints, f"Missing expected admin views: {missing_endpoints}"
