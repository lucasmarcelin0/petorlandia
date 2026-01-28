from flask import Blueprint


def get_blueprint():
    import app as app_module

    bp = Blueprint("financeiro_routes", __name__)

    bp.add_url_rule("/contabilidade", view_func=app_module.contabilidade_home)
    bp.add_url_rule(
        "/contabilidade/financeiro",
        view_func=app_module.contabilidade_financeiro,
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos",
        view_func=app_module.contabilidade_pagamentos,
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/novo",
        view_func=app_module.contabilidade_pagamentos_novo,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/<int:payment_id>/editar",
        view_func=app_module.contabilidade_pagamentos_editar,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/<int:payment_id>/delete",
        view_func=app_module.contabilidade_pagamentos_delete,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/<int:payment_id>/marcar_pago",
        view_func=app_module.contabilidade_pagamentos_marcar_pago,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/plantonistas/novo",
        view_func=app_module.contabilidade_plantonistas_novo,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/plantonistas/quick-create",
        view_func=app_module.contabilidade_plantonistas_quick_create,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/plantonistas/<int:escala_id>/editar",
        view_func=app_module.contabilidade_plantonistas_editar,
        methods=["GET", "POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/plantao/<int:escala_id>/confirmar",
        view_func=app_module.contabilidade_plantao_confirmar,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/pagamentos/plantao/<int:escala_id>/gerar_pagamento",
        view_func=app_module.contabilidade_plantao_gerar_pagamento,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/obrigacoes",
        view_func=app_module.contabilidade_obrigacoes,
    )
    bp.add_url_rule(
        "/contabilidade/nfse",
        view_func=app_module.contabilidade_nfse,
    )
    bp.add_url_rule(
        "/contabilidade/nfse/emitir",
        view_func=app_module.contabilidade_nfse_emitir,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/nfse/processar_fila",
        view_func=app_module.contabilidade_nfse_processar_fila,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/nfse/<int:issue_id>/reprocessar",
        view_func=app_module.contabilidade_nfse_reprocessar,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/nfse/<int:issue_id>/cancelar",
        view_func=app_module.contabilidade_nfse_cancelar,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/nfse/<int:issue_id>/substituir",
        view_func=app_module.contabilidade_nfse_substituir,
        methods=["POST"],
    )
    bp.add_url_rule(
        "/contabilidade/nfse/<int:issue_id>/download/<string:kind>",
        view_func=app_module.contabilidade_nfse_download,
    )
    return bp
