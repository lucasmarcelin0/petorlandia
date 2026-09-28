"""Atualização da base entomológica pela equipe e boletim público aprovado.

Registradas no blueprint do SFA, com a mesma autorização interna. Nenhuma
rota daqui grava a fotografia versionada em disco.
"""
import json
from collections import Counter
from datetime import date, datetime

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required


def _ator():
    if current_user.is_authenticated:
        return str(current_user.get_id())
    return 'acesso interno por token/configuração'


def usuario_pode_alterar():
    return bool(current_user.is_authenticated and (getattr(current_user, 'role', '') or '').lower() == 'admin')


def ensure_entomologia_admin():
    """Alterar a base ou a página pública exige administrador identificado.

    O token interno do SFA continua dando acesso de leitura ao painel; gravações
    ficam atribuídas a uma conta real na auditoria.
    """
    if not usuario_pode_alterar():
        abort(403)


def _responsavel():
    valor = str(request.form.get('responsavel') or '').strip()
    if not valor or len(valor) > 160:
        raise ValueError('Informe o responsável pelo envio (até 160 caracteres).')
    return valor


def _auditar(funcao, mensagem, detalhes):
    from extensions import db
    from models.sfa import SfaAuditoria
    db.session.add(SfaAuditoria(nivel='INFO', categoria='ENTOMOLOGIA', funcao=funcao, mensagem=mensagem,
                                detalhes_json=json.dumps({'ator_autenticado': _ator(), **detalhes},
                                                         ensure_ascii=False, default=str)))


