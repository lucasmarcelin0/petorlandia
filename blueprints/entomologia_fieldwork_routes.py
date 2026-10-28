"""Casa a casa: app de campo, plano dos quarteirões e visitas imóvel a imóvel.

Registradas no blueprint do SFA com o acesso da área de território. Ler o mapa
vale também para o token interno; planejar e registrar visita exigem conta
(administrador ou equipe "Combate à dengue"), para cada marcação ter autor.
"""
from __future__ import annotations

import json
from datetime import timedelta

from flask import abort, current_app, jsonify, make_response, render_template, request, url_for
from flask_login import current_user, login_required


def _sem_cache(response):
    response = current_app.make_response(response)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def _token():
    return request.args.get('token') or None


def _enviar_foto(*args, **kwargs):
    # Resolve app.upload_to_s3 na hora: é o que os testes trocam (sem falar com a AWS).
    import app as app_module
    return app_module.upload_to_s3(*args, **kwargs)


def _erro(mensagem, codigo=400):
    return _sem_cache(jsonify({'ok': False, 'erro': mensagem})), codigo


def register(bp, require_access):
    """Registra as rotas de campo no blueprint do SFA."""
    from blueprints.entomologia_routes import ensure_entomologia_admin, ensure_entomologia_editor, usuario_pode_alterar
    from services.entomologia_acesso import eh_admin

    def _auditar(funcao, mensagem, detalhes):
        from extensions import db
        from models.sfa import SfaAuditoria
        db.session.add(SfaAuditoria(nivel='INFO', categoria='ENTOMOLOGIA', funcao=funcao, mensagem=mensagem,
                                    detalhes_json=json.dumps({'ator_autenticado': str(current_user.get_id()),
                                                              **detalhes}, ensure_ascii=False, default=str)))

    def _periodo():
        from services.entomologia_casa_a_casa import _data
        from services.sfa_workflow import hoje_local
        hoje = hoje_local()
        try:
            fim = _data(request.args.get('fim'), hoje)
            inicio = _data(request.args.get('inicio'), fim)
        except ValueError:
            abort(400)
        if inicio > fim or (fim - inicio).days > 370:
            abort(400)
        return inicio, fim

    def _planilha(texto, nome):
        response = make_response('﻿' + texto)
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename={nome}'
        return _sem_cache(response)

    @bp.route('/entomologia/casa-a-casa')
    @require_access
    def casa_a_casa():
        from flask_wtf.csrf import generate_csrf
        from services import entomologia_casa_a_casa as servico

        registra = usuario_pode_alterar()
        config = {
            'urls': {
                'base': url_for('sfa_routes.casa_a_casa_base', token=_token()),
                'estado': url_for('sfa_routes.casa_a_casa_estado', token=_token()),
                'plano': url_for('sfa_routes.casa_a_casa_plano'),
                'visitas': url_for('sfa_routes.casa_a_casa_visitas'),
                'historico': url_for('sfa_routes.casa_a_casa_historico', token=_token()),
                'moradores': url_for('sfa_routes.casa_a_casa_moradores') if registra else '',
                'solicitacao': url_for('sfa_routes.casa_a_casa_solicitacao_nova') if registra else '',
                'solicitacoes': url_for('sfa_routes.casa_a_casa_solicitacoes', token=_token()),
                'visitas_csv': url_for('sfa_routes.casa_a_casa_visitas_csv', token=_token()),
                'boletim_csv': url_for('sfa_routes.casa_a_casa_boletim_csv', token=_token()),
                'recipientes_csv': url_for('sfa_routes.casa_a_casa_recipientes_csv', token=_token()),
                'relatorio': url_for('sfa_routes.casa_a_casa_relatorio', token=_token()),
                'relatorio_csv': url_for('sfa_routes.casa_a_casa_relatorio_csv', token=_token()),
                'equipe': url_for('sfa_routes.casa_a_casa_equipe'),
                'painel': url_for('sfa_routes.entomologia', token=_token()),
                'entrar': url_for('login_view', next=url_for('sfa_routes.casa_a_casa'))
                if 'login_view' in current_app.view_functions else '',
                # Mesmo endereço que templates/layout.html registra: outro endereço reinstalaria o worker.
                'sw': url_for('service_worker', v='20260812-pmo-video')
                if 'service_worker' in current_app.view_functions else '',
            },
            'usuario': ({'id': current_user.id, 'nome': servico.nome_da_conta(current_user)}
                        if registra else None),
            'registra': registra,
            'situacoes': servico.SITUACOES,
            'recipientes': servico.grupos_recipiente(),
            'atividades': servico.ATIVIDADES,
            'partes': servico.NOME_PARTE,
            'produtos_focal': servico.PRODUTOS_FOCAL,
            'categorias_solicitacao': servico.CATEGORIAS_SOLICITACAO,
            'destinos_solicitacao': list(servico.DESTINOS_SOLICITACAO),
            'equipe': servico.equipe(current_user if registra else None),
            'admin': eh_admin(current_user),
            'csrf': generate_csrf(),
        }
        return _sem_cache(render_template('sfa/casa_a_casa.html', config=config))

    @bp.route('/entomologia/casa-a-casa/base.json')
    @require_access
    def casa_a_casa_base():
        from services.entomologia_casa_a_casa import base
        dados = base()
        etag = '"cac-' + dados['versao'] + '"'
        if request.headers.get('If-None-Match') == etag:
            response = make_response('', 304)
        else:
            response = jsonify(dados)
        response.headers['ETag'] = etag
        # Revalida a cada pedido: só baixa de novo quando a malha ou os endereços mudam.
        response.headers['Cache-Control'] = 'private, no-cache'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @bp.route('/entomologia/casa-a-casa/estado')
    @require_access
    def casa_a_casa_estado():
        from flask_wtf.csrf import generate_csrf
        from services import entomologia_casa_a_casa as servico
        from services.sfa_workflow import hoje_local

        dados = servico.estado(hoje_local(), max(0, request.args.get('desde', 0, type=int) or 0))
        dados.update(versao_base=servico.base()['versao'], registra=usuario_pode_alterar(), csrf=generate_csrf())
        return _sem_cache(jsonify(dados))

    @bp.route('/entomologia/casa-a-casa/plano', methods=['POST'])
    @require_access
    @login_required
    def casa_a_casa_plano():
        """Escritório: planejar, dividir em L, tirar do plano, concluir ou reabrir quarteirões."""
        ensure_entomologia_editor()
        from extensions import db
        from models import User
        from services import entomologia_casa_a_casa as servico
        from services.sfa_workflow import hoje_local

        pedido = request.get_json(silent=True) or {}
        acao, blocos, hoje = str(pedido.get('acao') or ''), pedido.get('blocos'), hoje_local()
        try:
            dia = servico._data(pedido.get('data'), hoje)
            origem = servico._data(pedido.get('origem'), hoje)
            if 'esperado' in pedido and acao in ('planejar', 'remover', 'reagendar', 'dividir', 'unir'):
                servico.conferir_plano(blocos, origem if acao == 'reagendar' else dia, pedido['esperado'])

            def pessoa(responsavel_id):
                if not responsavel_id:
                    return None
                if responsavel_id not in {p['id'] for p in servico.equipe(current_user)}:
                    raise ValueError('Essa pessoa não faz parte da equipe.')
                return db.session.get(User, responsavel_id)

            if acao in ('planejar', 'reagendar'):
                responsavel = pessoa(pedido.get('responsavel_id'))
                if acao == 'reagendar':
                    feitos = servico.reagendar(blocos, origem, dia, hoje, responsavel)
                else:
                    feitos = servico.planejar(blocos, dia, hoje, responsavel, servico.nome_da_conta(current_user),
                                              pedido.get('atividade'))
            elif acao in ('dividir', 'unir'):
                if not isinstance(blocos, list) or len(blocos) != 1:
                    raise ValueError('Divida um quarteirão por vez.')
                if acao == 'dividir':
                    divisao = pedido.get('divisao')
                    if not isinstance(divisao, list) or any(not isinstance(p, dict) for p in divisao):
                        raise ValueError('Divisão inválida.')
                    feitos = servico.dividir(blocos[0], dia, hoje,
                                             [(str(p.get('parte') or '').upper(), pessoa(p.get('responsavel_id')))
                                              for p in divisao], servico.nome_da_conta(current_user), pedido.get('atividade'))
                else:
                    feitos = servico.unir(blocos[0], dia, pessoa(pedido.get('responsavel_id')))
            elif acao == 'remover':
                feitos = servico.desplanejar(blocos, dia)
            elif acao == 'concluir':
                feitos = servico.concluir(blocos, hoje, current_user)
            elif acao == 'reabrir':
                feitos = servico.reabrir(blocos, hoje)
            else:
                raise ValueError('Ação desconhecida.')
        except servico.ConflitoPlano as exc:
            db.session.rollback()
            return _erro(str(exc), 409)
        except ValueError as exc:
            db.session.rollback()
            return _erro(str(exc))
        if feitos:
            from sqlalchemy.exc import IntegrityError
            try:
                _auditar('casa_a_casa_' + acao, f'Casa a casa: {acao} em {feitos} quarteirão(ões)',
                         {'data': dia, 'origem': origem if acao == 'reagendar' else None,
                          'blocos': [str(b) for b in (blocos or [])][:60]})
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return _erro('O plano mudou em outro aparelho. Confira a agenda atualizada e aplique novamente.', 409)
        return _sem_cache(jsonify({'ok': True, 'feitos': feitos, **servico.estado(hoje)}))

    @bp.route('/entomologia/casa-a-casa/visitas', methods=['POST'])
    @require_access
    @login_required
    def casa_a_casa_visitas():
        """Rua: recebe as visitas do aparelho (na hora ou guardadas enquanto faltou internet)."""
        ensure_entomologia_editor()
        from extensions import db
        from services import entomologia_casa_a_casa as servico
        from services.sfa_workflow import hoje_local

        if request.content_length and request.content_length > 600_000:
            abort(413)
        pedido = request.get_json(silent=True) or {}
        try:
            resultado = servico.registrar_visitas(pedido.get('visitas'), current_user, hoje_local())
        except ValueError as exc:
            db.session.rollback()
            return _erro(str(exc))
        db.session.commit()
        if resultado.pop('imoveis_novos', 0):
            # Imóvel acrescentado em campo entra na base: os aparelhos baixam a nova versão.
            servico.esquecer_base()
        return _sem_cache(jsonify({'ok': True, **resultado}))

    @bp.route('/entomologia/casa-a-casa/historico')
    @require_access
    def casa_a_casa_historico():
        from services.entomologia_casa_a_casa import historico
        imovel = (request.args.get('imovel') or '').strip()
        if not imovel or len(imovel) > 80:
            abort(400)
        return _sem_cache(jsonify(historico(imovel)))

    @bp.route('/entomologia/casa-a-casa/moradores')
    @require_access
    @login_required
    def casa_a_casa_moradores():
        """Moradores e telefones do imóvel: dado pessoal, só para a equipe logada."""
        ensure_entomologia_editor()
        from services.entomologia_casa_a_casa import moradores
        imovel = (request.args.get('imovel') or '').strip()
        if not imovel or len(imovel) > 80:
            abort(400)
        return _sem_cache(jsonify({'imovel': imovel, 'moradores': moradores(imovel)}))

    @bp.route('/entomologia/casa-a-casa/solicitacoes', methods=['POST'])
    @require_access
    @login_required
    def casa_a_casa_solicitacao_nova():
        """Rua: solicitação com foto, data e coordenadas (na hora ou guardada sem internet)."""
        ensure_entomologia_editor()
        import uuid as uuid_mod

        from werkzeug.utils import secure_filename

        from extensions import db
        from services import entomologia_casa_a_casa as servico

        if request.content_length and request.content_length > 9 * 1024 * 1024:
            return _erro('A foto é muito grande. Use uma imagem de até 8 MB.', 413)
        try:
            item = json.loads(request.form.get('dados') or '{}')
        except ValueError:
            return _erro('Solicitação em formato inválido.')
        existente = servico.solicitacao_existente(item.get('uuid') if isinstance(item, dict) else '')
        if existente is not None:
            # Reenvio do aparelho: já está gravada, não sobe a foto de novo.
            return _sem_cache(jsonify({'ok': True, 'nova': False, 'solicitacao': servico.solicitacao_dict(existente)}))
        try:
            dados = servico.validar_solicitacao(item, servico.indice()['blocos'])
        except ValueError as exc:
            return _erro(str(exc))

        foto_url = None
        arquivo = request.files.get('foto')
        if arquivo is not None:
            from services.photo_intake import PhotoIntakeError, normalize_photo_upload, normalized_filename
            from services.photo_storage import PhotoStorageError, store_photo
            conteudo = arquivo.stream.read()
            if not conteudo:
                return _erro('A foto chegou vazia. Tire a foto de novo.')
            if len(conteudo) > 8 * 1024 * 1024:
                return _erro('A foto é muito grande. Use uma imagem de até 8 MB.', 413)
            try:
                foto = normalize_photo_upload(conteudo)
            except PhotoIntakeError as exc:
                return _erro(exc.user_message, exc.status_code)
            nome = f"{uuid_mod.uuid4().hex}_{secure_filename(normalized_filename(arquivo.filename or 'foto', foto))}"
            try:
                foto_url = store_photo(foto.stream, nome, folder='entomologia/solicitacoes', uploader=_enviar_foto)
            except PhotoStorageError as exc:
                current_app.logger.error('Foto da solicitação não guardada (code=%s): %s', exc.code,
                                         exc.detail or exc.user_message)
                # 502: o aparelho mantém a solicitação e a foto e tenta de novo depois.
                return _sem_cache(jsonify({'ok': False, 'erro': exc.user_message, 'repetir': True})), 502

        solicitacao, nova = servico.registrar_solicitacao(dados, foto_url, current_user)
        db.session.commit()
        return _sem_cache(jsonify({'ok': True, 'nova': nova, 'solicitacao': servico.solicitacao_dict(solicitacao)}))

    @bp.route('/entomologia/casa-a-casa/solicitacoes')
    @require_access
    def casa_a_casa_solicitacoes():
        """Escritório: solicitações vindas do campo, com foto, mapa e o ofício para imprimir."""
        from flask_wtf.csrf import generate_csrf
        from services import entomologia_casa_a_casa as servico

        status = (request.args.get('status') or '').upper()
        return _sem_cache(render_template(
            'sfa/casa_a_casa_solicitacoes.html', solicitacoes=servico.solicitacoes(status or None),
            status=status, nomes_status=servico.STATUS_SOLICITACAO, destinos=servico.DESTINOS_SOLICITACAO,
            edita=usuario_pode_alterar(), csrf=generate_csrf(), token=_token(),
            voltar=url_for('sfa_routes.casa_a_casa', token=_token())))

    @bp.route('/entomologia/casa-a-casa/solicitacoes/<int:solicitacao_id>', methods=['POST'])
    @require_access
    @login_required
    def casa_a_casa_solicitacao_atualizar(solicitacao_id):
        ensure_entomologia_editor()
        from flask import redirect
        from extensions import db
        from services import entomologia_casa_a_casa as servico

        dados = request.get_json(silent=True) if request.is_json else request.form
        try:
            resultado = servico.atualizar_solicitacao(solicitacao_id, dados or {}, current_user)
        except LookupError:
            abort(404)
        except ValueError as exc:
            db.session.rollback()
            return _erro(str(exc))
        db.session.commit()
        if request.is_json:
            return _sem_cache(jsonify({'ok': True, 'solicitacao': resultado}))
        return redirect(url_for('sfa_routes.casa_a_casa_solicitacoes', status=request.args.get('status') or None)
                        + f'#solicitacao-{solicitacao_id}')

    @bp.route('/entomologia/casa-a-casa/solicitacoes/<int:solicitacao_id>/oficio')
    @require_access
    def casa_a_casa_solicitacao_oficio(solicitacao_id):
        """Ofício pronto para imprimir: texto editável na tela, foto, endereço e coordenadas."""
        from extensions import db
        from models.entomologia import EntomologiaSolicitacao
        from services import entomologia_casa_a_casa as servico
        from services.sfa_workflow import hoje_local

        solicitacao = db.session.get(EntomologiaSolicitacao, solicitacao_id)
        if solicitacao is None:
            abort(404)
        hoje = hoje_local()
        return _sem_cache(render_template('sfa/casa_a_casa_oficio.html', s=servico.solicitacao_dict(solicitacao),
                                          hoje=hoje, data_extenso=servico.data_por_extenso(hoje), voltar=url_for('sfa_routes.casa_a_casa_solicitacoes',
                                                                            token=_token())))

    @bp.route('/entomologia/casa-a-casa/visitas.csv')
    @require_access
    def casa_a_casa_visitas_csv():
        from services.entomologia_casa_a_casa import visitas_csv
        inicio, fim = _periodo()
        return _planilha(visitas_csv(inicio, fim), f'casa_a_casa_visitas_{inicio}_{fim}.csv')

    @bp.route('/entomologia/casa-a-casa/boletim.csv')
    @require_access
    def casa_a_casa_boletim_csv():
        from services.entomologia_casa_a_casa import boletim_csv
        inicio, fim = _periodo()
        return _planilha(boletim_csv(inicio, fim), f'casa_a_casa_boletim_{inicio}_{fim}.csv')

    @bp.route('/entomologia/casa-a-casa/recipientes.csv')
    @require_access
    def casa_a_casa_recipientes_csv():
        from services.entomologia_casa_a_casa import recipientes_csv
        inicio, fim = _periodo()
        return _planilha(recipientes_csv(inicio, fim), f'casa_a_casa_recipientes_{inicio}_{fim}.csv')

    @bp.route('/entomologia/casa-a-casa/relatorio.json')
    @require_access
    def casa_a_casa_relatorio():
        from services.entomologia_casa_a_casa import relatorio
        inicio, fim = _periodo()
        if (fim - inicio).days > 62:
            abort(400)
        return _sem_cache(jsonify(relatorio(inicio, fim)))

    @bp.route('/entomologia/casa-a-casa/relatorio.csv')
    @require_access
    def casa_a_casa_relatorio_csv():
        from services.entomologia_casa_a_casa import relatorio_csv
        inicio, fim = _periodo()
        return _planilha(relatorio_csv(inicio, fim), f'casa_a_casa_relatorio_{inicio}_{fim}.csv')

    @bp.route('/entomologia/casa-a-casa/equipe', methods=['POST'])
    @require_access
    @login_required
    def casa_a_casa_equipe():
        """Escritório: o administrador inclui um novo trabalhador pelo e-mail da conta."""
        ensure_entomologia_admin()
        from extensions import db
        from services import entomologia_acesso as acesso
        from services import entomologia_casa_a_casa as servico

        pedido = request.get_json(silent=True) or {}
        try:
            user = acesso.buscar_conta(pedido.get('email'))
        except ValueError as exc:
            return _erro(str(exc))
        _vinculo, criado = acesso.conceder(user, servico.nome_da_conta(current_user) or str(current_user.get_id()))
        if criado:
            _auditar('casa_a_casa_trabalhador', 'Casa a casa: trabalhador incluído na equipe',
                     {'user_id': user.id})
        db.session.commit()
        return _sem_cache(jsonify({'ok': True, 'criado': criado, 'id': user.id,
                                   'equipe': servico.equipe(current_user)}))
