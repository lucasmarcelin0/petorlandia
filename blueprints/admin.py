from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("admin_routes", __name__)

    bp.add_url_rule(
        "/admin/users/<int:user_id>/promover_veterinario",
        view_func=lazy_view("admin_promote_veterinarian"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/users/<int:user_id>/promover_entregador",
        view_func=lazy_view("admin_promote_delivery"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/users/<int:user_id>/remover_entregador",
        view_func=lazy_view("admin_remove_delivery"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/users/<int:user_id>/promover_parceiro",
        view_func=lazy_view("admin_promote_parceiro"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/users/<int:user_id>/remover_parceiro",
        view_func=lazy_view("admin_remove_parceiro"),
        methods=["POST"],
    )
    bp.add_url_rule(\
        "/admin/planos/dashboard",
        view_func=lazy_view("planos_dashboard"),
    )
    bp.add_url_rule(
        "/admin/site-flags/toggle",
        view_func=lazy_view("admin_toggle_site_flag"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/parcerias",
        view_func=lazy_view("admin_parcerias"),
    )
    bp.add_url_rule(
        "/admin/parcerias/convite",
        view_func=lazy_view("admin_criar_convite"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/clinica/<int:clinica_id>/aprovar",
        view_func=lazy_view("admin_aprovar_clinica"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/clinica/<int:clinica_id>/rejeitar",
        view_func=lazy_view("admin_rejeitar_clinica"),
        methods=["POST"],
    )
    return bp
