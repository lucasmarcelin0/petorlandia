"""Single source of truth para paletas de cores e identidade visual por área de trabalho.

Centraliza todas as definições visuais das áreas (Admin, Profissional, Clínica,
Loja, Entregas, Parceiro, Vacinador, Contabilidade, Estudante, etc.).

Ao alterar qualquer cor, rótulo ou emoji neste arquivo:
- Os cartões/ícones da página inicial (home) são atualizados automaticamente.
- As páginas internas de cada módulo herdam instantaneamente a mesma paleta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import g, has_request_context, request


@dataclass(frozen=True)
class AreaTheme:
    key: str
    label: str
    emoji: str
    icon: str
    area: str
    tone2: str
    tone3: str
    tone4: str
    ink: str
    tint: str
    edge: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "emoji": self.emoji,
            "icon": self.icon,
            "area": self.area,
            "tone2": self.tone2,
            "tone3": self.tone3,
            "tone4": self.tone4,
            "ink": self.ink,
            "tint": self.tint,
            "edge": self.edge,
        }


# Paleta central e metadados de cada área
WORKSPACE_THEMES: dict[str, dict[str, Any]] = {
    "admin": {
        "label": "Administração",
        "emoji": "🧭",
        "icon": "fa-chart-line",
        "area": "#1e3359",
        "tone2": "#34558a",
        "tone3": "#9bb8e3",
        "tone4": "#d1dff4",
        "ink": "#142c4b",
        "tint": "#f5f7fc",
        "edge": "#d5deed",
        "blueprints": {"admin", "admin_routes", "painel_admin"},
        "endpoints": {
            "painel_admin",
            "painel_admin.index",
            "admin_notifications",
            "admin_routes.product_analytics_dashboard",
            "admin_home_editor",
            "admin_financeiro",
            "admin_users",
            "admin_logs",
        },
        "prefixes": ("/admin", "/painel-admin", "/admin-home-editor"),
    },
    "professional": {
        "label": "Área profissional",
        "emoji": "🩺",
        "icon": "fa-stethoscope",
        "area": "#075354",
        "tone2": "#087d7d",
        "tone3": "#83cec9",
        "tone4": "#c8eae5",
        "ink": "#123d3a",
        "tint": "#f2faf9",
        "edge": "#c8e4e1",
        "blueprints": {"clinica", "pacientes", "consulta"},
        "endpoints": {
            "appointments",
            "novo_animal",
            "tutores",
            "minha_clinica",
            "prontuario",
            "prescricao",
            "internacao",
            "exames",
            "receitas",
            "atendimento",
            "historico_clinico",
        },
        "prefixes": (
            "/agendamentos",
            "/novo-animal",
            "/tutores",
            "/minha-clinica",
            "/prontuario",
            "/prescricao",
            "/internacao",
            "/pacientes",
            "/consultas",
        ),
    },
    "clinic": {
        "label": "Minha clínica",
        "emoji": "🏥",
        "icon": "fa-hospital",
        "area": "#075354",
        "tone2": "#087d7d",
        "tone3": "#83cec9",
        "tone4": "#c8eae5",
        "ink": "#123d3a",
        "tint": "#f2faf9",
        "edge": "#c8e4e1",
        "blueprints": {"clinica"},
        "endpoints": {"minha_clinica"},
        "prefixes": ("/minha-clinica",),
    },
    "store": {
        "label": "Minha loja",
        "emoji": "🏪",
        "icon": "fa-store",
        "area": "#843808",
        "tone2": "#b7571c",
        "tone3": "#edb57f",
        "tone4": "#f9ddbc",
        "ink": "#4b280f",
        "tint": "#fff8f2",
        "edge": "#efd9c7",
        "blueprints": {"casa_de_racao", "sfa"},
        "endpoints": {
            "casa_de_racao_dashboard",
            "casa_de_racao_produtos",
            "casa_de_racao_vendas",
            "casa_de_racao_entregas",
        },
        "prefixes": ("/casa-de-racao", "/sfa"),
    },
    "delivery": {
        "label": "Área de Entregas",
        "emoji": "🚚",
        "icon": "fa-truck",
        "area": "#843808",
        "tone2": "#b7571c",
        "tone3": "#edb57f",
        "tone4": "#f9ddbc",
        "ink": "#4b280f",
        "tint": "#fff8f2",
        "edge": "#efd9c7",
        "blueprints": set(),
        "endpoints": {
            "list_delivery_requests",
            "delivery_detail",
            "minhas_entregas",
        },
        "prefixes": ("/entregas", "/delivery"),
    },
    "partner": {
        "label": "Área do Parceiro",
        "emoji": "🤝",
        "icon": "fa-handshake",
        "area": "#50247e",
        "tone2": "#8654b5",
        "tone3": "#c5a6e3",
        "tone4": "#e5d5f3",
        "ink": "#3e2059",
        "tint": "#f9f5fd",
        "edge": "#e4d6f2",
        "blueprints": {"parceiro"},
        "endpoints": {
            "parceiro_dashboard",
            "parceiro_novo_estabelecimento",
        },
        "prefixes": ("/parceiro",),
    },
    "vaccinator": {
        "label": "Área do Vacinador",
        "emoji": "💉",
        "icon": "fa-syringe",
        "area": "#194897",
        "tone2": "#3568bd",
        "tone3": "#9cbeef",
        "tone4": "#d5e4fa",
        "ink": "#17345f",
        "tint": "#f3f7ff",
        "edge": "#d2dff8",
        "blueprints": {"vacina_pmo"},
        "endpoints": {
            "vacina_pmo",
            "vacina_pmo.painel",
            "vacina_pmo.dashboard",
            "vacina_pmo_app",
            "vacina_pmo_routes",
        },
        "prefixes": ("/vacina-pmo",),
    },
    "membership": {
        "label": "Acesso profissional",
        "emoji": "🪪",
        "icon": "fa-id-card",
        "area": "#194897",
        "tone2": "#3568bd",
        "tone3": "#9cbeef",
        "tone4": "#d5e4fa",
        "ink": "#17345f",
        "tint": "#f3f7ff",
        "edge": "#d2dff8",
        "blueprints": set(),
        "endpoints": {"veterinarian_membership"},
        "prefixes": ("/assinatura-veterinario", "/membership"),
    },
    "accounting": {
        "label": "Contabilidade",
        "emoji": "📊",
        "icon": "fa-chart-line",
        "area": "#155438",
        "tone2": "#287d50",
        "tone3": "#8bce9e",
        "tone4": "#d2edd8",
        "ink": "#173e2a",
        "tint": "#f3faf5",
        "edge": "#cfe5d6",
        "blueprints": {"financeiro", "fiscal"},
        "endpoints": {
            "contabilidade_financeiro",
            "contabilidade_pagamentos",
            "contabilidade_obrigacoes",
            "contabilidade_nfse",
        },
        "prefixes": ("/contabilidade",),
    },
    "student": {
        "label": "Estudar",
        "emoji": "🎓",
        "icon": "fa-graduation-cap",
        "area": "#4d2c65",
        "tone2": "#82508c",
        "tone3": "#c8a3d0",
        "tone4": "#ead7ed",
        "ink": "#422647",
        "tint": "#faf6fc",
        "edge": "#e7d7ed",
        "blueprints": set(),
        "endpoints": {
            "student_hub",
            "student_practice",
        },
        "prefixes": ("/estudante",),
    },
    "internship": {
        "label": "Estágio supervisionado",
        "emoji": "📚",
        "icon": "fa-user-graduate",
        "area": "#4d2c65",
        "tone2": "#82508c",
        "tone3": "#c8a3d0",
        "tone4": "#ead7ed",
        "ink": "#422647",
        "tint": "#faf6fc",
        "edge": "#e7d7ed",
        "blueprints": set(),
        "endpoints": {
            "student_internship_clinic",
        },
        "prefixes": ("/estagio",),
    },
    "personal-shortcuts": {
        "label": "Minha vida pet",
        "emoji": "🐾",
        "icon": "fa-paw",
        "area": "#243b64",
        "tone2": "#3c5a92",
        "tone3": "#9bb8e3",
        "tone4": "#d5e1f9",
        "ink": "#172744",
        "tint": "#f7f9ff",
        "edge": "#d7e1ff",
        "blueprints": set(),
        "endpoints": set(),
        "prefixes": (),
    },
}


def _theme_for_key(key: str) -> AreaTheme | None:
    data = WORKSPACE_THEMES.get(key)
    if not data:
        return None
    return AreaTheme(
        key=key,
        label=data["label"],
        emoji=data["emoji"],
        icon=data["icon"],
        area=data["area"],
        tone2=data["tone2"],
        tone3=data["tone3"],
        tone4=data["tone4"],
        ink=data["ink"],
        tint=data["tint"],
        edge=data["edge"],
    )


def get_all_workspace_themes() -> dict[str, dict[str, Any]]:
    """Retorna todas as paletas e metadados para injeção no Jinja/CSS."""
    return {k: {**v} for k, v in WORKSPACE_THEMES.items()}


def get_current_page_theme() -> AreaTheme | None:
    """Resolve o tema da página atual com base no contexto do request.

    Ordem de resolução:
    1. Override explícito via g.page_theme (definido na view ou no template).
    2. Correspondência direta por blueprint do Flask.
    3. Correspondência direta por endpoint ou prefixo do endpoint.
    4. Correspondência pelo início da URL (request.path).
    5. Fallback para rotas públicas: None (layout neutro padrão).
    """
    if not has_request_context():
        return None

    # 1. Override explícito na requisição
    explicit_key = getattr(g, "page_theme", None)
    if explicit_key and explicit_key in WORKSPACE_THEMES:
        return _theme_for_key(explicit_key)

    endpoint = request.endpoint or ""
    blueprint = request.blueprint or ""
    path = request.path or ""

    # Rotas que são explicitamente neutras (ex: landing page, auth, termos, pública)
    if endpoint in {"index", "home", "static"} or path in {"/", "/index"}:
        return None

    # 2. Correspondência por Blueprint
    if blueprint:
        for key, conf in WORKSPACE_THEMES.items():
            if blueprint in conf.get("blueprints", set()):
                return _theme_for_key(key)

    # 3. Correspondência por Endpoint
    if endpoint:
        endpoint_short = endpoint.rsplit(".", 1)[-1]
        for key, conf in WORKSPACE_THEMES.items():
            endpoints = conf.get("endpoints", set())
            if endpoint in endpoints or endpoint_short in endpoints:
                return _theme_for_key(key)
            # Prefixos de endpoint (ex: painel_admin.*)
            if any(endpoint.startswith(f"{ep}.") for ep in endpoints):
                return _theme_for_key(key)

    # 4. Correspondência por prefixo de URL (request.path)
    for key, conf in WORKSPACE_THEMES.items():
        for prefix in conf.get("prefixes", ()):
            if path == prefix or path.startswith(f"{prefix}/"):
                return _theme_for_key(key)

    return None
