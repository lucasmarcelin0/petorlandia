"""Package wrapper to expose the Flask app module."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_module_path = pathlib.Path(__file__).resolve().parent.parent / "app.py"
_spec = importlib.util.spec_from_file_location("petorlandia_app", _module_path)
_app_module = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("petorlandia_app", _app_module)
_spec.loader.exec_module(_app_module)

globals().update(_app_module.__dict__)
