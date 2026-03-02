from flask import Blueprint

from blueprints.utils import lazy_view


def get_blueprint():
    bp = Blueprint("oauth_routes", __name__)

    bp.add_url_rule("/oauth/authorize", view_func=lazy_view("oauth_authorize"), methods=["GET", "POST"])
    bp.add_url_rule("/oauth/token", view_func=lazy_view("oauth_token"), methods=["POST"])
    bp.add_url_rule(
        "/.well-known/openid-configuration",
        view_func=lazy_view("openid_configuration"),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/.well-known/oauth-authorization-server",
        endpoint="oauth_authorization_server_metadata",
        view_func=lazy_view("openid_configuration"),
        methods=["GET"],
    )
    bp.add_url_rule("/.well-known/jwks.json", view_func=lazy_view("jwks"), methods=["GET"])
    bp.add_url_rule("/oauth/userinfo", view_func=lazy_view("oauth_userinfo"), methods=["GET"])
    bp.add_url_rule("/oauth/revoke", view_func=lazy_view("oauth_revoke"), methods=["POST"])
    bp.add_url_rule("/oauth/introspect", view_func=lazy_view("oauth_introspect"), methods=["POST"])
    bp.add_url_rule("/oauth/register", view_func=lazy_view("oauth_dynamic_client_registration"), methods=["POST"])
    # MCP server endpoint — JSON-RPC 2.0 over HTTP
    # GET: unauthenticated capability probe (Claude uses this before OAuth)
    # POST: authenticated JSON-RPC requests
    bp.add_url_rule("/mcp", view_func=lazy_view("mcp_server"), methods=["GET", "POST", "OPTIONS"])
    # RFC 9396 Protected Resource Metadata — enables OAuth discovery for path-based URLs
    bp.add_url_rule(
        "/.well-known/oauth-protected-resource",
        view_func=lazy_view("mcp_protected_resource_metadata"),
        methods=["GET"],
    )

    return bp
