from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("planos_routes", __name__)

    bp.add_url_rule(
        "/plano-saude",
        view_func=lazy_view("plano_saude_overview"),
    )
    bp.add_url_rule(
        "/animal/<int:animal_id>/planosaude",
        view_func=lazy_view("planosaude_animal"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/plano-saude/<int:animal_id>/contratar",
        view_func=lazy_view("contratar_plano"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/consulta/<int:consulta_id>/validar-plano",
        view_func=lazy_view("validar_plano_consulta"),
        methods=["POST"],
    )
    return bp
