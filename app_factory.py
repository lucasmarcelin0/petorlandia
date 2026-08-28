"""Application factory for PetOrlandia."""
import importlib

from flask import Flask

try:
    from .blueprint_utils import register_domain_blueprints
except ImportError:  # pragma: no cover - direct script/import mode
    from blueprint_utils import register_domain_blueprints


def _load_configured_app() -> Flask:
    """Return the real Flask instance regardless of import aliasing."""

    modules_to_try = [
        f"{__package__}.app" if __package__ else None,
        "app.app",
        "app",
        "petorlandia_app",
    ]

    for module_name in modules_to_try:
        if not module_name:
            continue
        try:
            app_module = importlib.import_module(module_name)
        except (ModuleNotFoundError, ImportError):
            continue

        candidate = getattr(app_module, "app", app_module)
        if isinstance(candidate, Flask) or getattr(getattr(candidate, "__class__", None), "__name__", None) == "Flask":
            return candidate

        nested = getattr(candidate, "app", None)
        if isinstance(nested, Flask) or getattr(getattr(nested, "__class__", None), "__name__", None) == "Flask":
            return nested

    raise RuntimeError("Could not resolve Flask app instance")


def create_app(config_name=None):  # noqa: ARG001
    """Return the configured Flask app and register domain blueprints."""

    app = _load_configured_app()
    register_domain_blueprints(app)
    return app
