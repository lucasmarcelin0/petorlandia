"""Application factory for PetOrlândia."""
from blueprint_utils import register_domain_blueprints


def create_app(config_name=None):  # noqa: ARG001
    """Return the configured Flask app and register domain blueprints."""
    from app import app

    register_domain_blueprints(app)

    return app
