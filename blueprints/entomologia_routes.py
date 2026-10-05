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
    from flask import has_request_context
    if not has_request_context():
        return 'tarefa agendada, sem sessão'
    if current_user.is_authenticated:
        return str(current_user.get_id())
    return 'acesso interno por token/configuração'


def usuario_pode_alterar():
    """Administrador ou membro da equipe "Combate à dengue", com conta logada."""
    from services.entomologia_acesso import pode_acessar
    return pode_acessar(current_user)


def ensure_entomologia_editor():
    """Alterar a base ou a página pública exige uma conta identificada.

    O token interno do SFA continua dando acesso de leitura ao painel; gravações
    ficam atribuídas a uma pessoa real na auditoria.
    """
    if not usuario_pode_alterar():
        abort(403)


def ensure_entomologia_admin():
    """Conceder ou revogar o papel "Combate à dengue" é tarefa de administrador."""
    from services.entomologia_acesso import eh_admin
    if not eh_admin(current_user):
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


def _dia(valor):
    return valor.date().isoformat() if isinstance(valor, datetime) else (valor.isoformat() if valor else None)


def _eh_territorial(acao):
    return not acao.id_estudo and not acao.evento_id and bool(acao.setor)


def acoes_territoriais(completo=True):
    """Ações com setor para o planejamento e a aba Equipe.

    Sem acesso completo ao SFA (equipe de combate à dengue), só entram ações
    puramente territoriais: nada vinculado a episódio ou evento de pacientes.
    """
    from models.sfa import SfaAcao
    from services.entomologia_service import consultar_sem_interromper

    rows = consultar_sem_interromper(lambda: SfaAcao.query.filter(
        SfaAcao.setor.isnot(None), SfaAcao.setor != '').order_by(SfaAcao.id).all(), [])
    if not completo:
        rows = [a for a in rows if _eh_territorial(a)]
    return [{'id': a.id, 'sector': a.setor, 'tipo': a.tipo, 'status': a.status, 'prazo': _dia(a.prazo),
             'criado_em': _dia(a.criado_em), 'executado_em': _dia(a.executado_em),
             'verificado_em': _dia(a.verificado_em), 'motivo': a.motivo, 'responsavel': a.responsavel,
             'resultado': a.resultado, 'territorial': _eh_territorial(a)} for a in rows]


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
        envios = EntomologiaImportacao.query.filter(EntomologiaImportacao.status != 'PREVIA', EntomologiaImportacao.tipo != 'atlas_edit') \
            .order_by(EntomologiaImportacao.id.desc()).limit(60).all()
        from services.entomologia_acesso import eh_admin, membros_ativos
        publicacoes = EntomologiaPublicacao.query.order_by(EntomologiaPublicacao.id.desc()).limit(12).all()
        dataset = dataset_atual()
        gerencia_equipe = eh_admin(current_user)
        return _sem_cache(current_app.make_response(render_template(
            'sfa/entomologia_atualizar.html', previa=previa,
            previa_resumo=json.loads(previa.resumo_json or '{}') if previa else None,
            envios=envios, publicacoes=publicacoes, fonte=dataset['source'],
            hoje=hoje_local(), token=request.args.get('token') or None, pode_alterar=usuario_pode_alterar(),
            gerencia_equipe=gerencia_equipe, equipe=membros_ativos() if gerencia_equipe else [],
        )))

    @bp.route('/entomologia/atualizar', methods=['POST'])
    @require_access
    @login_required
    def entomologia_enviar():
        ensure_entomologia_editor()
        from extensions import db
        from models.entomologia import EntomologiaImportacao
        from services import entomologia_service as service
        from services.sfa_workflow import hoje_local
        from time_utils import utcnow

        tipo = request.form.get('tipo', service.TIPO_VISITAS)
        arquivo = request.files.get('arquivo')
        try:
            from services.entomologia_atlas import TIPO_ATLAS
            if tipo not in (service.TIPO_VISITAS, service.TIPO_CAMADA, TIPO_ATLAS):
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
                if tipo == TIPO_ATLAS:
                    from services.entomologia_atlas import read_earth
                    atlas = read_earth(blob, nome)
                    lido = {'geojson': atlas, 'sha256': atlas['source']['sha256'],
                            'titulo': atlas['source']['title'], 'pastas': list(atlas['source']['counts'])}
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
            repetido = EntomologiaImportacao.query.filter_by(tipo=registro.tipo, sha256=registro.sha256, status='ATIVA').order_by(EntomologiaImportacao.id.desc()).first()
            if repetido and tipo==TIPO_ATLAS and json.loads(repetido.dados_json).get('schema_version',1)<atlas.get('schema_version',1):
                repetido=None  # Same file can recover folder/address metadata lost by the old importer.
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
        ensure_entomologia_editor()
        from extensions import db
        from models.entomologia import EntomologiaImportacao
        from time_utils import utcnow

        registro = db.session.get(EntomologiaImportacao, envio_id)
        if not registro or registro.tipo == 'atlas_edit' or registro.status != 'PREVIA':
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
            flash(f'Camada “{registro.titulo}” disponível no atlas (projeto completo) ou na aba Entomologia (camada avulsa).', 'success')
        return redirect(url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None))

    @bp.route('/entomologia/envios/<int:envio_id>/desfazer', methods=['POST'])
    @require_access
    @login_required
    def entomologia_desfazer(envio_id):
        ensure_entomologia_editor()
        from extensions import db
        from models.entomologia import EntomologiaImportacao
        from time_utils import utcnow

        registro = db.session.get(EntomologiaImportacao, envio_id)
        if not registro or registro.tipo == 'atlas_edit' or registro.status not in ('PREVIA', 'ATIVA'):
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
        ensure_entomologia_editor()
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
        ensure_entomologia_editor()
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

    def _voltar_planejamento():
        return redirect(url_for('sfa_routes.entomologia', token=request.args.get('token') or None) + '#acao-criada')

    @bp.route('/entomologia/acoes', methods=['POST'])
    @require_access
    @login_required
    def entomologia_acao_criar():
        """Ação territorial criada no Planejamento, sem vínculo com pacientes."""
        ensure_entomologia_editor()
        from extensions import db
        from services.sfa_workflow_ops import registrar_operacao
        if not str(request.form.get('setor') or '').strip():
            flash('Informe o setor da ação territorial.', 'danger')
            return _voltar_planejamento()
        form = {campo: request.form.get(campo, '') for campo in ('responsavel', 'setor', 'tipo', 'motivo', 'prazo')}
        form.update(operacao='acao', id_estudo='', evento_id='')
        try:
            registrar_operacao(form, _ator())
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        else:
            flash('Ação territorial criada. Acompanhe o andamento na lista de ações do Planejamento.', 'success')
        return _voltar_planejamento()

    @bp.route('/entomologia/acoes/<int:acao_id>/andamento', methods=['POST'])
    @require_access
    @login_required
    def entomologia_acao_andamento(acao_id):
        """Execução e verificação de ações territoriais (não mexe em ações de pacientes)."""
        ensure_entomologia_editor()
        from extensions import db
        from models.sfa import SfaAcao
        from services.sfa_workflow_ops import registrar_operacao
        acao = db.session.get(SfaAcao, acao_id)
        if not acao or not _eh_territorial(acao):
            abort(404)
        form = {campo: request.form.get(campo, '') for campo in
                ('responsavel', 'status', 'resultado', 'evidencia_verificacao', 'horas', 'custo')}
        form.update(operacao='acao_status', acao_id=str(acao.id), id_estudo='')
        try:
            registrar_operacao(form, _ator())
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        else:
            flash(f'Ação #{acao.id} atualizada.', 'success')
        return _voltar_planejamento()

    @bp.route('/entomologia/equipe', methods=['POST'])
    @require_access
    @login_required
    def entomologia_equipe_conceder():
        ensure_entomologia_admin()
        from extensions import db
        from services.entomologia_acesso import ROTULO_PAPEL, buscar_conta, conceder
        destino = url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None) + '#equipe'
        try:
            conta = buscar_conta(request.form.get('email'))
            _, criado = conceder(conta, _responsavel())
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return redirect(destino)
        if criado:
            _auditar('conceder_papel', f'Papel {ROTULO_PAPEL} concedido à conta #{conta.id}',
                     {'user_id': conta.id, 'responsavel': request.form.get('responsavel')})
            db.session.commit()
            flash(f'{conta.name or conta.email} agora faz parte da equipe {ROTULO_PAPEL}.', 'success')
        else:
            flash('Essa conta já faz parte da equipe.', 'info')
        return redirect(destino)

    @bp.route('/entomologia/equipe/<int:user_id>/revogar', methods=['POST'])
    @require_access
    @login_required
    def entomologia_equipe_revogar(user_id):
        ensure_entomologia_admin()
        from extensions import db
        from services.entomologia_acesso import ROTULO_PAPEL, revogar
        destino = url_for('sfa_routes.entomologia_atualizar', token=request.args.get('token') or None) + '#equipe'
        try:
            responsavel = _responsavel()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(destino)
        if not revogar(user_id, responsavel):
            abort(404)
        _auditar('revogar_papel', f'Papel {ROTULO_PAPEL} revogado da conta #{user_id}',
                 {'user_id': user_id, 'responsavel': responsavel})
        db.session.commit()
        flash('Acesso à área de combate à dengue revogado. Os demais acessos da conta não mudaram.', 'info')
        return redirect(destino)
