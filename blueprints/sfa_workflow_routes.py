"""Rotas internas do acompanhamento SFA, registradas no blueprint existente."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user


def register(bp, require_access):
    @bp.route('/trabalho')
    @require_access
    def trabalho():
        from models.sfa import SfaPaciente, SfaAcao, SfaEventoColetivo
        from services.sfa_service import anexar_dados_sinan_pacientes, filtrar_pacientes_reais_sfa
        from services.sfa_workflow import pendencias_qualidade, resumo_calendario, hoje_local
        from services.entomologia_service import load_entomologia
        todos = filtrar_pacientes_reais_sfa(SfaPaciente.query.order_by(SfaPaciente.id_estudo).all())
        anexar_dados_sinan_pacientes(todos)
        episodio = request.args.get('episodio', '')
        paciente = next((p for p in todos if p.id_estudo == episodio), None)
        if episodio and not paciente:
            abort(404)
        return render_template('sfa/trabalho.html', pacientes=todos, p=paciente,
                               calendario=resumo_calendario(paciente) if paciente else None,
                               pendencias=pendencias_qualidade(todos),
                               acoes=SfaAcao.query.order_by(SfaAcao.prazo, SfaAcao.id).all(),
                               eventos=SfaEventoColetivo.query.order_by(SfaEventoColetivo.id.desc()).all(),
                               setores=sorted({str(r['sector']) for r in load_entomologia()['records'] if r.get('sector')}),
                               hoje=hoje_local())

    @bp.route('/trabalho/registrar', methods=['POST'])
    @require_access
    def trabalho_registrar():
        from extensions import db
        from services.sfa_workflow_ops import registrar_operacao
        ator = str(current_user.get_id()) if current_user.is_authenticated else 'acesso interno por token/configuração'
        try:
            registrar_operacao(request.form, ator)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        else:
            flash('Registro salvo com histórico de auditoria.', 'success')
        return redirect(url_for('sfa_routes.trabalho', episodio=request.form.get('id_estudo', '')))

    @bp.route('/vigilancia-semanal')
    @require_access
    def vigilancia_semanal():
        from models.sfa import SfaPaciente
        from services.sfa_service import anexar_dados_sinan_pacientes
        from services.sfa_workflow import vigilancia_semanal as montar
        from services.entomologia_service import load_entomologia
        defasagem = request.args.get('defasagem', 0, type=int)
        if defasagem not in range(5):
            abort(400)
        pacientes = SfaPaciente.query.all()
        anexar_dados_sinan_pacientes(pacientes)
        resumo = montar(pacientes, load_entomologia(), defasagem)
        setor = request.args.get('setor', '').strip()
        setores = sorted({r['setor'] for r in resumo['linhas']})
        if setor:
            resumo['linhas'] = [r for r in resumo['linhas'] if r['setor'] == setor]
        return render_template('sfa/vigilancia_semanal.html', resumo=resumo, setores=setores, setor=setor)
