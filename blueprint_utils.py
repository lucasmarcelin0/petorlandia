from blueprints import agendamentos, clinica, loja


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
    if "clinica_routes" not in app.blueprints:
        _register_with_alias(app, clinica.bp)
    if "agendamentos_routes" not in app.blueprints:
        _register_with_alias(app, agendamentos.bp)
    if "loja_routes" not in app.blueprints:
        _register_with_alias(app, loja.bp)
