from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("mensagens_routes", __name__)

    bp.add_url_rule(
        "/mensagem/<int:animal_id>",
        view_func=lazy_view("enviar_mensagem"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/mensagem/<int:message_id>/aceitar",
        view_func=lazy_view("aceitar_interesse"),
        methods=["POST"],
    )
    bp.add_url_rule("/mensagens", view_func=lazy_view("mensagens"))
    bp.add_url_rule(
        "/chat/<int:animal_id>",
        view_func=lazy_view("chat_messages"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/chat/<int:animal_id>/view",
        view_func=lazy_view("chat_view"),
    )
    bp.add_url_rule(
        "/conversa/<int:animal_id>/<int:user_id>",
        view_func=lazy_view("conversa"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/conversa_admin",
        view_func=lazy_view("conversa_admin"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/conversa_admin/<int:user_id>",
        view_func=lazy_view("conversa_admin"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/mensagens_admin",
        view_func=lazy_view("mensagens_admin"),
    )
    return bp
