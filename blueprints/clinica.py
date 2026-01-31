from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("clinica_routes", __name__)

    bp.add_url_rule("/clinicas", view_func=lazy_view("clinicas"))
    bp.add_url_rule(
        "/minha-clinica",
        view_func=lazy_view("minha_clinica"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>",
        view_func=lazy_view("clinic_detail"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/convites/<int:invite_id>/cancel",
        view_func=lazy_view("cancel_clinic_invite"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/convites/<int:invite_id>/resend",
        view_func=lazy_view("resend_clinic_invite"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/veterinario",
        view_func=lazy_view("create_clinic_veterinario"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/convites/clinica",
        view_func=lazy_view("clinic_invites"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/convites/<int:invite_id>/<string:action>",
        view_func=lazy_view("respond_clinic_invite"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/estoque",
        view_func=lazy_view("clinic_stock"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/estoque/item/<int:item_id>/atualizar",
        view_func=lazy_view("update_inventory_item"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/novo_orcamento",
        view_func=lazy_view("novo_orcamento"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/orcamento/<int:orcamento_id>/editar",
        view_func=lazy_view("editar_orcamento"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/orcamento/<int:orcamento_id>/enviar",
        view_func=lazy_view("enviar_orcamento"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/orcamento/<int:orcamento_id>/status",
        view_func=lazy_view("atualizar_status_orcamento"),
        methods=["PATCH"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/orcamentos",
        view_func=lazy_view("orcamentos"),
    )
    bp.add_url_rule(
        "/dashboard/orcamentos",
        view_func=lazy_view("dashboard_orcamentos"),
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/dashboard",
        view_func=lazy_view("clinic_dashboard"),
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/funcionarios",
        view_func=lazy_view("clinic_staff"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/funcionario/<int:user_id>/permissoes",
        view_func=lazy_view("clinic_staff_permissions"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/funcionario/<int:user_id>/remove",
        view_func=lazy_view("remove_funcionario"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/horario/<int:horario_id>/delete",
        view_func=lazy_view("delete_clinic_hour"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/remove",
        view_func=lazy_view("remove_veterinario"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/especialista/<int:veterinario_id>/remove",
        view_func=lazy_view("remove_specialist"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/schedule/<int:horario_id>/delete",
        view_func=lazy_view("delete_vet_schedule_clinic"),
        methods=["POST"],
    )
    return bp
