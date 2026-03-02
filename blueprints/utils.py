"""Utilities for blueprint registration."""
from __future__ import annotations

import importlib
from typing import Any, Callable


def _load_app_module():
    try:
        return importlib.import_module("petorlandia_app")
    except ModuleNotFoundError:
        return importlib.import_module("app")


def lazy_view(view_name: str) -> Callable[..., Any]:
    def _view(*args: Any, **kwargs: Any):
        app_module = _load_app_module()
        view_func = getattr(app_module, view_name)
        return view_func(*args, **kwargs)

    _view.__name__ = view_name
    _view.__qualname__ = view_name
    _view.__doc__ = f"Proxy for app.{view_name}"

    # Flask-WTF identifies exempt views by "module.qualname".
    # The wrapper _view lives in "blueprints.utils", so it never matches the
    # entry that @csrf.exempt added for the real function (e.g. "app.mcp_server").
    # Fix: copy __module__ from the actual function so the check resolves to
    # the same "module.qualname" key that was registered by @csrf.exempt.
    try:
        app_module = _load_app_module()
        actual_func = getattr(app_module, view_name, None)
        if actual_func is not None:
            _view.__module__ = actual_func.__module__  # critical for csrf exempt lookup
            if getattr(actual_func, "csrf_exempt", False):
                _view.csrf_exempt = True  # type: ignore[attr-defined]
    except Exception:
        pass

    return _view
