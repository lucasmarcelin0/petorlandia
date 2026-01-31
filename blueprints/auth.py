from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("auth_routes", __name__)

    bp.add_url_rule(
        "/reset_password_request",
        view_func=lazy_view("reset_password_request"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/reset_password/<token>",
        view_func=lazy_view("reset_password"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/register",
        view_func=lazy_view("register"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/login",
        view_func=lazy_view("login_view"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule("/logout", view_func=lazy_view("logout"))
    bp.add_url_rule(
        "/profile",
        view_func=lazy_view("profile"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/change_password",
        view_func=lazy_view("change_password"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/delete_account",
        view_func=lazy_view("delete_account"),
        methods=["POST"],
    )
    return bp
