from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("planos_routes", __name__)

    bp.add_url_rule(
        "/plano-saude",
        view_func=lazy_view("plano_saude_overview"),
        methods=["GET", "POST"],
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
    # Planos de Banho e Tosa — painel da clínica
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/planos/tosa",
        view_func=lazy_view("clinic_grooming_planos"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/planos/tosa/<int:plan_id>/editar",
        view_func=lazy_view("clinic_grooming_plano_editar"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/planos/tosa/<int:plan_id>/toggle",
        view_func=lazy_view("clinic_grooming_plano_toggle"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/planos/tosa/<int:plan_id>/assinantes",
        view_func=lazy_view("clinic_grooming_assinantes"),
    )
    # Planos de Banho e Tosa — área do tutor
    bp.add_url_rule(
        "/planos/tosa",
        view_func=lazy_view("grooming_planos_publicos"),
    )
    bp.add_url_rule(
        "/planos/tosa/<int:plan_id>/assinar",
        view_func=lazy_view("grooming_assinar"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/planos/tosa/assinatura/<int:sub_id>/cancelar",
        view_func=lazy_view("grooming_cancelar"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/planos/tosa/minhas-assinaturas",
        view_func=lazy_view("grooming_minhas_assinaturas"),
    )
    return bp
