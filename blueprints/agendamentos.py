from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("agendamentos_routes", __name__)

    bp.add_url_rule("/veterinarios", view_func=app_module.veterinarios)
    bp.add_url_rule("/veterinario/<int:veterinario_id>", view_func=app_module.vet_detail)
    bp.add_url_rule(
        "/admin/veterinario/<int:veterinario_id>/especialidades",
        view_func=app_module.edit_vet_specialties,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/confirmation",
        view_func=app_module.appointment_confirmation,
    )
    bp.add_url_rule(
        "/appointments",
        view_func=app_module.appointments,
        methods=["GET", "POST"],
    )
    bp.add_url_rule("/appointments/calendar", view_func=app_module.appointments_calendar)
    bp.add_url_rule(
        "/appointments/<int:veterinario_id>/schedule/<int:horario_id>/edit",
        view_func=app_module.edit_vet_schedule_slot,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:veterinario_id>/schedule/bulk_delete",
        view_func=app_module.bulk_delete_vet_schedule,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:veterinario_id>/schedule/<int:horario_id>/delete",
        view_func=app_module.delete_vet_schedule,
        methods=["POST"],
    )
    bp.add_url_rule("/appointments/pending", view_func=app_module.pending_appointments)
    bp.add_url_rule("/appointments/manage", view_func=app_module.manage_appointments)
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/edit",
        view_func=app_module.edit_appointment,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/status",
        view_func=app_module.update_appointment_status,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/delete",
        view_func=app_module.delete_appointment,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/animal/<int:animal_id>/schedule_exam",
        view_func=app_module.schedule_exam,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/status",
        view_func=app_module.update_exam_appointment_status,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/update",
        view_func=app_module.update_exam_appointment,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/requester_update",
        view_func=app_module.update_exam_appointment_requester,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/delete",
        view_func=app_module.delete_exam_appointment,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/animal/<int:animal_id>/exam_appointments",
        view_func=app_module.animal_exam_appointments,
    )
    return bp
