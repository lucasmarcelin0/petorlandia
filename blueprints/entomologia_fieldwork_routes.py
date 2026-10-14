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


def _erro(mensagem, codigo=400):
    return _sem_cache(jsonify({'ok': False, 'erro': mensagem})), codigo


def register(bp, require_access):
    """Registra as rotas de campo no blueprint do SFA."""
    from blueprints.entomologia_routes import ensure_entomologia_editor, usuario_pode_alterar

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
                'visitas_csv': url_for('sfa_routes.casa_a_casa_visitas_csv', token=_token()),
                'boletim_csv': url_for('sfa_routes.casa_a_casa_boletim_csv', token=_token()),
                'recipientes_csv': url_for('sfa_routes.casa_a_casa_recipientes_csv', token=_token()),
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
            'equipe': servico.equipe(current_user if registra else None),
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
        """Escritório: planejar, tirar do plano, concluir ou reabrir quarteirões."""
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
            if 'esperado' in pedido and acao in ('planejar', 'remover', 'reagendar'):
                servico.conferir_plano(blocos, origem if acao == 'reagendar' else dia, pedido['esperado'])
            if acao in ('planejar', 'reagendar'):
                responsavel = None
                if pedido.get('responsavel_id'):
                    permitidos = {pessoa['id'] for pessoa in servico.equipe(current_user)}
                    if pedido['responsavel_id'] not in permitidos:
                        raise ValueError('Essa pessoa não faz parte da equipe.')
                    responsavel = db.session.get(User, pedido['responsavel_id'])
                if acao == 'reagendar':
                    feitos = servico.reagendar(blocos, origem, dia, hoje, responsavel)
                else:
                    feitos = servico.planejar(blocos, dia, hoje, responsavel, servico.nome_da_conta(current_user))
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
        return _sem_cache(jsonify({'ok': True, **resultado}))

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
