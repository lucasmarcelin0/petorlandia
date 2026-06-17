from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("parceiro_routes", __name__)

    bp.add_url_rule(
        "/parceiro",
        view_func=lazy_view("parceiro_dashboard"),
    )
    bp.add_url_rule(
        "/parceiro/estabelecimentos/novo",
        view_func=lazy_view("parceiro_novo_estabelecimento"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/parceiro/usuarios/novo",
        view_func=lazy_view("parceiro_novo_usuario"),
        methods=["GET", "POST"],
    )
    return bp
