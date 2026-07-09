"""Rotas de Web Push: chave pública VAPID e inscrição/desinscrição."""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from services.push import (
    delete_subscription,
    push_enabled,
    push_to_user,
    save_subscription,
    vapid_public_key,
)

bp = Blueprint("push_routes", __name__)


def get_blueprint():
    return bp


@bp.route("/push/vapid-public-key", methods=["GET"])
def push_vapid_public_key():
    if not push_enabled():
        return jsonify({"enabled": False, "publicKey": None})
    return jsonify({"enabled": True, "publicKey": vapid_public_key()})


@bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    data = request.get_json(silent=True) or {}
    subscription = data.get("subscription") or data
    try:
        save_subscription(
            current_user.id,
            subscription,
            user_agent=request.headers.get("User-Agent"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({"success": True})


@bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({"success": False, "message": "endpoint é obrigatório"}), 400
    removed = delete_subscription(current_user.id, endpoint)
    return jsonify({"success": True, "removed": removed})


@bp.route("/push/test", methods=["POST"])
@login_required
def push_test():
    """Dispara um push de teste para o próprio usuário (validação do opt-in)."""
    sent = push_to_user(
        current_user.id,
        "Notificações ativas 🐾",
        "Pronto! Você vai receber lembretes do PetOrlândia por aqui.",
        url="/",
        tag="push-test",
    )
    return jsonify({"success": True, "sent": sent})
