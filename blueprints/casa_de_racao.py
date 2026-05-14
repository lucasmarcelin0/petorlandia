from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("casa_de_racao_routes", __name__)

    bp.add_url_rule(
        "/minha-casa-de-racao",
        view_func=lazy_view("minha_casa_de_racao"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/casa-de-racao/<int:casa_id>",
        view_func=lazy_view("casa_de_racao_dashboard"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/casa-de-racao/<int:casa_id>/produtos",
        view_func=lazy_view("casa_de_racao_produtos"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/casa-de-racao/<int:casa_id>/produto/<int:product_id>/editar",
        view_func=lazy_view("casa_produto_editar"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/casa-de-racao/<int:casa_id>/produto/<int:product_id>/toggle",
        view_func=lazy_view("casa_produto_toggle"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/casa-de-racao/<int:casa_id>/vendas",
        view_func=lazy_view("casa_de_racao_vendas"),
    )
    bp.add_url_rule(
        "/casa-de-racao/<int:casa_id>/entregas",
        view_func=lazy_view("casa_de_racao_entregas"),
    )
    bp.add_url_rule(
        "/casa-de-racao/<int:casa_id>/entrega/<int:dr_id>/status",
        view_func=lazy_view("casa_entrega_atualizar_status"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/casas-de-racao",
        view_func=lazy_view("admin_casas_de_racao"),
    )
    bp.add_url_rule(
        "/admin/casa-de-racao/<int:casa_id>/aprovar",
        view_func=lazy_view("admin_aprovar_casa_de_racao"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/casa-de-racao/<int:casa_id>/suspender",
        view_func=lazy_view("admin_suspender_casa_de_racao"),
        methods=["POST"],
    )
    return bp
