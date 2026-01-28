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
    from blueprints import agendamentos, clinica, loja

    clinica_bp = clinica.get_blueprint()
    if clinica_bp.name not in app.blueprints:
        _register_with_alias(app, clinica_bp)

    agendamentos_bp = agendamentos.get_blueprint()
    if agendamentos_bp.name not in app.blueprints:
        _register_with_alias(app, agendamentos_bp)

    loja_bp = loja.get_blueprint()
    if loja_bp.name not in app.blueprints:
        _register_with_alias(app, loja_bp)
