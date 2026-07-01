"""Application factory for PetOrlandia."""
import importlib

from flask import Flask

try:
    from .blueprint_utils import register_domain_blueprints
except ImportError:  # pragma: no cover - direct script/import mode
    from blueprint_utils import register_domain_blueprints


def _load_configured_app() -> Flask:
    """Return the real Flask instance regardless of import aliasing."""

    module_name = f"{__package__}.app" if __package__ else "app"
    try:
        app_module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        app_module = importlib.import_module("app")

    candidate = getattr(app_module, "app", app_module)
    if isinstance(candidate, Flask):
        return candidate

    nested = getattr(candidate, "app", None)
    if isinstance(nested, Flask):
        return nested

    raise RuntimeError("Could not resolve Flask app instance")


def create_app(config_name=None):  # noqa: ARG001
    """Return the configured Flask app and register domain blueprints."""

    app = _load_configured_app()
    register_domain_blueprints(app)
    return app
