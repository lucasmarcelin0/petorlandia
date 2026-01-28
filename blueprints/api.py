from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("api_routes", __name__)

    bp.add_url_rule("/api/cep/<cep>", view_func=app_module.api_cep_lookup)
    bp.add_url_rule("/api/geocode/reverse", view_func=app_module.api_reverse_geocode)
    bp.add_url_rule(
        "/api/geocode/address",
        view_func=app_module.api_forward_geocode,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/messages/threads",
        view_func=app_module.api_message_threads,
    )
    bp.add_url_rule(
        "/api/conversa/<int:animal_id>/<int:user_id>",
        view_func=app_module.api_conversa_message,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/conversa_admin",
        view_func=app_module.api_conversa_admin_message,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/conversa_admin/<int:user_id>",
        view_func=app_module.api_conversa_admin_message,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/seguradoras/sinistros",
        view_func=app_module.api_criar_sinistro,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/seguradoras/sinistros/<int:claim_id>",
        view_func=app_module.api_status_sinistro,
    )
    bp.add_url_rule(
        "/api/seguradoras/planos/<int:plan_id>/historico",
        view_func=app_module.api_historico_uso,
    )
    bp.add_url_rule(
        "/api/seguradoras/consultas/<int:consulta_id>/autorizacao",
        view_func=app_module.api_status_autorizacao,
    )
    bp.add_url_rule(
        "/api/shares",
        view_func=app_module.shares_api,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/api/shares/<int:request_id>/approve",
        view_func=app_module.approve_share_request,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/shares/<int:request_id>/deny",
        view_func=app_module.deny_share_request,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/shares/confirm",
        view_func=app_module.confirm_share_request,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/share-requests/<string:token>",
        view_func=app_module.share_request_detail,
    )
    bp.add_url_rule("/api/my_pets", view_func=app_module.api_my_pets)
    bp.add_url_rule("/api/clinic_pets", view_func=app_module.api_clinic_pets)
    bp.add_url_rule("/api/my_appointments", view_func=app_module.api_my_appointments)
    bp.add_url_rule(
        "/api/user_appointments/<int:user_id>",
        view_func=app_module.api_user_appointments,
    )
    bp.add_url_rule(
        "/api/appointments/<int:appointment_id>/reschedule",
        view_func=app_module.api_reschedule_appointment,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/api/clinic_appointments/<int:clinica_id>",
        view_func=app_module.api_clinic_appointments,
    )
    bp.add_url_rule(
        "/api/vet_appointments/<int:veterinario_id>",
        view_func=app_module.api_vet_appointments,
    )
    bp.add_url_rule("/api/specialists", view_func=app_module.api_specialists)
    bp.add_url_rule("/api/specialties", view_func=app_module.api_specialties)
    bp.add_url_rule(
        "/api/specialist/<int:veterinario_id>/available_times",
        view_func=app_module.api_specialist_available_times,
    )
    bp.add_url_rule(
        "/api/specialist/<int:veterinario_id>/weekly_schedule",
        view_func=app_module.api_specialist_weekly_schedule,
    )
    bp.add_url_rule("/api/delivery_counts", view_func=app_module.api_delivery_counts)
    bp.add_url_rule(
        "/api/payment_status/<int:payment_id>",
        view_func=app_module.api_payment_status,
    )
    bp.add_url_rule("/api/minhas-compras", view_func=app_module.api_minhas_compras)
    return bp
