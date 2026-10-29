"""Área das unidades de saúde: registrar a ficha SINAN, ver as fichas da unidade e o panorama.

Registradas no blueprint do SFA. Ao contrário das telas internas, aqui o token
do SFA não vale: toda rota exige uma conta, porque cada ficha fica atribuída a
quem preencheu e à unidade pela qual a pessoa responde.
"""
import re
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

_CAMPO = re.compile(r"[a-z0-9_]{1,80}")
_LIMITE_EMAILS = 30


def _usuario():
    # Os testes do SFA montam um Flask cru só com o blueprint, sem login.
    return current_user if hasattr(current_app, 'login_manager') else None


def usuario_pode_acessar():
    from services.sfa_notificacao import pode_acessar
    return pode_acessar(_usuario())


def usuario_administra():
    from services.sfa_notificacao import eh_admin
    return eh_admin(_usuario())


def usuario_so_notificacao():
    from services.sfa_notificacao import conta_so_notificacao
    return conta_so_notificacao(_usuario())


def require_notificacao_access(view):
    """Conta logada que é administradora ou responde por alguma unidade ativa."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not getattr(_usuario(), 'is_authenticated', False):
            if hasattr(current_app, 'login_manager') and 'login_view' in current_app.view_functions:
                return redirect(url_for('login_view', next=request.url))
            abort(401)
        if not usuario_pode_acessar():
            abort(404)
        return view(*args, **kwargs)

    return wrapper


def ensure_notificacao_admin():
    """Cadastrar unidades e indicar responsáveis é tarefa de administrador."""
    if not usuario_administra():
        abort(404)


def _sem_cache(response):
    response = current_app.make_response(response)
    response.headers['Cache-Control'] = 'private, no-store'
    # same-origin, não no-referrer: em HTTPS o CSRF exige o Referer do próprio site, e sem ele todo
    # envio (ficha, responsáveis, unidades) era recusado. Para fora do site nada é enviado.
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def _data_hora(iso):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(iso)).strftime('%d/%m/%Y %H:%M')
    except ValueError:
        return ''


def _enumerar(itens):
    itens = list(itens)
    return itens[0] if len(itens) == 1 else ', '.join(itens[:-1]) + ' e ' + itens[-1]


def _auditar(funcao, mensagem, detalhes, id_estudo=None):
    from services.sfa_notificacao import auditar
    auditar(funcao, mensagem, detalhes, ator=current_user, id_estudo=id_estudo)


def register(bp):
    @bp.context_processor
    def _inject_notificacao():
        return {'sfa_acesso_notificacao': usuario_pode_acessar, 'sfa_notificacao_admin': usuario_administra,
                'sfa_conta_so_notificacao': usuario_so_notificacao}

    def ensure_ficha_da_unidade(ficha_id):
        """A ficha, se é de uma unidade ao alcance da conta; senão 404, sem revelar que ela existe."""
        from services.sfa_notificacao import ficha_visivel
        return ficha_visivel(current_user, ficha_id) or abort(404)

    def ensure_unidade_da_conta(unidades, unidade_id):
        """A unidade pedida, se a conta pode registrar em nome dela (a única, quando nenhuma foi pedida)."""
        return next((u for u in unidades if unidade_id in (None, u.id)), None) or abort(404)

    def _mensagem_ao_salvar(mensagem, answers, schema):
        """Diz quantos obrigatórios ainda faltam, para a enfermagem saber que precisa completar a ficha."""
        from services.sfa_notificacao import pendencias

        faltam = [item for item in pendencias(answers, schema) if item['obrigatorio']]
        if not faltam:
            return mensagem
        numeros = ', '.join(dict.fromkeys(item['numero'] for item in faltam))
        return (f"{mensagem} {'Falta' if len(faltam) == 1 else 'Faltam'} {len(faltam)} "
                f"{'campo obrigatório' if len(faltam) == 1 else 'campos obrigatórios'} para completar depois "
                f"({numeros}); use “Completar ficha”.")

    def _formulario(schema, submitted, form_action, contexto, error='', error_field=''):
        return _sem_cache(render_template('sfa/pre_t0_form.html', schema=schema, error=error,
                                          error_field=error_field, submitted=submitted,
                                          form_action=form_action, unidade_ctx=contexto))

    # ------------------------------------------------------------------ fichas da unidade
    @bp.route('/notificacao')
    @require_notificacao_access
    @login_required
    def notificacao_fichas():
        from services.sfa_notificacao import listar_fichas, unidades_para_registrar

        unidades = unidades_para_registrar(current_user)
        unidade_id = request.args.get('unidade', type=int)
        if unidade_id and unidade_id not in {u.id for u in unidades}:
            abort(404)
        busca = str(request.args.get('busca') or '').strip()
        so_pendentes = request.args.get('pendentes') == '1'
        dados = listar_fichas(current_user, unidade_id=unidade_id, busca=busca, so_pendentes=so_pendentes)
        return _sem_cache(render_template('sfa/notificacao_fichas.html', unidades=unidades, unidade_id=unidade_id,
                                          busca=busca, so_pendentes=so_pendentes, **dados))

    # ------------------------------------------------------------------ nova ficha
    @bp.route('/notificacao/ficha', methods=['GET', 'POST'])
    @require_notificacao_access
    @login_required
    def notificacao_nova():
        from services.sfa_notificacao import ficha_ja_registrada, ficha_visivel, nome_da_conta, unidades_para_registrar
        from services.sfa_pre_t0 import CampoInvalido, coletar_respostas_pre_t0, esquema_da_notificacao, salvar_ficha_pre_t0
        from services.sfa_workflow import hoje_local

        unidades = unidades_para_registrar(current_user)
        if not unidades:
            flash('Cadastre uma unidade de saúde antes de registrar fichas.', 'warning')
            return redirect(url_for('sfa_routes.notificacao_unidades'))
        unidade_id = request.args.get('unidade', type=int)
        if unidade_id is None and len(unidades) > 1:
            return _sem_cache(render_template('sfa/notificacao_escolher.html', unidades=unidades))
        unidade = ensure_unidade_da_conta(unidades, unidade_id)

        schema = esquema_da_notificacao()
        acao = url_for('sfa_routes.notificacao_nova', unidade=unidade.id)
        contexto = {'modo': 'nova', 'unidade_nome': unidade.nome, 'voltar_url': url_for('sfa_routes.notificacao_fichas')}
        if request.method == 'POST':
            if request.content_length and request.content_length > 131072:
                abort(413)
            # Campo armadilha para descartar envios automatizados sem guardar dados.
            if str(request.form.get('website') or '').strip():
                return redirect(url_for('sfa_routes.notificacao_fichas'))
            try:
                answers = coletar_respostas_pre_t0(request.form, schema)
                answers['unidade_notificante'] = {'valor': unidade.nome, 'codigo': unidade.cnes or ''}
                existente = ficha_ja_registrada(answers.get('ficha_sinan'))
                if existente is not None:
                    if ficha_visivel(current_user, existente.id) is not None:
                        flash('Esta ficha já estava registrada. Nada foi gravado de novo.', 'info')
                        return redirect(url_for('sfa_routes.notificacao_ficha', ficha_id=existente.id))
                    raise CampoInvalido('Já existe uma ficha registrada com esse número. Confira o número ou '
                                        'fale com a vigilância.', 'ficha_sinan')
                salvo = salvar_ficha_pre_t0(answers, autor_id=current_user.id, unidade=unidade)
            except (ValueError, RuntimeError) as exc:
                return _formulario(schema, request.form, acao, contexto, str(exc), getattr(exc, 'campo', ''))
            flash(_mensagem_ao_salvar('Ficha registrada.', answers, schema), 'success')
            return redirect(url_for('sfa_routes.notificacao_ficha', ficha_id=salvo['log_id']))

        iniciais = {
            'data_notificacao': hoje_local().isoformat(),
            'uf_notificacao': 'SP', 'municipio_notificacao': 'Orlândia', 'codigo_municipio_notificacao': '3534708',
            'unidade_notificante': unidade.nome, 'codigo_unidade_notificante': unidade.cnes or '',
            'investigador__municipio_unidade': f'Orlândia / {unidade.nome}'[:180],
            'investigador__codigo_unidade': unidade.cnes or '',
            'investigador__nome': nome_da_conta(current_user)[:160],
        }
        return _formulario(schema, iniciais, acao, contexto)

    # ------------------------------------------------------------------ uma ficha
    @bp.route('/notificacao/fichas/<int:ficha_id>')
    @require_notificacao_access
    @login_required
    def notificacao_ficha(ficha_id):
        from extensions import db
        from models import User
        from services.sfa_notificacao import (agravo_da_ficha, motivo_para_nao_excluir, nome_da_conta, pendencias,
                                              pendencias_por_grupo, pode_completar)
        from services.sfa_pre_t0 import carregar_esquema_pre_t0, obter_ficha_do_log

        log_entry = ensure_ficha_da_unidade(ficha_id)
        schema = carregar_esquema_pre_t0()
        ficha = obter_ficha_do_log(log_entry, schema)
        faltam = pendencias(ficha['respostas'], schema)
        # Na ordem da ficha, para as alterações aparecerem como a pessoa lê o formulário.
        numeros = {field['key']: field['number'] or field['campo']
                   for section in schema['sections'] for field in section['fields']}
        revisoes = []
        for revisao in reversed(ficha['revisoes']):
            autor = db.session.get(User, revisao.get('por')) if isinstance(revisao.get('por'), int) else None
            revisoes.append({'em': _data_hora(revisao.get('em')), 'autor': nome_da_conta(autor) or 'Conta removida',
                             'campos': [numero for key, numero in numeros.items()
                                        if key in (revisao.get('campos') or [])]})
        editavel = pode_completar(current_user, log_entry)
        return _sem_cache(render_template(
            'sfa/notificacao_ficha.html', log=log_entry, ficha=ficha, revisoes=revisoes,
            grupos=pendencias_por_grupo(faltam), faltando={item['chave'] for item in faltam},
            agravo=agravo_da_ficha(ficha['respostas']), autor=nome_da_conta(log_entry.preenchido_por),
            pode_completar=editavel, motivo_exclusao=motivo_para_nao_excluir(log_entry) if editavel else ''))

    @bp.route('/notificacao/fichas/<int:ficha_id>/completar', methods=['GET', 'POST'])
    @require_notificacao_access
    @login_required
    def notificacao_completar(ficha_id):
        from services.sfa_notificacao import pendencias, pendencias_por_grupo, pode_completar
        from services.sfa_pre_t0 import (atualizar_ficha_pre_t0, coletar_respostas_pre_t0, esquema_da_notificacao,
                                         obter_ficha_do_log, respostas_para_formulario)

        log_entry = ensure_ficha_da_unidade(ficha_id)
        if not pode_completar(current_user, log_entry):
            abort(404)
        schema = esquema_da_notificacao()
        respostas = obter_ficha_do_log(log_entry, schema)['respostas']
        faltam = pendencias(respostas, schema)
        destino = url_for('sfa_routes.notificacao_ficha', ficha_id=log_entry.id)
        campo = str(request.args.get('campo') or '')
        contexto = {'modo': 'completar', 'unidade_nome': log_entry.unidade.nome, 'voltar_url': destino,
                    'ficha_sinan': log_entry.ficha_sinan or '', 'grupos': pendencias_por_grupo(faltam),
                    'faltando': {item['chave'] for item in faltam},
                    'focar': campo if _CAMPO.fullmatch(campo) else ''}
        acao = url_for('sfa_routes.notificacao_completar', ficha_id=log_entry.id)
        if request.method == 'POST':
            if request.content_length and request.content_length > 131072:
                abort(413)
            try:
                answers = coletar_respostas_pre_t0(request.form, schema)
                resultado = atualizar_ficha_pre_t0(log_entry.id, answers, autor_id=current_user.id,
                                                   preservar=('unidade_notificante',))
            except (ValueError, RuntimeError) as exc:
                return _formulario(schema, request.form, acao, contexto, str(exc), getattr(exc, 'campo', ''))
            if resultado['alterados']:
                flash(_mensagem_ao_salvar('Alterações salvas.', answers, schema), 'success')
            else:
                flash('Nada mudou: a ficha continua como estava.', 'info')
            return redirect(destino)
        return _formulario(schema, respostas_para_formulario(respostas, schema), acao, contexto)

    @bp.route('/notificacao/fichas/<int:ficha_id>/excluir', methods=['POST'])
    @require_notificacao_access
    @login_required
    def notificacao_excluir(ficha_id):
        """Exclui a ficha (e o caso que só ela criou) enquanto o estudo não agiu sobre ela."""
        from extensions import db
        from services.sfa_notificacao import excluir_ficha, pode_completar

        log_entry = ensure_ficha_da_unidade(ficha_id)
        if not pode_completar(current_user, log_entry):
            abort(404)
        try:
            resumo = excluir_ficha(log_entry)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'warning')
            return redirect(url_for('sfa_routes.notificacao_ficha', ficha_id=ficha_id))
        _auditar('excluir_ficha', f"Ficha #{resumo['ficha_id']} excluída pela área das unidades", resumo,
                 id_estudo=resumo['id_estudo'] or None)
        db.session.commit()
        flash(f"Ficha {resumo['ficha_sinan'] or 'sem número'} excluída.", 'success')
        return redirect(url_for('sfa_routes.notificacao_fichas'))

    @bp.route('/notificacao/fichas/<int:ficha_id>/imprimir')
    @require_notificacao_access
    @login_required
    def notificacao_imprimir(ficha_id):
        """Ficha na disposição da folha oficial do SINAN, pronta para imprimir."""
        from services.sfa_pre_t0 import montar_folha_pre_t0, obter_ficha_do_log

        log_entry = ensure_ficha_da_unidade(ficha_id)
        ficha = obter_ficha_do_log(log_entry)
        return _sem_cache(render_template(
            'sfa/pre_t0_print.html', folha=montar_folha_pre_t0(ficha['respostas']),
            recebida_em=ficha['submitted_at'], voltar_rotulo='Voltar à ficha', simulacao=None, oculto='',
            voltar_url=url_for('sfa_routes.notificacao_ficha', ficha_id=log_entry.id)))

    # ------------------------------------------------------------------ panorama
    @bp.route('/notificacao/panorama')
    @require_notificacao_access
    @login_required
    def notificacao_panorama():
        from services.sfa_notificacao import panorama, unidades_do_usuario
        from services.sfa_workflow import hoje_local

        agravo = request.args.get('agravo')
        agravo = agravo if agravo in ('Dengue', 'Chikungunya') else ''
        dados = panorama(hoje_local(), agravo=agravo, detalhar=usuario_administra(),
                         minhas=tuple(u.id for u in unidades_do_usuario(current_user)))
        return _sem_cache(render_template('sfa/notificacao_panorama.html', agravo=agravo, p=dados))

    # ------------------------------------------------------------------ unidades e responsáveis (administrador)
    def _voltar_unidades(ancora=''):
        return redirect(url_for('sfa_routes.notificacao_unidades') + ancora)

    @bp.route('/notificacao/unidades')
    @require_notificacao_access
    @login_required
    def notificacao_unidades():
        ensure_notificacao_admin()
        from models.sfa import SfaUnidadeSaude
        from services.sfa_notificacao import PERFIL_SO_NOTIFICACAO
        unidades = SfaUnidadeSaude.query.order_by(SfaUnidadeSaude.ativa.desc(), SfaUnidadeSaude.nome).all()
        return _sem_cache(render_template('sfa/notificacao_unidades.html', unidades=unidades,
                                          perfil_so_notificacao=PERFIL_SO_NOTIFICACAO,
                                          editar_conta='user.edit_view' in current_app.view_functions))

    @bp.route('/notificacao/unidades', methods=['POST'])
    @require_notificacao_access
    @login_required
    def notificacao_unidade_criar():
        ensure_notificacao_admin()
        from extensions import db
        from services.sfa_notificacao import criar_unidade, nome_da_conta
        try:
            unidade = criar_unidade(request.form, nome_da_conta(current_user)[:160])
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return _voltar_unidades('#nova-unidade')
        _auditar('criar_unidade', f'Unidade de saúde #{unidade.id} cadastrada', {'unidade_id': unidade.id})
        db.session.commit()
        flash(f'{unidade.nome} cadastrada. Indique quem responde por ela.', 'success')
        return _voltar_unidades(f'#unidade-{unidade.id}')

    @bp.route('/notificacao/unidades/<int:unidade_id>', methods=['POST'])
    @require_notificacao_access
    @login_required
    def notificacao_unidade_editar(unidade_id):
        ensure_notificacao_admin()
        from extensions import db
        from models.sfa import SfaUnidadeSaude
        from services.sfa_notificacao import atualizar_unidade
        unidade = db.session.get(SfaUnidadeSaude, unidade_id) or abort(404)
        try:
            alterados = atualizar_unidade(unidade, request.form)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
            return _voltar_unidades(f'#unidade-{unidade_id}')
        if alterados:
            _auditar('editar_unidade', f'Unidade de saúde #{unidade.id} alterada',
                     {'unidade_id': unidade.id, 'campos': alterados})
            db.session.commit()
            flash(f'{unidade.nome} atualizada.', 'success')
        return _voltar_unidades(f'#unidade-{unidade_id}')

    @bp.route('/notificacao/unidades/<int:unidade_id>/responsaveis', methods=['POST'])
    @require_notificacao_access
    @login_required
    def notificacao_responsavel_conceder(unidade_id):
        """Indica uma ou várias contas de uma vez: a unidade pode ter quantos responsáveis precisar."""
        ensure_notificacao_admin()
        from extensions import db
        from models.sfa import SfaUnidadeSaude
        from services.entomologia_acesso import buscar_conta
        from services.sfa_notificacao import conceder, nome_da_conta
        unidade = db.session.get(SfaUnidadeSaude, unidade_id) or abort(404)
        destino = f'#unidade-{unidade_id}'
        digitados = re.split(r'[\s,;]+', str(request.form.get('email') or ''))
        emails = list(dict.fromkeys(email.lower() for email in digitados if email))
        if not emails:
            flash('Informe o e-mail de pelo menos uma conta.', 'danger')
            return _voltar_unidades(destino)
        if len(emails) > _LIMITE_EMAILS:
            flash(f'Indique até {_LIMITE_EMAILS} e-mails por vez.', 'danger')
            return _voltar_unidades(destino)
        novos, repetidos, sem_conta = [], [], []
        for email in emails:
            try:
                conta = buscar_conta(email)
            except ValueError:
                sem_conta.append(email[:254])
                continue
            _, criado = conceder(unidade, conta, nome_da_conta(current_user)[:160])
            (novos if criado else repetidos).append(nome_da_conta(conta))
            if criado:
                _auditar('conceder_responsavel', f'Conta #{conta.id} passou a responder pela unidade #{unidade.id}',
                         {'unidade_id': unidade.id, 'user_id': conta.id})
        if novos:
            db.session.commit()
            flash(f"{_enumerar(novos)} agora {'responde' if len(novos) == 1 else 'respondem'} por {unidade.nome}.",
                  'success')
        if repetidos:
            flash(f"{_enumerar(repetidos)} já {'respondia' if len(repetidos) == 1 else 'respondiam'} por esta unidade.",
                  'info')
        if sem_conta:
            flash(f"Nenhuma conta no site com {'este e-mail' if len(sem_conta) == 1 else 'estes e-mails'}: "
                  f"{', '.join(sem_conta)}. Peça para a pessoa criar a conta com esse endereço e indique de novo.",
                  'danger')
        return _voltar_unidades(destino)

    @bp.route('/notificacao/responsaveis/<int:vinculo_id>/revogar', methods=['POST'])
    @require_notificacao_access
    @login_required
    def notificacao_responsavel_revogar(vinculo_id):
        ensure_notificacao_admin()
        from extensions import db
        from services.sfa_notificacao import nome_da_conta, revogar
        vinculo = revogar(vinculo_id, nome_da_conta(current_user)[:160]) or abort(404)
        _auditar('revogar_responsavel', f'Conta #{vinculo.user_id} deixou de responder pela unidade #{vinculo.unidade_id}',
                 {'unidade_id': vinculo.unidade_id, 'user_id': vinculo.user_id})
        db.session.commit()
        flash('Acesso à unidade revogado. Os demais acessos da conta não mudaram.', 'info')
        return _voltar_unidades(f'#unidade-{vinculo.unidade_id}')
