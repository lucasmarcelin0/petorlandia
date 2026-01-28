from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("mensagens_routes", __name__)

    bp.add_url_rule(
        "/mensagem/<int:animal_id>",
        view_func=app_module.enviar_mensagem,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/mensagem/<int:message_id>/aceitar",
        view_func=app_module.aceitar_interesse,
        methods=["POST"],
    )
    bp.add_url_rule("/mensagens", view_func=app_module.mensagens)
    bp.add_url_rule(
        "/chat/<int:animal_id>",
        view_func=app_module.chat_messages,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/chat/<int:animal_id>/view",
        view_func=app_module.chat_view,
    )
    bp.add_url_rule(
        "/conversa/<int:animal_id>/<int:user_id>",
        view_func=app_module.conversa,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/conversa_admin",
        view_func=app_module.conversa_admin,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/conversa_admin/<int:user_id>",
        view_func=app_module.conversa_admin,
        methods=["GET", "POST"],
    )
    bp.add_url_rule("/mensagens_admin", view_func=app_module.mensagens_admin)
    return bp
