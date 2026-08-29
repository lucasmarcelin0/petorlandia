"""Application factory for PetOrlandia."""
import importlib

from flask import Flask

try:
    from .blueprint_utils import register_domain_blueprints
except ImportError:  # pragma: no cover - direct script/import mode
    from blueprint_utils import register_domain_blueprints


def _load_configured_app() -> Flask:
    """Return the real Flask instance regardless of import aliasing."""

    import importlib
    import sys

    for mod_name in ("petorlandia_app", "app"):
        mod = sys.modules.get(mod_name)
        if mod:
            cand = getattr(mod, "app", mod)
            if isinstance(cand, Flask) or type(cand).__name__ == "Flask":
                return cand

    module_name = f"{__package__}.app" if __package__ else "app"
    try:
        app_module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        app_module = importlib.import_module("app")

    candidate = getattr(app_module, "app", app_module)
    if isinstance(candidate, Flask) or type(candidate).__name__ == "Flask":
        return candidate

    nested = getattr(candidate, "app", None)
    if isinstance(nested, Flask) or type(nested).__name__ == "Flask":
        return nested

    import importlib.util
    import pathlib

    app_py = pathlib.Path(__file__).resolve().parent / "app.py"
    if app_py.exists():
        spec = importlib.util.spec_from_file_location("petorlandia_app", app_py)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules.setdefault("petorlandia_app", mod)
            spec.loader.exec_module(mod)
            cand = getattr(mod, "app", None)
            if isinstance(cand, Flask) or type(cand).__name__ == "Flask":
                return cand

    raise RuntimeError("Could not resolve Flask app instance")


def create_app(config_name=None):  # noqa: ARG001
    """Return the configured Flask app and register domain blueprints."""

    app = _load_configured_app()
    register_domain_blueprints(app)
    return app
