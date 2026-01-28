from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("auth_routes", __name__)

    bp.add_url_rule(
        "/reset_password_request",
        view_func=app_module.reset_password_request,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/reset_password/<token>",
        view_func=app_module.reset_password,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/register",
        view_func=app_module.register,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/login",
        view_func=app_module.login_view,
        methods=["GET", "POST"],
    )
    bp.add_url_rule("/logout", view_func=app_module.logout)
    bp.add_url_rule(
        "/profile",
        view_func=app_module.profile,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/change_password",
        view_func=app_module.change_password,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/delete_account",
        view_func=app_module.delete_account,
        methods=["POST"],
    )
    return bp
