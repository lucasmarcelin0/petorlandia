from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("fiscal_routes", __name__)

    bp.add_url_rule(
        "/fiscal/settings",
        view_func=app_module.fiscal_settings,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/fiscal/documents",
        view_func=app_module.fiscal_documents,
        methods=["GET"],
    )
    bp.add_url_rule(
        "/fiscal/documents/<int:document_id>",
        view_func=app_module.fiscal_document_detail,
        methods=["GET"],
    )

    return bp
