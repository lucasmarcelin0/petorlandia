"""Application factory for PetOrlandia."""
import importlib
import pathlib
import sys

from flask import Flask

try:
    from .blueprint_utils import register_domain_blueprints
except ImportError:  # pragma: no cover - direct script/import mode
    from blueprint_utils import register_domain_blueprints


def _load_configured_app() -> Flask:
    """Return the real Flask instance regardless of import aliasing."""

    for mod_name in ("petorlandia_app", "app"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "app") and isinstance(getattr(mod, "app"), Flask):
            return mod.app

    project_root = pathlib.Path(__file__).resolve().parent
    app_py_path = project_root / "app.py"
    if app_py_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("petorlandia_app", app_py_path)
        app_module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("petorlandia_app", app_module)
        sys.modules["app"] = app_module
        spec.loader.exec_module(app_module)
        if isinstance(getattr(app_module, "app", None), Flask):
            return app_module.app

    raise RuntimeError("Could not resolve Flask app instance")


def create_app(config_name=None):  # noqa: ARG001
    """Return the configured Flask app and register domain blueprints."""

    app = _load_configured_app()
    register_domain_blueprints(app)
    return app
