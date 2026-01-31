from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("agendamentos_routes", __name__)

    bp.add_url_rule("/veterinarios", view_func=lazy_view("veterinarios"))
    bp.add_url_rule(
        "/veterinario/<int:veterinario_id>",
        view_func=lazy_view("vet_detail"),
    )
    bp.add_url_rule(
        "/admin/veterinario/<int:veterinario_id>/especialidades",
        view_func=lazy_view("edit_vet_specialties"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/confirmation",
        view_func=lazy_view("appointment_confirmation"),
    )
    bp.add_url_rule(
        "/appointments",
        view_func=lazy_view("appointments"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/appointments/calendar",
        view_func=lazy_view("appointments_calendar"),
    )
    bp.add_url_rule(
        "/appointments/<int:veterinario_id>/schedule/<int:horario_id>/edit",
        view_func=lazy_view("edit_vet_schedule_slot"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:veterinario_id>/schedule/bulk_delete",
        view_func=lazy_view("bulk_delete_vet_schedule"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:veterinario_id>/schedule/<int:horario_id>/delete",
        view_func=lazy_view("delete_vet_schedule"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/pending",
        view_func=lazy_view("pending_appointments"),
    )
    bp.add_url_rule(
        "/appointments/manage",
        view_func=lazy_view("manage_appointments"),
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/edit",
        view_func=lazy_view("edit_appointment"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/nfse",
        view_func=lazy_view("appointment_emit_nfse"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/status",
        view_func=lazy_view("update_appointment_status"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/appointments/<int:appointment_id>/delete",
        view_func=lazy_view("delete_appointment"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/animal/<int:animal_id>/schedule_exam",
        view_func=lazy_view("schedule_exam"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/status",
        view_func=lazy_view("update_exam_appointment_status"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/update",
        view_func=lazy_view("update_exam_appointment"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/requester_update",
        view_func=lazy_view("update_exam_appointment_requester"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/exam_appointment/<int:appointment_id>/delete",
        view_func=lazy_view("delete_exam_appointment"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/animal/<int:animal_id>/exam_appointments",
        view_func=lazy_view("animal_exam_appointments"),
    )
    return bp
