"""Utilities for blueprint registration."""
from __future__ import annotations

import importlib


def _load_app_module():
    """Resolve o módulo app em tempo de request (late-binding).

    Usado por views que precisam respeitar monkeypatch de testes em nomes
    do módulo app. O antigo ``lazy_view`` (proxy de views inteiras) foi
    aposentado quando todas as views migraram para os blueprints.
    """
    try:
        return importlib.import_module("petorlandia_app")
    except ModuleNotFoundError:
        return importlib.import_module("app")
