import os
import re
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.theme_service import (
    WORKSPACE_THEMES,
    get_all_workspace_themes,
    get_current_page_theme,
)
from app import app as flask_app


HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def test_workspace_themes_integrity():
    required_keys = {
        "admin",
        "professional",
        "clinic",
        "store",
        "delivery",
        "partner",
        "vaccinator",
        "accounting",
        "student",
    }
    assert required_keys.issubset(set(WORKSPACE_THEMES.keys()))

    for key, conf in WORKSPACE_THEMES.items():
        assert "label" in conf, f"Missing label in {key}"
        assert "emoji" in conf, f"Missing emoji in {key}"
        assert "icon" in conf, f"Missing icon in {key}"
        for col_prop in ("area", "tone2", "tone3", "tone4", "ink", "tint", "edge"):
            color = conf.get(col_prop)
            assert color is not None, f"Missing {col_prop} in {key}"
            assert HEX_COLOR_PATTERN.match(color), f"Invalid hex color {color} for {key}.{col_prop}"


def test_get_all_workspace_themes():
    all_themes = get_all_workspace_themes()
    assert isinstance(all_themes, dict)
    assert "vaccinator" in all_themes
    assert all_themes["vaccinator"]["area"] == "#194897"


def test_get_current_page_theme_by_path():
    with flask_app.test_request_context("/vacina-pmo"):
        theme = get_current_page_theme()
        assert theme is not None
        assert theme.key == "vaccinator"
        assert theme.emoji == "💉"
        assert theme.area == "#194897"

    with flask_app.test_request_context("/contabilidade"):
        theme = get_current_page_theme()
        assert theme is not None
        assert theme.key == "accounting"
        assert theme.emoji == "📊"

    with flask_app.test_request_context("/casa-de-racao/produtos"):
        theme = get_current_page_theme()
        assert theme is not None
        assert theme.key == "store"
        assert theme.emoji == "🏪"


def test_get_current_page_theme_by_blueprint(monkeypatch):
    with flask_app.test_request_context("/qualquer-rota"):
        from flask import request
        monkeypatch.setattr(type(request._get_current_object()), "blueprint", "vacina_pmo")
        theme = get_current_page_theme()
        assert theme is not None
        assert theme.key == "vaccinator"


def test_get_current_page_theme_by_endpoint(monkeypatch):
    with flask_app.test_request_context("/qualquer-rota"):
        from flask import request
        monkeypatch.setattr(type(request._get_current_object()), "endpoint", "painel_admin.index")
        theme = get_current_page_theme()
        assert theme is not None
        assert theme.key == "admin"


def test_get_current_page_theme_neutral_on_public_routes():
    with flask_app.test_request_context("/"):
        theme = get_current_page_theme()
        assert theme is None

    with flask_app.test_request_context("/termos"):
        theme = get_current_page_theme()
        assert theme is None


def test_get_current_page_theme_explicit_override():
    from flask import g

    with flask_app.test_request_context("/qualquer-lugar"):
        g.page_theme = "partner"
        theme = get_current_page_theme()
        assert theme is not None
        assert theme.key == "partner"
        assert theme.emoji == "🤝"


def test_context_processor_injection():
    from context_processors import inject_page_theme

    with flask_app.test_request_context("/vacina-pmo"):
        ctx = inject_page_theme()
        assert "current_page_theme" in ctx
        assert "all_workspace_themes" in ctx
        assert ctx["current_page_theme"] is not None
        assert ctx["current_page_theme"].key == "vaccinator"
        assert "vaccinator" in ctx["all_workspace_themes"]


def test_layout_renders_theme_context_badge_and_data_attribute():
    with flask_app.test_client() as client:
        # A rota /vacina-pmo renderiza o layout com o tema vacinador
        resp = client.get("/vacina-pmo")
        # Mesmo se redirecionar para login (302), checamos renderização com app_context e render_template_string
        from flask import render_template_string
        with flask_app.test_request_context("/vacina-pmo"):
            html = render_template_string(
                '{% extends "layout.html" %}{% block main %}<p>Teste Vacina</p>{% endblock %}'
            )
            assert 'data-page-theme="vaccinator"' in html
            assert "--theme-area: #194897" in html
            assert "theme-context-badge" in html
            assert "💉" in html
            assert "Área do Vacinador" in html
            assert "theme-accent-bar" in html
