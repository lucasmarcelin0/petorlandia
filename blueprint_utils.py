def _is_blueprint_registered(app, blueprint):
    if blueprint.name in app.blueprints:
        return True
    prefix = f"{blueprint.name}."
    return any(endpoint.startswith(prefix) for endpoint in app.view_functions)


def _register_with_alias(app, blueprint):
    app.register_blueprint(blueprint)
    prefix = f"{blueprint.name}."
    existing_endpoints = set(app.view_functions)
    for rule in list(app.url_map.iter_rules()):
        if not rule.endpoint.startswith(prefix):
            continue
        alias = rule.endpoint[len(prefix):]
        if alias in existing_endpoints:
            continue
        app.add_url_rule(
            rule.rule,
            endpoint=alias,
            view_func=app.view_functions[rule.endpoint],
            methods=rule.methods,
            defaults=rule.defaults,
        )
        existing_endpoints.add(alias)


def register_domain_blueprints(app):
    from blueprints import (
        admin,
        agendamentos,
        api,
        auth,
        clinica,
        financeiro,
        fiscal,
        loja,
        mensagens,
        planos,
    )

    clinica_bp = clinica.get_blueprint()
    if not _is_blueprint_registered(app, clinica_bp):
        _register_with_alias(app, clinica_bp)

    agendamentos_bp = agendamentos.get_blueprint()
    if not _is_blueprint_registered(app, agendamentos_bp):
        _register_with_alias(app, agendamentos_bp)

    loja_bp = loja.get_blueprint()
    if not _is_blueprint_registered(app, loja_bp):
        _register_with_alias(app, loja_bp)

    auth_bp = auth.get_blueprint()
    if not _is_blueprint_registered(app, auth_bp):
        _register_with_alias(app, auth_bp)

    mensagens_bp = mensagens.get_blueprint()
    if not _is_blueprint_registered(app, mensagens_bp):
        _register_with_alias(app, mensagens_bp)

    financeiro_bp = financeiro.get_blueprint()
    if not _is_blueprint_registered(app, financeiro_bp):
        _register_with_alias(app, financeiro_bp)

    fiscal_bp = fiscal.get_blueprint()
    if not _is_blueprint_registered(app, fiscal_bp):
        _register_with_alias(app, fiscal_bp)

    planos_bp = planos.get_blueprint()
    if not _is_blueprint_registered(app, planos_bp):
        _register_with_alias(app, planos_bp)

    admin_bp = admin.get_blueprint()
    if not _is_blueprint_registered(app, admin_bp):
        _register_with_alias(app, admin_bp)

    api_bp = api.get_blueprint()
    if not _is_blueprint_registered(app, api_bp):
        _register_with_alias(app, api_bp)
