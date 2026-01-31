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
    return _view
