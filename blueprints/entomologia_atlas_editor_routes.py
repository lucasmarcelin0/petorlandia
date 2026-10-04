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

    @bp.after_request
    def atlas_dados_mudaram(response):
        """Edição, importação ou desfazer no atlas: a versão nova do índice começa a ser montada já, em segundo plano.

        Enquanto isso a anterior continua servindo a busca; a próxima abertura do atlas recebe a nova.
        """
        if request.method=='POST' and 200<=response.status_code<300 and '/entomologia/' in request.path:
            from services import entomologia_atlas_artefatos as artefatos
            try:
                if artefatos.ativo():artefatos.atualizar_em_segundo_plano(current_app._get_current_object())
            except Exception:
                current_app.logger.warning('Pré-cálculo do atlas não iniciou após a alteração.',exc_info=True)
        return response

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

    @bp.route('/entomologia/atlas/editor/<key>/conferencia',methods=['GET','POST'])
    @require_access
    def atlas_editor_spatial_review(key):
        from services.entomologia_georeference import review,assess
        from services.entomologia_folders import validate_feature_folder
        available=service.layers(clinical_access());layer=available.get(key)
        if not layer:abort(404)
        houses=[f for item in available.values() if item['origin']['type']=='condominium' for f in item['features']]
        try:
            if request.method=='POST':
                if request.content_length and request.content_length>32_000:return reply({'error':'Registro maior que 32 KB.'},413)
                command=request.get_json(silent=True)
                if not isinstance(command,dict):raise ValueError('Registro inválido.')
                previous=next((f for f in layer['features'] if str(f['id'])==str(command.get('feature_id',''))),None)
                if command.get('feature_id') and not previous:raise LookupError('Registro não encontrado.')
                feature=service.clean_feature(command.get('feature'),previous)
                validate_feature_folder(feature,layer)
                return reply({'records':[assess(feature,houses)]})
            return reply(review(layer,request.args.get('feature_id'),houses))
        except LookupError:abort(404)
        except ValueError as exc:return reply({'error':str(exc)},400)

    @bp.route('/entomologia/atlas/croquis/<code>')
    @require_access
    def atlas_cadastre_drawing(code):
        from services.entomologia_cadastre import drawing
        import re
        if not re.fullmatch(r'S[0-9]{1,4}Q[0-9]{1,4}',code.upper()):abort(404)
        data=drawing(code)
        if not data:abort(404)
        return reply(data)

    @bp.route('/entomologia/atlas/enderecos')
    @require_access
    def atlas_cnefe_layers():
        from services import entomologia_atlas_artefatos as artefatos
        pronto=artefatos.enderecos(bool(clinical_access()))
        if pronto is not None:return _sem_cache(artefatos.resposta(pronto))
        return reply({'layers':[{'id':layer['id'],'features':layer['features']} for layer in service.layers(clinical_access()).values() if layer['origin']['type']=='cnefe']})

    @bp.route('/entomologia/atlas/busca')
    @require_access
    def atlas_place_search():
        if request.args.get('compacto')=='1':
            # Reserva do navegador enquanto o índice não chega: mesma busca, sobre o índice já pronto.
            from services import entomologia_atlas_artefatos as artefatos
            found=artefatos.busca_compacta(request.args.get('q',''),bool(clinical_access()),current_app._get_current_object())
            if found is not None:return reply(found)
        return reply({'results':service.search(request.args.get('q',''),clinical_access())})

    @bp.route('/entomologia/atlas/busca/indice')
    @require_access
    def atlas_search_index():
        """Índice compacto: o navegador filtra sozinho, a cada tecla, sem ir ao servidor."""
        from services import entomologia_atlas_artefatos as artefatos
        from services import entomologia_atlas_search as search_service
        clinical=bool(clinical_access())
        # Pronto no banco (já em gzip): nada é montado durante a requisição. Sem versão gravada ainda, o caminho
        # anterior monta e serve, e a cópia gravada fica para as próximas.
        pronto=artefatos.indice(clinical,current_app._get_current_object())
        if pronto==artefatos.PREPARANDO:
            # Versão nova sendo montada em segundo plano: responde já (o navegador tenta de novo), sem
            # prender uma das poucas threads do site esperando a montagem.
            response=_sem_cache(jsonify({'error':'Preparando a busca de endereços.','preparando':True}))
            response.status_code=503
            response.headers['Retry-After']='5'
            return response
        if pronto is not None:
            gz,etag,br=pronto
            body=None
        else:
            body,etag=search_service.client_index(clinical)
            gz=br=None
        if etag and not clinical:
            # Só dados não clínicos podem ser revalidados pelo navegador. Com acesso
            # clínico a regra do atlas continua valendo: nada fica guardado.
            value=etag+'-0'
            tag='"'+value+'"'
            if request.if_none_match.contains(value):
                response=current_app.response_class(status=304)
            else:
                response=_corpo_json(gz,body,br)
            response.headers['ETag']=tag
            # `private` + `max-age` é a exceção que o filtro global de respostas
            # autenticadas respeita (senão tudo vira no-store); max-age=0 obriga a revalidar.
            response.headers['Cache-Control']='private, max-age=0, must-revalidate'
            response.headers['Referrer-Policy']='no-referrer'
            return response
        return _sem_cache(_corpo_json(gz,body,br))

    def _corpo_json(gz,body,br=None):
        """Resposta JSON a partir do brotli/gzip pronto (sem recomprimir) ou do texto montado na hora."""
        if gz is None:
            return current_app.response_class(body,mimetype='application/json')
        from services.entomologia_atlas_artefatos import resposta
        return resposta((gz,None,br))

    @bp.route('/entomologia/atlas/busca/lugar')
    @require_access
    def atlas_search_place():
        """Feição completa (com a geometria) de uma entrada do índice."""
        from services import entomologia_atlas_artefatos as artefatos
        from services import entomologia_atlas_search as search_service
        layer,feature,clinical=request.args.get('layer',''),request.args.get('feature',''),bool(clinical_access())
        item=artefatos.lugar(layer,feature,clinical)
        if item is False:abort(404)
        if item==artefatos.PREPARANDO:
            response=reply({'error':'Preparando.','preparando':True},503)
            response.headers['Retry-After']='5'
            return response
        if item is None:item=search_service.place(layer,feature,clinical)
        if not item:abort(404)
        return reply(item)

    @bp.route('/entomologia/atlas/malha')
    @require_access
    def atlas_street_network():
        """Malha de ruas (OpenStreetMap) para o navegador traçar rotas sem serviço externo."""
        from services import entomologia_atlas_malha
        body,etag=entomologia_atlas_malha.street_network()
        if request.if_none_match.contains(etag):
            response=current_app.response_class(status=304)
        else:
            response=current_app.response_class(body,mimetype='application/json')
        response.headers['ETag']='"'+etag+'"'
        # Dado público de referência: só muda com uma nova publicação. `private` + `max-age`
        # é a exceção que o filtro global de respostas autenticadas respeita.
        response.headers['Cache-Control']='private, max-age=3600'
        response.headers['Referrer-Policy']='no-referrer'
        return response

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
