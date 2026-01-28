from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("clinica_routes", __name__)

    bp.add_url_rule("/clinicas", view_func=app_module.clinicas)
    bp.add_url_rule(
        "/minha-clinica",
        view_func=app_module.minha_clinica,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>",
        view_func=app_module.clinic_detail,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/convites/<int:invite_id>/cancel",
        view_func=app_module.cancel_clinic_invite,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/convites/<int:invite_id>/resend",
        view_func=app_module.resend_clinic_invite,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/veterinario",
        view_func=app_module.create_clinic_veterinario,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/convites/clinica",
        view_func=app_module.clinic_invites,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/convites/<int:invite_id>/<string:action>",
        view_func=app_module.respond_clinic_invite,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/estoque",
        view_func=app_module.clinic_stock,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/estoque/item/<int:item_id>/atualizar",
        view_func=app_module.update_inventory_item,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/novo_orcamento",
        view_func=app_module.novo_orcamento,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/orcamento/<int:orcamento_id>/editar",
        view_func=app_module.editar_orcamento,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/orcamento/<int:orcamento_id>/enviar",
        view_func=app_module.enviar_orcamento,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/orcamento/<int:orcamento_id>/status",
        view_func=app_module.atualizar_status_orcamento,
        methods=["PATCH"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/orcamentos",
        view_func=app_module.orcamentos,
    )
    bp.add_url_rule(
        "/dashboard/orcamentos",
        view_func=app_module.dashboard_orcamentos,
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/dashboard",
        view_func=app_module.clinic_dashboard,
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/funcionarios",
        view_func=app_module.clinic_staff,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/funcionario/<int:user_id>/permissoes",
        view_func=app_module.clinic_staff_permissions,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/funcionario/<int:user_id>/remove",
        view_func=app_module.remove_funcionario,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/horario/<int:horario_id>/delete",
        view_func=app_module.delete_clinic_hour,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/remove",
        view_func=app_module.remove_veterinario,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/especialista/<int:veterinario_id>/remove",
        view_func=app_module.remove_specialist,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/schedule/<int:horario_id>/delete",
        view_func=app_module.delete_vet_schedule_clinic,
        methods=["POST"],
    )
    return bp
