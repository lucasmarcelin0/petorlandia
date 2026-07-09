from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("bulario_routes", __name__)

    bp.add_url_rule(
        "/bulario",
        view_func=lazy_view("bulario"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/bulario/novo",
        view_func=lazy_view("bulario_novo"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/bulario/<int:medicamento_id>",
        view_func=lazy_view("bulario_detalhe"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/bulario/curadoria",
        view_func=lazy_view("bulario_curadoria"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/bulario/curadoria/sincronizar",
        view_func=lazy_view("bulario_curadoria_sincronizar"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/bulario/curadoria/<int:review_id>/status",
        view_func=lazy_view("bulario_curadoria_status"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/bulario/<int:medicamento_id>/editar",
        view_func=lazy_view("bulario_editar"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/bulario/<int:medicamento_id>/excluir",
        view_func=lazy_view("bulario_excluir"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/bulario/buscar",
        view_func=lazy_view("bulario_buscar_api"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/api/bulario/sugerir-dose",
        view_func=lazy_view("bulario_sugerir_dose_api"),
        methods=["GET"],
    )

    return bp
