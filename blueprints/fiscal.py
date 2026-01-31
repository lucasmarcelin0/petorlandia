from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("fiscal_routes", __name__)

    bp.add_url_rule(
        "/fiscal/settings",
        view_func=lazy_view("fiscal_settings"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/fiscal/certificate",
        view_func=lazy_view("fiscal_certificate_upload"),
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/fiscal/documents",
        view_func=lazy_view("fiscal_documents"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/fiscal/documents/<int:document_id>",
        view_func=lazy_view("fiscal_document_detail"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/fiscal/documents/<int:document_id>/status",
        view_func=lazy_view("fiscal_document_status"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/fiscal/documents/<int:document_id>/cancel",
        view_func=lazy_view("fiscal_document_cancel"),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/fiscal/exports/xmls",
        view_func=lazy_view("fiscal_exports_xmls"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/fiscal/onboarding",
        view_func=lazy_view("fiscal_onboarding_start"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/fiscal/onboarding/step/<int:step>",
        view_func=lazy_view("fiscal_onboarding_step"),
        methods=["GET", "POST"],
    )

    return bp
