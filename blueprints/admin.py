from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("admin_routes", __name__)

    bp.add_url_rule(
        "/admin/users/<int:user_id>/promover_veterinario",
        view_func=app_module.admin_promote_veterinarian,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/users/<int:user_id>/promover_entregador",
        view_func=app_module.admin_promote_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/users/<int:user_id>/remover_entregador",
        view_func=app_module.admin_remove_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/planos/dashboard",
        view_func=app_module.planos_dashboard,
    )
    return bp
