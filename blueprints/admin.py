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
        "/admin/planos/dashboard",
        view_func=lazy_view("planos_dashboard"),
    )
    return bp
