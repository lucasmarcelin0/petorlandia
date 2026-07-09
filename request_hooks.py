"""Hooks de request (request-id, cache de estáticos) e error handlers globais.

Extraído de app.py durante a modularização. Registrar com:

    from request_hooks import register_request_hooks
    register_request_hooks(app)
"""
from __future__ import annotations

import uuid

from flask import (
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException, NotFound

from extensions import db
from helpers import ensure_veterinarian_membership, has_veterinarian_profile


def _attach_request_id():
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())


def _set_request_id_header(response):
    response.headers["X-Request-ID"] = getattr(g, "request_id", "")
    if request.endpoint == "static":
        if request.args.get("v"):
            max_age = int(current_app.config.get("SEND_FILE_VERSIONED_MAX_AGE", 31536000))
            response.headers["Cache-Control"] = f"public, max-age={max_age}, immutable"
        else:
            max_age = int(current_app.config.get("SEND_FILE_MAX_AGE_DEFAULT", 3600))
            response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return response


def handle_http_exception(err):
    current_app.logger.warning(
        "http_exception",
        extra={
            "path": request.path,
            "status_code": err.code,
            "request_id": getattr(g, "request_id", None),
        },
    )
    wants_json = (
        request.accept_mimetypes["application/json"]
        >= request.accept_mimetypes["text/html"]
    )

    is_route_miss_404 = isinstance(err, NotFound) and getattr(request, "routing_exception", None) is not None
    if (
        is_route_miss_404
        and request.accept_mimetypes["text/html"] >= request.accept_mimetypes["application/json"]
        and request.method == 'GET'
        and not request.path.startswith('/static/')
        and current_user.is_authenticated
        and has_veterinarian_profile(current_user)
    ):
        membership = ensure_veterinarian_membership(getattr(current_user, 'veterinario', None))
        if membership and not membership.is_active():
            flash('Sua assinatura de veterinário expirou. Renove para continuar acessando as funcionalidades.', 'warning')
            return redirect(url_for('veterinarian_membership'))

    if wants_json:
        # Defense in depth: avoid leaking cross-tenant resource existence in JSON APIs.
        sanitized_message = err.description
        sanitized_error = err.name
        if err.code in (403, 404):
            sanitized_error = "Not Found"
            sanitized_message = "Resource not found."
        payload = {
            "error": sanitized_error,
            "message": sanitized_message,
            "request_id": getattr(g, "request_id", None),
        }
        status_code = 404 if err.code in (403, 404) else err.code
        return jsonify(payload), status_code
    db.session.rollback()
    return render_template("errors/http.html", error=err), err.code


def handle_csrf_error(err):
    current_app.logger.warning(
        "csrf_error",
        extra={
            "path": request.path,
            "status_code": 400,
            "request_id": getattr(g, "request_id", None),
        },
    )
    wants_json = (
        request.accept_mimetypes["application/json"]
        >= request.accept_mimetypes["text/html"]
    )
    if wants_json:
        payload = {
            "error": "CSRF token missing or invalid",
            "message": "Falha de validação. Recarregue a página e tente novamente.",
            "errors": {"csrf_token": ["Falha de validação. Recarregue a página e tente novamente."]},
            "request_id": getattr(g, "request_id", None),
        }
        return jsonify(payload), 400
    db.session.rollback()
    return render_template("errors/http.html", error=err), 400


def handle_unhandled_exception(err):
    current_app.logger.exception(
        "unhandled_error",
        extra={"path": request.path, "request_id": getattr(g, "request_id", None)},
    )
    wants_json = (
        request.accept_mimetypes["application/json"]
        >= request.accept_mimetypes["text/html"]
    )
    if wants_json:
        payload = {
            "error": "Internal Server Error",
            "message": "Unexpected error.",
            "request_id": getattr(g, "request_id", None),
        }
        return jsonify(payload), 500
    db.session.rollback()
    return render_template("errors/500.html"), 500


def register_request_hooks(app):
    app.before_request(_attach_request_id)
    app.after_request(_set_request_id_header)
    app.register_error_handler(HTTPException, handle_http_exception)
    app.register_error_handler(CSRFError, handle_csrf_error)
    app.register_error_handler(Exception, handle_unhandled_exception)
