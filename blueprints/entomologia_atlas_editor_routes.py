"""Authenticated atlas editing; no Google write scopes or public data routes."""
from flask import abort, current_app, jsonify, request, send_file, url_for
from flask_login import current_user, login_required

def register(bp, require_access, clinical_access):
    from services import entomologia_atlas_editor as service
    from blueprints.entomologia_routes import ensure_entomologia_editor, _sem_cache
    from services.entomologia_acesso import eh_admin

    def reply(data,status=200):
        response=jsonify(data);response.status_code=status
        return _sem_cache(response)

    @bp.route('/entomologia/atlas/editor')
    @require_access
    def atlas_editor_catalog():
        return reply({'layers':service.catalog(clinical_access(),True)})

    @bp.route('/entomologia/atlas/editor/<key>')
    @require_access
    def atlas_editor_layer(key):
        layer=service.layers(clinical_access(),True).get(key)
        if not layer: abort(404)
        return reply(layer)

    @bp.route('/entomologia/atlas/editor', methods=['POST'])
    @bp.route('/entomologia/atlas/editor/<key>', methods=['POST'])
    @require_access
    @login_required
    def atlas_editor_write(key=None):
        ensure_entomologia_editor()
        if request.content_length and request.content_length>2_000_000:
            return reply({'error':'Formulário maior que 2 MB.'},413)
        try:
            # Only an identified SFA administrator can edit clinical layers.
            data=service.save(key,request.get_json(silent=True),eh_admin(current_user),
                              f'{current_user.get_id()} · {current_user.name or "Equipe"}')
        except service.Conflict as exc: return reply({'error':str(exc),'conflict':True},409)
        except PermissionError as exc: return reply({'error':str(exc)},403)
        except LookupError: return reply({'error':'Camada ou registro não encontrado.'},404)
        except ValueError as exc: return reply({'error':str(exc)},400)
        return reply(data)

    @bp.route('/entomologia/atlas/editor/<key>/historico')
    @require_access
    def atlas_editor_history(key):
        try: return reply({'revisions':service.history(key,clinical_access())})
        except LookupError: abort(404)

    @bp.route('/entomologia/atlas/busca')
    @require_access
    def atlas_place_search():
        return reply({'results':service.search(request.args.get('q',''),clinical_access())})

    @bp.route('/entomologia/atlas/documentos')
    @require_access
    def atlas_documents():
        return reply({'documents':[{**item,'url':url_for('sfa_routes.atlas_document',key=item['id'],kind='pdf',token=request.args.get('token') or None),
                                   'image_url':url_for('sfa_routes.atlas_document',key=item['id'],kind='png',token=request.args.get('token') or None)}
                                  for item in service.documents()]})

    @bp.route('/entomologia/atlas/documentos/<key>.<kind>')
    @require_access
    def atlas_document(key,kind):
        if kind not in ('pdf','png') or key not in {x['id'] for x in service.documents()}: abort(404)
        response=send_file(service.DATA/(key+'.'+kind),mimetype='application/pdf' if kind=='pdf' else 'image/png',conditional=True)
        response.headers['X-Content-Type-Options']='nosniff'
        return _sem_cache(response)