def _sem_cache(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def acoes_territoriais():
    """Ações com setor, sem vínculo pessoal, para o planejamento e a aba Equipe."""
    from models.sfa import SfaAcao
    from services.entomologia_service import consultar_sem_interromper

    def dia(valor):
        return valor.date().isoformat() if isinstance(valor, datetime) else (valor.isoformat() if valor else None)
    rows = consultar_sem_interromper(lambda: SfaAcao.query.filter(
        SfaAcao.setor.isnot(None), SfaAcao.setor != '').order_by(SfaAcao.id).all(), [])
    return [{'id': a.id, 'sector': a.setor, 'tipo': a.tipo, 'status': a.status, 'prazo': dia(a.prazo),
             'criado_em': dia(a.criado_em), 'executado_em': dia(a.executado_em),
             'verificado_em': dia(a.verificado_em)} for a in rows]


def publicacao_vigente():
    from models.entomologia import EntomologiaPublicacao
    from services.entomologia_service import consultar_sem_interromper
    return consultar_sem_interromper(lambda: EntomologiaPublicacao.query.filter_by(status='PUBLICADA')
                                     .order_by(EntomologiaPublicacao.id.desc()).first())


def url_publica():
    """Link da página pública, ausente quando o blueprint público não está registrado."""
    from werkzeug.routing import BuildError
    try:
        return url_for('vigilancia_publica.painel_aedes_publico')
    except BuildError:
        return None


def register(bp, require_access):
    @bp.context_processor
    def _inject_entomologia_url_publica():
        return {'entomologia_url_publica': url_publica}

    @bp.route('/entomologia/atualizar')
    @require_access
    def entomologia_atualizar():
        from models.entomologia import EntomologiaImportacao, EntomologiaPublicacao
        from services.entomologia_service import dataset_atual
        from services.sfa_workflow import hoje_local

        previa = None
        previa_id = request.args.get('previa', type=int)
        if previa_id:
            previa = EntomologiaImportacao.query.filter_by(id=previa_id, status='PREVIA').first()
        envios = EntomologiaImportacao.query.filter(EntomologiaImportacao.status != 'PREVIA') \
            .order_by(EntomologiaImportacao.id.desc()).limit(60).all()
        publicacoes = EntomologiaPublicacao.query.order_by(EntomologiaPublicacao.id.desc()).limit(12).all()
        dataset = dataset_atual()
        return _sem_cache(current_app.make_response(render_template(
            'sfa/entomologia_atualizar.html', previa=previa,
            previa_resumo=json.loads(previa.resumo_json or '{}') if previa else None,
            envios=envios, publicacoes=publicacoes, fonte=dataset['source'],
            hoje=hoje_local(), token=request.args.get('token') or None, pode_alterar=usuario_pode_alterar(),
        )))

    @bp.route('/entomologia/atualizar', methods=['POST'])
    @require_access
    @login_required
    def entomologia_enviar():
        ensure_entomologia_admin()
        from extensions import db
        from models.entomologia import EntomologiaImportacao
        from services import entomologia_service as service
        from services.sfa_workflow import hoje_local
        from time_utils import utcnow

        tipo = request.form.get('tipo', service.TIPO_VISITAS)
        arquivo = request.files.get('arquivo')
        try:
            if tipo not in (service.TIPO_VISITAS, service.TIPO_CAMADA):
                raise ValueError('Tipo de arquivo inválido.')
            if not arquivo or not arquivo.filename:
                raise ValueError('Escolha um arquivo para enviar.')
            responsavel = _responsavel()
            nome = arquivo.filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1][:200]
            blob = arquivo.stream.read(service.LIMITE_ENVIO + 1)
            # Prévias esquecidas não se acumulam no banco.
            limite = utcnow() - service.PREVIA_VALIDADE
            EntomologiaImportacao.query.filter(EntomologiaImportacao.status == 'PREVIA',
                                               EntomologiaImportacao.criado_em < limite).delete()
            if tipo == service.TIPO_VISITAS:
                lido = service.ler_visitas(blob, nome)
                resumo = service.previa_visitas(lido['rows'], service.dataset_atual(), hoje_local())
                resumo['repetidas'] = lido['repetidas']
                registro = EntomologiaImportacao(
                    tipo=tipo, nome_arquivo=nome, titulo=lido['arquivo'][:200], sha256=lido['sha256'],
                    inicio=date.fromisoformat(resumo['inicio']), fim=date.fromisoformat(resumo['fim']),
                    linhas=resumo['linhas'], dados_json=json.dumps(lido['rows'], ensure_ascii=False,
                                                                   separators=(',', ':'), allow_nan=False),
                    resumo_json=json.dumps(resumo, ensure_ascii=False))
            else:
                lido = service.ler_camada(blob, nome)
                titulo = str(request.form.get('titulo') or '').strip()[:200] or lido['titulo'] or nome
                features = lido['geojson']['features']
                resumo = {'elementos': len(features), 'pastas': lido['pastas'][:50],
                          'tipos': dict(sorted(Counter(f['geometry']['type'] for f in features).items()))}
                registro = EntomologiaImportacao(
                    tipo=tipo, nome_arquivo=nome, titulo=titulo, sha256=lido['sha256'],
                    linhas=resumo['elementos'], dados_json=json.dumps(lido['geojson'], ensure_ascii=False,
                                                                      separators=(',', ':'), allow_nan=False),
                    resumo_json=json.dumps(resumo, ensure_ascii=False))
            repetido = EntomologiaImportacao.query.filter_by(sha256=registro.sha256, status='ATIVA').first()
            if repetido:
                raise ValueError(f'Este conteúdo já está em uso (envio #{repetido.id}). Nada foi alterado.')
            registro.responsavel, registro.ator, registro.status = responsavel, _ator(), 'PREVIA'
            db.session.add(registro)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None))
        return redirect(url_for('sfa_routes.entomologia_atualizar', previa=registro.id,
                                token=request.args.get('token') or None) + '#previa')

    @bp.route('/entomologia/envios/<int:envio_id>/confirmar', methods=['POST'])
    @require_access
    @login_required
    def entomologia_confirmar(envio_id):
        ensure_entomologia_admin()
        from extensions import db
        from models.entomologia import EntomologiaImportacao
        from time_utils import utcnow

        registro = db.session.get(EntomologiaImportacao, envio_id)
        if not registro or registro.status != 'PREVIA':
            abort(404)
        try:
            responsavel = _responsavel()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('sfa_routes.entomologia_atualizar', previa=envio_id,
                                    token=request.args.get('token') or None) + '#previa')
        registro.status, registro.confirmado_em = 'ATIVA', utcnow()
        _auditar('confirmar_envio', f'Envio #{registro.id} ({registro.tipo}) confirmado por {responsavel}',
                 {'envio': registro.id, 'tipo': registro.tipo, 'arquivo': registro.nome_arquivo,
                  'sha256': registro.sha256, 'inicio': registro.inicio, 'fim': registro.fim,
                  'linhas': registro.linhas, 'responsavel_envio': registro.responsavel,
                  'responsavel_confirmacao': responsavel})
        db.session.commit()
        if registro.tipo == 'visitas':
            flash(f'Base atualizada: {registro.linhas} registros de {registro.inicio:%d/%m/%Y} a {registro.fim:%d/%m/%Y}. '
                  'Os painéis já usam os novos dados.', 'success')
        else:
            flash(f'Camada “{registro.titulo}” disponível no mapa da aba Entomologia.', 'success')
        return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None))

    @bp.route('/entomologia/envios/<int:envio_id>/desfazer', methods=['POST'])
    @require_access
    @login_required
    def entomologia_desfazer(envio_id):
        ensure_entomologia_admin()
        from extensions import db
        from models.entomologia import EntomologiaImportacao
        from time_utils import utcnow

        registro = db.session.get(EntomologiaImportacao, envio_id)
        if not registro or registro.status not in ('PREVIA', 'ATIVA'):
            abort(404)
        if registro.status == 'PREVIA':
            db.session.delete(registro)
            db.session.commit()
            flash('Prévia descartada. Nada foi alterado na base.', 'info')
        else:
            try:
                responsavel = _responsavel()
            except ValueError as exc:
                flash(str(exc), 'danger')
                return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None))
            registro.status, registro.desfeito_em, registro.desfeito_por = 'DESFEITA', utcnow(), responsavel
            _auditar('desfazer_envio', f'Envio #{registro.id} desfeito por {responsavel}',
                     {'envio': registro.id, 'tipo': registro.tipo, 'arquivo': registro.nome_arquivo})
            db.session.commit()
            flash(f'Envio #{registro.id} desfeito. Os dias voltaram à versão anterior.', 'info')
        return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None))

    @bp.route('/entomologia/boletim/previa')
    @require_access
    def entomologia_boletim_previa():
        from services.entomologia_service import boletim_publico, dataset_atual, malha_publica
        dias = request.args.get('dias', 28, type=int)
        try:
            boletim = boletim_publico(dataset_atual(), dias=dias)
        except ValueError:
            abort(400)
        return _sem_cache(current_app.make_response(render_template(
            'vigilancia/aedes.html', boletim=boletim, publicacao=None, previa=True,
            census=malha_publica())))

    @bp.route('/entomologia/publicar', methods=['POST'])
    @require_access
    @login_required
    def entomologia_publicar():
        ensure_entomologia_admin()
        from extensions import db
        from models.entomologia import EntomologiaPublicacao
        from services.entomologia_service import boletim_publico, dataset_atual

        try:
            responsavel = _responsavel()
            dias = int(request.form.get('dias') or 28)
            texto = lambda campo, limite: str(request.form.get(campo) or '').strip()[:limite] or None
            boletim = boletim_publico(dataset_atual(), dias=dias)
        except ValueError as exc:
            flash(str(exc) or 'Não foi possível montar o boletim.', 'danger')
            return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None))
        for anterior in EntomologiaPublicacao.query.filter_by(status='PUBLICADA').all():
            anterior.status = 'SUBSTITUIDA'
        publicacao = EntomologiaPublicacao(
            inicio=date.fromisoformat(boletim['inicio']), fim=date.fromisoformat(boletim['fim']),
            dados_json=json.dumps(boletim, ensure_ascii=False), mensagem=texto('mensagem', 1200),
            contato=texto('contato', 300), assinatura=texto('assinatura', 200),
            responsavel=responsavel, ator=_ator(), status='PUBLICADA')
        db.session.add(publicacao)
        _auditar('publicar_boletim', f'Boletim público {boletim["inicio"]} a {boletim["fim"]} publicado por {responsavel}',
                 {'inicio': boletim['inicio'], 'fim': boletim['fim'], 'totais': boletim['totais']})
        db.session.commit()
        flash('Boletim publicado. A página pública já mostra os novos números.', 'success')
        return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None) + '#publicar')

    @bp.route('/entomologia/publicacoes/<int:publicacao_id>/retirar', methods=['POST'])
    @require_access
    @login_required
    def entomologia_retirar(publicacao_id):
        ensure_entomologia_admin()
        from extensions import db
        from models.entomologia import EntomologiaPublicacao
        from time_utils import utcnow

        publicacao = db.session.get(EntomologiaPublicacao, publicacao_id)
        if not publicacao or publicacao.status != 'PUBLICADA':
            abort(404)
        try:
            responsavel = _responsavel()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None) + '#publicar')
        publicacao.status, publicacao.retirado_em, publicacao.retirado_por = 'RETIRADA', utcnow(), responsavel
        _auditar('retirar_boletim', f'Boletim #{publicacao.id} retirado por {responsavel}', {'publicacao': publicacao.id})
        db.session.commit()
        flash('Boletim retirado da página pública.', 'info')
        return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None) + '#publicar')
