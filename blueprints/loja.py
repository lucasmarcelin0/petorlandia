from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("loja_routes", __name__)

    bp.add_url_rule(
        "/orders/new",
        view_func=app_module.create_order,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/orders/<int:order_id>/request_delivery",
        view_func=app_module.request_delivery,
        methods=["POST"],
    )
    bp.add_url_rule("/delivery_requests", view_func=app_module.list_delivery_requests)
    bp.add_url_rule(
        "/admin/delivery/<int:req_id>",
        view_func=app_module.admin_delivery_detail,
    )
    bp.add_url_rule(
        "/worker/delivery/<int:req_id>",
        view_func=app_module.worker_delivery_detail,
    )
    bp.add_url_rule(
        "/delivery_requests/<int:req_id>/accept",
        view_func=app_module.accept_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/delivery_requests/<int:req_id>/complete",
        view_func=app_module.complete_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/delivery_requests/<int:req_id>/cancel",
        view_func=app_module.cancel_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/delivery_requests/<int:req_id>/buyer_cancel",
        view_func=app_module.buyer_cancel_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/delivery/<int:req_id>",
        view_func=app_module.delivery_detail,
    )
    bp.add_url_rule("/admin/mapa_tutores", view_func=app_module.admin_tutor_map)
    bp.add_url_rule(
        "/admin/api/tutor_markers",
        view_func=app_module.admin_tutor_markers_api,
    )
    bp.add_url_rule(
        "/admin/api/geocode_addresses",
        view_func=app_module.admin_geocode_addresses,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/api/geocode_addresses/status",
        view_func=app_module.admin_geocode_status,
    )
    bp.add_url_rule(
        "/admin/delivery_overview",
        view_func=app_module.delivery_overview,
    )
    bp.add_url_rule(
        "/admin/delivery_requests/<int:req_id>/status/<status>",
        view_func=app_module.admin_set_delivery_status,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/delivery_requests/<int:req_id>/delete",
        view_func=app_module.admin_delete_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/delivery_requests/<int:req_id>/archive",
        view_func=app_module.admin_archive_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/delivery_requests/<int:req_id>/unarchive",
        view_func=app_module.admin_unarchive_delivery,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/admin/delivery_archive",
        view_func=app_module.delivery_archive,
    )
    bp.add_url_rule(
        "/admin/data-share-logs",
        view_func=app_module.admin_data_share_logs,
    )
    bp.add_url_rule("/delivery_archive", view_func=app_module.delivery_archive_user)
    bp.add_url_rule("/loja", view_func=app_module.loja)
    bp.add_url_rule("/loja/data", view_func=app_module.loja_data)
    bp.add_url_rule(
        "/produto/<int:product_id>",
        view_func=app_module.produto_detail,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/carrinho/adicionar/<int:product_id>",
        view_func=app_module.adicionar_carrinho,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/carrinho/increase/<int:item_id>",
        view_func=app_module.aumentar_item_carrinho,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/carrinho/decrease/<int:item_id>",
        view_func=app_module.diminuir_item_carrinho,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/carrinho",
        view_func=app_module.ver_carrinho,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/carrinho/salvar_endereco",
        view_func=app_module.carrinho_salvar_endereco,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/checkout/confirm",
        view_func=app_module.checkout_confirm,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/checkout",
        view_func=app_module.checkout,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/notificacoes",
        view_func=app_module.notificacoes_mercado_pago,
        methods=["POST", "GET"],
    )
    bp.add_url_rule(
        "/pagamento/<status>",
        view_func=app_module.legacy_pagamento,
    )
    bp.add_url_rule(
        "/order/<int:order_id>/edit_address",
        view_func=app_module.edit_order_address,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/payment_status/<int:payment_id>",
        view_func=app_module.payment_status,
    )
    bp.add_url_rule("/minhas-compras", view_func=app_module.minhas_compras)
    bp.add_url_rule(
        "/pedido/<int:order_id>",
        view_func=app_module.pedido_detail,
    )
    return bp
