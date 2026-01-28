from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("planos_routes", __name__)

    bp.add_url_rule("/plano-saude", view_func=app_module.plano_saude_overview)
    bp.add_url_rule(
        "/animal/<int:animal_id>/planosaude",
        view_func=app_module.planosaude_animal,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/plano-saude/<int:animal_id>/contratar",
        view_func=app_module.contratar_plano,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/consulta/<int:consulta_id>/validar-plano",
        view_func=app_module.validar_plano_consulta,
        methods=["POST"],
    )
    return bp
