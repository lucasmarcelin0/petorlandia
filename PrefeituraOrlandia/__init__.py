"""Blueprint for the Prefeitura de Orlândia landing page demo."""
from __future__ import annotations

from flask import Blueprint, render_template

prefeitura_bp = Blueprint(
    "prefeitura_orlandia",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/prefeitura-orlandia-static",
    url_prefix="/prefeitura-demonstracao",
)


def _get_featured_services() -> list[dict[str, str]]:
    """Return static metadata describing the highlighted services."""
    return [
        {
            "title": "Portal do Cidadão",
            "description": "Emita certidões, acompanhe protocolos e agende atendimentos sem sair de casa.",
            "icon": "fa-regular fa-id-card",
        },
        {
            "title": "Saúde Digital",
            "description": "Marque consultas, confira resultados e receba avisos em tempo real pela plataforma municipal.",
            "icon": "fa-solid fa-heart-pulse",
        },
        {
            "title": "Educação Conectada",
            "description": "Acesse boletins, calendários escolares e materiais pedagógicos em um só lugar.",
            "icon": "fa-solid fa-graduation-cap",
        },
        {
            "title": "Transparência 360º",
            "description": "Acompanhe obras, licitações e indicadores financeiros com relatórios atualizados.",
            "icon": "fa-solid fa-chart-line",
        },
    ]


def _get_highlights() -> list[dict[str, str]]:
    """Return the list of highlighted news cards."""
    return [
        {
            "title": "Novo Pronto Atendimento 24h",
            "text": "Unidade equipada com telemedicina e acompanhamento remoto para pacientes crônicos.",
            "image": "images/4164909925e4420cad674f89c436d901_Urinaria.jpg",
        },
        {
            "title": "Programa Cidade Sustentável",
            "text": "Monitoramento inteligente de resíduos e coleta seletiva ampliada para 100% dos bairros.",
            "image": "images/2aff5b72d70b40daab5dd1f26115594d_rs.jpg",
        },
        {
            "title": "Economia em Foco",
            "text": "Portal reúne dados de arrecadação e investimentos com comparativos em tempo real.",
            "image": "images/BrasaoOrlandia.svg.png",
        },
    ]


@prefeitura_bp.route("/")
def landing_page():
    """Render the Prefeitura digital experience demo."""
    return render_template(
        "prefeitura_demonstracao.html",
        services=_get_featured_services(),
        highlights=_get_highlights(),
    )


@prefeitura_bp.route("")
def landing_page_no_slash():
    """Route without trailing slash for consistency with marketing links."""
    return landing_page()
