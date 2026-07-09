"""Views do domínio consulta_routes (migrado do app.py)."""
from flask import Blueprint
import json, os, re, unicodedata, uuid
from authz import can_manage_budget, can_view_budget
from context_processors import _invalidate_cached_context
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from extensions import db
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from forms import AnimalForm, AppointmentForm, EditProfileForm
from helpers import group_appointments_by_day
from models import (
    AdministracaoRegistro,
    Animal,
    Appointment,
    ApresentacaoMedicamento,
    BlocoExames,
    BlocoOrcamento,
    BlocoPrescricao,
    ClinicNotification,
    Clinica,
    Consulta,
    DoseMedicamento,
    ExameModelo,
    ExameSolicitado,
    FiscalDocument,
    FiscalDocumentType,
    FotoTratamento,
    ItemTratamento,
    Medicamento,
    Message,
    Notification,
    Orcamento,
    OrcamentoItem,
    Prescricao,
    ProtocoloClinico,
    ServicoClinica,
)
from services import coverage_badge, coverage_label
from services.appointments import ReturnAppointmentDTO, finalize_consulta_flow, schedule_return_appointment
from services.billing.close_appointment import close_appointment
from services.clinical_suggestions import build_followup_prefill, log_suggestion_event, recommend_protocols
from services.payments import PaymentItemDTO, PaymentPreferenceDTO, apply_payment_to_bloco, apply_payment_to_orcamento, create_payment_preference
from sqlalchemy import Text, cast, or_, text
from sqlalchemy.orm import load_only, selectinload
from template_filters import PAYER_TYPE_LABELS, default_payer_type_for_consulta, payer_type_label
from time_utils import BR_TZ, coerce_to_brazil_tz, now_in_brazil, utcnow
from urllib.parse import quote_plus
from werkzeug.utils import secure_filename

# Helpers ainda hospedados no app.py (realocação em fases futuras).
from app import (  # noqa: E402
    ORCAMENTO_PAYMENT_STATUS_LABELS,
    ORCAMENTO_PAYMENT_STATUS_STYLES,
    ORCAMENTO_STATUS_LABELS,
    ORCAMENTO_STATUS_STYLES,
    PaymentPreferenceError,
    _append_consulta_text,
    _apply_protocol_payload,
    _build_clinical_suggestion_context,
    _build_protocol_from_payload,
    _clear_medication_search_cache,
    _clinic_orcamento_blocks,
    _clinic_prescricao_blocks,
    _clinical_suspicion_options,
    _coerce_int,
    _current_user_owns_animal,
    _ensure_clinic_notifications_table,
    _find_protocol_item,
    _first_access_url_for_user,
    _get_medication_search_cache,
    _mercadopago_notification_url,
    _mp_auto_return_enabled,
    _normalizar_instrucoes_prescricao,
    _protocol_preferred_dose_mode,
    _protocol_prefers_weight_based_dose,
    _render_prescricao_history,
    _serialize_clinical_protocol,
    _set_medication_search_cache,
    _tratamento_acompanhamento_or_404,
    _web_whatsapp_url,
    current_user_clinic_id,
    formatar_telefone,
    get_animal_or_404,
    get_consulta_or_404,
    list_breeds,
    list_rations,
    list_species,
)

bp = Blueprint("consulta_routes", __name__)


def get_blueprint():
    return bp


def _criar_preferencia_pagamento(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._criar_preferencia_pagamento.
    import app as app_module
    return app_module._criar_preferencia_pagamento(*args, **kwargs)


def _render_orcamento_history(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._render_orcamento_history.
    import app as app_module
    return app_module._render_orcamento_history(*args, **kwargs)


def _sync_orcamento_payment_classification(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._sync_orcamento_payment_classification.
    import app as app_module
    return app_module._sync_orcamento_payment_classification(*args, **kwargs)


def ensure_clinic_access(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.ensure_clinic_access.
    import app as app_module
    return app_module.ensure_clinic_access(*args, **kwargs)


def is_veterinarian(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.is_veterinarian.
    import app as app_module
    return app_module.is_veterinarian(*args, **kwargs)


def mp_sdk(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.mp_sdk.
    import app as app_module
    return app_module.mp_sdk(*args, **kwargs)


def upload_to_s3(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.upload_to_s3.
    import app as app_module
    return app_module.upload_to_s3(*args, **kwargs)



@bp.route('/animal/<int:animal_id>/historico_consultas', methods=['GET'])
@login_required
def historico_consultas_partial(animal_id):
    animal = get_animal_or_404(animal_id)
    clinic_id = request.args.get('clinica_id', type=int) or getattr(animal, 'clinica_id', None) or current_user_clinic_id()

    if clinic_id:
        ensure_clinic_access(clinic_id)

    # Only show history if we have a valid clinic_id to prevent data leakage
    if clinic_id:
        historico = (
            Consulta.query
            .filter_by(animal_id=animal.id, status='finalizada', clinica_id=clinic_id)
            .order_by(Consulta.created_at.desc())
            .all()
        )
    else:
        historico = []

    historico_html = render_template(
        'partials/historico_consultas.html',
        animal=animal,
        historico_consultas=historico,
    )
    return jsonify({'success': True, 'html': historico_html})


@bp.route('/consulta/<int:consulta_id>/sugestoes_clinicas', methods=['POST'])
@login_required
def obter_sugestoes_clinicas(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem solicitar sugestões clínicas.'}), 403

    payload = request.get_json(silent=True) or {}
    context = _build_clinical_suggestion_context(consulta, payload)
    suggestions = recommend_protocols(context, clinic_id=consulta.clinica_id)

    for suggestion in suggestions:
        log_suggestion_event(
            consulta_id=consulta.id,
            protocolo_id=suggestion['id'],
            actor_user_id=current_user.id,
            tipo_item='protocolo',
            acao='shown',
            titulo_item=suggestion['nome'],
            justificativa=' | '.join(suggestion.get('motivos') or []),
            payload={
                'suspeita_clinica': context.get('suspeita_clinica'),
                'score': suggestion.get('score'),
            },
        )
    db.session.commit()

    return jsonify({
        'success': True,
        'suggestions': suggestions,
        'context': context,
        'message': 'Sugestões carregadas com sucesso.' if suggestions else 'Nenhum protocolo compatível encontrado ainda.',
    })


@bp.route('/consulta/<int:consulta_id>/sugestoes_clinicas/feedback', methods=['POST'])
@login_required
def registrar_feedback_sugestao_clinica(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem registrar feedback clínico.'}), 403

    payload = request.get_json(silent=True) or {}
    protocol_id = payload.get('protocol_id')
    action = (payload.get('action') or '').strip().lower()
    item_type = (payload.get('item_type') or 'protocolo').strip().lower()
    title = (payload.get('title') or '').strip() or None

    if action not in {'dismissed', 'shown', 'accepted', 'scheduled'}:
        return jsonify({'success': False, 'message': 'Ação de feedback inválida.'}), 400

    log_suggestion_event(
        consulta_id=consulta.id,
        protocolo_id=protocol_id,
        actor_user_id=current_user.id,
        tipo_item=item_type,
        acao=action,
        titulo_item=title,
        justificativa=payload.get('justificativa'),
        payload=payload.get('payload') or None,
    )
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/consulta/<int:consulta_id>/sugestoes_clinicas/plano', methods=['POST'])
@login_required
def calcular_plano_sugestao_clinica(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinÃ¡rios podem calcular planos clÃ­nicos.'}), 403

    payload = request.get_json(silent=True) or {}
    try:
        protocol_id = int(payload.get('protocol_id')) if payload.get('protocol_id') is not None else None
    except (TypeError, ValueError):
        protocol_id = None
    if not protocol_id:
        return jsonify({'success': False, 'message': 'Informe o protocolo clÃ­nico para calcular o plano.'}), 400

    protocol = (
        ProtocoloClinico.query
        .options(
            selectinload(ProtocoloClinico.exames_sugeridos),
            selectinload(ProtocoloClinico.medicamentos_sugeridos),
            selectinload(ProtocoloClinico.retornos_sugeridos),
        )
        .get_or_404(protocol_id)
    )
    if protocol.clinica_id and protocol.clinica_id != consulta.clinica_id:
        return jsonify({'success': False, 'message': 'Protocolo clÃ­nico indisponÃ­vel para esta clÃ­nica.'}), 403

    from services.clinical_plan import build_clinical_plan
    plan = build_clinical_plan(consulta, protocol, session=db.session)
    return jsonify({
        'success': True,
        'plan': plan,
        'message': 'Plano clÃ­nico calculado com sucesso.',
    })


@bp.route('/consulta/<int:consulta_id>/sugestoes_clinicas/aplicar', methods=['POST'])
@login_required
def aplicar_sugestao_clinica(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem aplicar sugestões clínicas.'}), 403

    payload = request.get_json(silent=True) or {}
    try:
        protocol_id = int(payload.get('protocol_id')) if payload.get('protocol_id') is not None else None
    except (TypeError, ValueError):
        protocol_id = None
    try:
        item_id = int(payload.get('item_id')) if payload.get('item_id') is not None else None
    except (TypeError, ValueError):
        item_id = None
    item_type = (payload.get('item_type') or '').strip().lower()
    if not protocol_id or item_type not in {'exame', 'medicamento', 'conduta', 'retorno'}:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos para aplicar sugestão.'}), 400

    protocol = (
        ProtocoloClinico.query
        .options(
            selectinload(ProtocoloClinico.exames_sugeridos),
            selectinload(ProtocoloClinico.medicamentos_sugeridos),
            selectinload(ProtocoloClinico.retornos_sugeridos),
        )
        .get_or_404(protocol_id)
    )
    item = _find_protocol_item(protocol, item_type, item_id)
    if not item:
        return jsonify({'success': False, 'message': 'Sugestão não encontrada no protocolo selecionado.'}), 404

    clinic_id = (
        consulta.clinica_id
        or current_user_clinic_id()
        or getattr(consulta.animal, 'clinica_id', None)
    )
    if item_type == 'exame':
        bloco = BlocoExames(
            animal_id=consulta.animal_id,
            observacoes_gerais=f"Sugestão aprovada do protocolo {protocol.nome}.",
        )
        db.session.add(bloco)
        db.session.flush()
        db.session.add(
            ExameSolicitado(
                bloco_id=bloco.id,
                nome=item.nome,
                justificativa=item.justificativa,
                status='pendente',
            )
        )
        response_payload = {'message': 'Exame sugerido adicionado ao histórico.'}
        title = item.nome
    elif item_type == 'medicamento':
        resolved_medicamento_id = item.medicamento_id
        if not resolved_medicamento_id and item.nome_exibicao:
            from services.prescricao_alias import resolver_e_persistir
            resolved_medicamento_id = resolver_e_persistir(item.nome_exibicao, db.session, db)
        response_payload = {
            'message': 'Sugestão aceita. Prescrição preparada como rascunho na aba de medicamentos.',
            'draft_prescription': {
                'medicamento_id': resolved_medicamento_id,
                'medicamento': item.nome_exibicao,
                'dosagem': item.dosagem_texto or '',
                'frequencia': item.frequencia_texto or '',
                'duracao': item.duracao_texto or '',
                'observacoes': item.observacoes or '',
                'texto': item.observacoes or '',
                'indicacao': item.indicacao or '',
                'use_weight_based_dose': bool(
                    resolved_medicamento_id and _protocol_prefers_weight_based_dose(item)
                ),
                'preferred_dose_mode': _protocol_preferred_dose_mode(item),
                'compact_practical_dose': (item.nome_exibicao or '').strip().lower() == 'simparic',
            },
            'draft_instructions': (protocol.orientacoes_tutor or '').strip() or '',
        }
        title = item.nome_exibicao
    elif item_type == 'conduta':
        consulta.conduta = _append_consulta_text(consulta.conduta, protocol.conduta_sugerida)
        response_payload = {
            'conduta': consulta.conduta,
            'message': 'Conduta sugerida adicionada ao rascunho da consulta.',
        }
        title = protocol.nome
    else:
        prefill = build_followup_prefill(item, reference_date=date.today())
        response_payload = {
            'prefill': prefill,
            'message': 'Sugestão de retorno preparada para revisão antes do agendamento.',
        }
        title = prefill['label']

    log_suggestion_event(
        consulta_id=consulta.id,
        protocolo_id=protocol.id,
        actor_user_id=current_user.id,
        tipo_item=item_type,
        acao='accepted',
        titulo_item=title,
        justificativa=getattr(item, 'justificativa', None) or getattr(protocol, 'conduta_sugerida', None),
        payload={'item_id': item_id, 'protocol_name': protocol.nome},
    )
    db.session.commit()
    if item_type == 'exame':
        animal_atualizado = Animal.query.get(consulta.animal_id)
        response_payload['html'] = render_template('partials/historico_exames.html', animal=animal_atualizado)
    return jsonify({'success': True, **response_payload})


@bp.route('/consulta/<int:consulta_id>/sugestoes_clinicas/protocolos', methods=['POST'])
@login_required
def criar_protocolo_clinico_inline(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem criar protocolos clínicos.'}), 403

    payload = request.get_json(silent=True) or {}
    try:
        protocolo = _build_protocol_from_payload(payload, consulta)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400

    db.session.add(protocolo)
    db.session.flush()

    log_suggestion_event(
        consulta_id=consulta.id,
        protocolo_id=protocolo.id,
        actor_user_id=current_user.id,
        tipo_item='protocolo',
        acao='created',
        titulo_item=protocolo.nome,
        justificativa=protocolo.suspeita_principal,
        payload={'origem': 'consulta_inline'},
    )
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Novo protocolo criado com sucesso.',
        'protocol': _serialize_clinical_protocol(protocolo),
        'clinical_suspicion_options': _clinical_suspicion_options(consulta.clinica_id),
    })


@bp.route('/consulta/<int:consulta_id>/sugestoes_clinicas/protocolos/<int:protocol_id>', methods=['GET'])
@login_required
def obter_protocolo_clinico_inline(consulta_id, protocol_id):
    consulta = get_consulta_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem visualizar protocolos clínicos.'}), 403

    protocolo = (
        ProtocoloClinico.query
        .options(
            selectinload(ProtocoloClinico.exames_sugeridos),
            selectinload(ProtocoloClinico.medicamentos_sugeridos),
            selectinload(ProtocoloClinico.retornos_sugeridos),
        )
        .get_or_404(protocol_id)
    )
    if protocolo.clinica_id and protocolo.clinica_id != consulta.clinica_id:
        return jsonify({'success': False, 'message': 'Este protocolo pertence a outra clínica.'}), 403

    edit_mode = 'update' if protocolo.clinica_id == consulta.clinica_id else 'clone'

    return jsonify({
        'success': True,
        'protocol': _serialize_clinical_protocol(protocolo),
        'edit_mode': edit_mode,
    })


@bp.route('/consulta/<int:consulta_id>/sugestoes_clinicas/protocolos/<int:protocol_id>', methods=['PUT'])
@login_required
def atualizar_protocolo_clinico_inline(consulta_id, protocol_id):
    consulta = get_consulta_or_404(consulta_id)
    ensure_clinic_access(consulta.clinica_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar protocolos clínicos.'}), 403

    protocolo = (
        ProtocoloClinico.query
        .options(
            selectinload(ProtocoloClinico.exames_sugeridos),
            selectinload(ProtocoloClinico.medicamentos_sugeridos),
            selectinload(ProtocoloClinico.retornos_sugeridos),
        )
        .get_or_404(protocol_id)
    )
    if not protocolo.clinica_id or protocolo.clinica_id != consulta.clinica_id:
        return jsonify({'success': False, 'message': 'Apenas protocolos da clínica podem ser editados por esta aba.'}), 403

    payload = request.get_json(silent=True) or {}
    try:
        protocolo = _apply_protocol_payload(protocolo, payload, consulta)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400

    log_suggestion_event(
        consulta_id=consulta.id,
        protocolo_id=protocolo.id,
        actor_user_id=current_user.id,
        tipo_item='protocolo',
        acao='updated',
        titulo_item=protocolo.nome,
        justificativa=protocolo.suspeita_principal,
        payload={'origem': 'consulta_inline'},
    )
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Protocolo atualizado com sucesso.',
        'protocol': _serialize_clinical_protocol(protocolo),
        'clinical_suspicion_options': _clinical_suspicion_options(consulta.clinica_id),
    })


@bp.route('/consulta/<int:animal_id>')
@login_required
def consulta_direct(animal_id):
    worker_role = getattr(current_user, 'worker', None)
    if not (is_veterinarian(current_user) or worker_role == 'colaborador'):
        abort(403)

    animal = get_animal_or_404(animal_id)
    tutor = animal.owner
    clinica_id = current_user_clinic_id()

    appointment_id = request.args.get('appointment_id', type=int)
    appointment = None
    if appointment_id:
        appointment = Appointment.query.get_or_404(appointment_id)
        if appointment.animal_id != animal.id:
            abort(404)
        appointment_clinic_id = appointment.clinica_id or (
            appointment.veterinario.clinica_id if appointment.veterinario else None
        )
        if not appointment_clinic_id and getattr(appointment, 'animal', None):
            appointment_clinic_id = appointment.animal.clinica_id
        if appointment_clinic_id:
            ensure_clinic_access(appointment_clinic_id)
            if clinica_id and appointment_clinic_id != clinica_id:
                abort(404)
            if not clinica_id:
                clinica_id = appointment_clinic_id

    edit_id = request.args.get('c', type=int)
    edit_mode = False

    consulta = None
    if is_veterinarian(current_user):
        consulta_created = False
        appointment_updated = False

        if edit_id:
            consulta = get_consulta_or_404(edit_id)
            edit_mode = True
        else:
            if appointment and appointment.consulta_id:
                consulta_vinculada = get_consulta_or_404(appointment.consulta_id)
                if consulta_vinculada.status != 'finalizada':
                    consulta = consulta_vinculada

            if not consulta:
                # Only search for existing consulta if we have a valid clinic_id
                if clinica_id:
                    consulta = (
                        Consulta.query
                        .filter_by(animal_id=animal.id, status='in_progress', clinica_id=clinica_id)
                        .first()
                    )

            if not consulta:
                # Require clinic_id to create new consultas
                if not clinica_id:
                    flash('Não foi possível determinar a clínica. Verifique seu cadastro de veterinário.', 'danger')
                    return redirect(url_for('index'))
                consulta = Consulta(
                    animal_id=animal.id,
                    created_by=current_user.id,
                    clinica_id=clinica_id,
                    status='in_progress'
                )
                db.session.add(consulta)
                consulta_created = True

        if appointment and consulta:
            if appointment.consulta_id != consulta.id:
                appointment.consulta = consulta
                appointment_updated = True

            vet_profile = getattr(current_user, 'veterinario', None)
            if (
                vet_profile
                and appointment.veterinario_id == getattr(vet_profile, 'id', None)
                and appointment.status not in {'completed', 'canceled'}
                and appointment.status != 'accepted'
            ):
                appointment.status = 'accepted'
                appointment_updated = True

        if consulta_created or appointment_updated:
            db.session.commit()
            if appointment_updated:
                _invalidate_cached_context(current_user.id, 'pending_appointment_count')
    else:
        consulta = None

    historico = []
    if is_veterinarian(current_user) and clinica_id:
        historico = (
            Consulta.query
            .filter_by(animal_id=animal.id, status='finalizada', clinica_id=clinica_id)
            .order_by(Consulta.created_at.desc())
            .limit(10)
            .all()
        )

    clinic_scope_id = clinica_id
    blocos_orcamento = _clinic_orcamento_blocks(animal, clinic_scope_id)
    blocos_prescricao = _clinic_prescricao_blocks(animal, clinic_scope_id)

    tipos_racao = list_rations()
    marcas_existentes = sorted(set([t.marca for t in tipos_racao if t.marca]))
    linhas_existentes = sorted(set([t.linha for t in tipos_racao if t.linha]))

    # 🆕 Carregar listas de espécies e raças para o formulário
    species_list = list_species()
    breed_list = list_breeds()

    form = AnimalForm(obj=animal)
    tutor_form = EditProfileForm(obj=tutor)

    appointment_form = None
    if consulta:
        from models import Veterinario

        appointment_form = AppointmentForm(clinic_ids=clinica_id, tutor=tutor)
        appointment_form.populate_animals(
            [animal],
            restrict_tutors=True,
            selected_tutor_id=getattr(animal, 'user_id', None),
            allow_all_option=False,
        )
        appointment_form.animal_id.data = animal.id
        vet_obj = None
        if consulta.veterinario and getattr(consulta.veterinario, "veterinario", None):
            vet_obj = consulta.veterinario.veterinario
        if vet_obj:
            vets = (
                Veterinario.query.filter_by(
                    clinica_id=current_user_clinic_id()
                ).all()
            )
            appointment_form.veterinario_id.choices = [
                (v.id, v.user.name) for v in vets
            ]
            appointment_form.veterinario_id.data = vet_obj.id

    # Idade e unidade (anos/meses)
    idade = ''
    idade_unidade = ''
    if animal.date_of_birth:
        delta = relativedelta(date.today(), animal.date_of_birth)
        if delta.years > 0:
            idade = delta.years
            idade_unidade = 'ano' if delta.years == 1 else 'anos'
        else:
            idade = delta.months
            idade_unidade = 'mês' if delta.months == 1 else 'meses'
    elif animal.age:
        partes = str(animal.age).split()
        try:
            idade = int(partes[0])
        except (ValueError, IndexError):
            idade = ''
        if len(partes) > 1:
            idade_unidade = partes[1]

    servicos = []
    if clinica_id:
        servicos = (
            ServicoClinica.query
            .filter_by(clinica_id=clinica_id)
            .order_by(ServicoClinica.descricao)
            .all()
        )

    worker_role = 'veterinario' if is_veterinarian(current_user) else current_user.worker
    clinical_suspicion_options = _clinical_suspicion_options(clinica_id)

    return render_template(
        'consulta_qr.html',
        animal=animal,
        tutor=tutor,
        consulta=consulta,
        historico_consultas=historico,
        edit_mode=edit_mode,
        worker=worker_role,
        tipos_racao=tipos_racao,
        marcas_existentes=marcas_existentes,
        linhas_existentes=linhas_existentes,
        species_list=species_list,
        breed_list=breed_list,
        form=form,
        tutor_form=tutor_form,
        animal_idade=idade,
        animal_idade_unidade=idade_unidade,
        servicos=servicos,
        appointment_form=appointment_form,
        blocos_orcamento=blocos_orcamento,
        blocos_prescricao=blocos_prescricao,
        clinic_scope_id=clinic_scope_id,
        clinical_suspicion_options=clinical_suspicion_options,
    )


@bp.route('/finalizar_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def finalizar_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem finalizar consultas.', 'danger')
        return redirect(url_for('index'))

    outcome = finalize_consulta_flow(
        consulta=consulta,
        actor_id=current_user.id,
        actor_vet_id=getattr(getattr(current_user, "veterinario", None), "id", None),
        clinic_id=current_user_clinic_id(),
    )
    if outcome.status == "blocked":
        flash(outcome.message, outcome.category)
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))
    if consulta.status != "finalizada":
        consulta.status = "finalizada"
        consulta.finalizada_em = utcnow()
        if consulta.appointment and consulta.appointment.status != "completed":
            consulta.appointment.status = "completed"
        db.session.commit()
    if outcome.status == "completed":
        flash(outcome.message, outcome.category)
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    flash(outcome.message, outcome.category)
    return render_template(
        'agendamentos/confirmar_retorno.html',
        consulta=consulta,
        form=outcome.form,
    )


@bp.route('/finalizar_consulta/<int:consulta_id>/fechar', methods=['POST'])
@login_required
def finalizar_consulta_e_fechar(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem finalizar consultas.', 'danger')
        return redirect(url_for('index'))

    outcome = finalize_consulta_flow(
        consulta=consulta,
        actor_id=current_user.id,
        actor_vet_id=getattr(getattr(current_user, "veterinario", None), "id", None),
        clinic_id=current_user_clinic_id(),
    )
    if outcome.status == "blocked":
        flash(outcome.message, outcome.category)
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id, c=consulta.id))
    if consulta.status != "finalizada":
        consulta.status = "finalizada"
        consulta.finalizada_em = utcnow()
        if consulta.appointment and consulta.appointment.status != "completed":
            consulta.appointment.status = "completed"
        db.session.commit()
    if outcome.status == "completed":
        flash(outcome.message, outcome.category)
        if consulta.appointment:
            return redirect(url_for('appointment_close', appointment_id=consulta.appointment.id))
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    flash(outcome.message, outcome.category)
    return render_template(
        'agendamentos/confirmar_retorno.html',
        consulta=consulta,
        form=outcome.form,
    )


@bp.route('/agendar_retorno/<int:consulta_id>', methods=['POST'])
@login_required
def agendar_retorno(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not is_veterinarian(current_user):
        abort(403)
    from models import Veterinario

    form = AppointmentForm(clinic_ids=consulta.clinica_id, tutor=consulta.animal.owner)
    form.populate_animals(
        [consulta.animal],
        restrict_tutors=True,
        selected_tutor_id=getattr(consulta.animal, 'user_id', None),
        allow_all_option=False,
    )
    vets = (
        Veterinario.query.filter_by(
            clinica_id=current_user_clinic_id()
        ).all()
    )
    form.veterinario_id.choices = [(v.id, v.user.name) for v in vets]
    if form.validate_on_submit():
        payload = ReturnAppointmentDTO(
            date=form.date.data,
            time=form.time.data,
            veterinarian_id=form.veterinario_id.data,
            reason=form.reason.data,
        )
        result = schedule_return_appointment(
            consulta=consulta,
            actor_id=current_user.id,
            actor_vet_id=getattr(getattr(current_user, "veterinario", None), "id", None),
            payload=payload,
        )
        if result.success:
            protocol_id = request.form.get('suggested_protocol_id', type=int)
            return_id = request.form.get('suggested_return_id', type=int)
            if protocol_id or return_id:
                log_suggestion_event(
                    consulta_id=consulta.id,
                    protocolo_id=protocol_id,
                    actor_user_id=current_user.id,
                    tipo_item='retorno',
                    acao='scheduled',
                    titulo_item='Retorno sugerido agendado',
                    justificativa=form.reason.data,
                    payload={
                        'return_id': return_id,
                        'date': form.date.data.isoformat() if form.date.data else None,
                        'time': form.time.data.isoformat() if form.time.data else None,
                    },
                )
                db.session.commit()
        flash(result.message, result.category)
    else:
        flash('Erro ao agendar retorno.', 'danger')
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@bp.route('/retorno/<int:appointment_id>/start', methods=['POST'])
@login_required
def iniciar_retorno(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)
    if not is_veterinarian(current_user):
        abort(403)
    consulta = Consulta(
        animal_id=appt.animal_id,
        created_by=current_user.id,
        clinica_id=appt.clinica_id or current_user_clinic_id(),
        status='in_progress',
        retorno_de_id=appt.consulta_id,
    )
    db.session.add(consulta)
    appt.status = 'completed'
    db.session.commit()
    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@bp.route('/consulta/<int:consulta_id>/deletar', methods=['POST'])
@login_required
def deletar_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal_id = consulta.animal_id
    if not is_veterinarian(current_user):
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir consultas.'), 403
        flash('Apenas veterinários podem excluir consultas.', 'danger')
        return redirect(url_for('index'))

    db.session.delete(consulta)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = render_template(
            'partials/historico_consultas.html',
            animal=animal,
            historico_consultas=animal.consultas
        )
        return jsonify(success=True, html=historico_html)

    flash('Consulta excluída!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@bp.route('/imprimir_consulta/<int:consulta_id>')
@login_required
def imprimir_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal = consulta.animal
    owner_access = _current_user_owns_animal(animal)
    tutor = animal.owner
    veterinario = consulta.veterinario
    clinica = consulta.clinica or (
        veterinario.veterinario.clinica if veterinario and veterinario.veterinario else None
    )

    return render_template(
        'orcamentos/imprimir_consulta.html',
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
        return_url=url_for('ficha_animal', animal_id=animal.id) if owner_access else url_for('consulta_direct', animal_id=animal.id),
    )


@bp.route('/update_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def update_consulta(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')

    if not is_veterinarian(current_user):
        message = 'Apenas veterinários podem editar a consulta.'
        flash(message, 'danger')
        if wants_json:
            return jsonify(success=False, message=message, category='danger'), 403
        return redirect(url_for('index'))

    # Ensure consulta has a clinic_id for proper isolation
    if not consulta.clinica_id:
        clinic_id = current_user_clinic_id()
        if clinic_id:
            consulta.clinica_id = clinic_id
        else:
            message = 'Consulta sem clínica associada. Verifique seu cadastro.'
            flash(message, 'danger')
            if wants_json:
                return jsonify(success=False, message=message, category='danger'), 400
            return redirect(url_for('index'))

    # Atualiza os campos
    consulta.queixa_principal = request.form.get('queixa_principal')
    consulta.historico_clinico = request.form.get('historico_clinico')
    consulta.exame_fisico = request.form.get('exame_fisico')
    consulta.suspeita_clinica = request.form.get('suspeita_clinica')
    consulta.conduta = request.form.get('conduta')

    # Se estiver editando uma consulta antiga
    if request.args.get('edit') == '1':
        db.session.commit()
        message = 'Consulta atualizada com sucesso!'
        flash(message, 'success')

    else:
        # Salva, finaliza e cria nova automaticamente
        consulta.status = 'finalizada'
        consulta.finalizada_em = utcnow()
        appointment = consulta.appointment
        if appointment and appointment.status != 'completed':
            appointment.status = 'completed'
        db.session.commit()

        nova = Consulta(
            animal_id=consulta.animal_id,
            created_by=current_user.id,
            clinica_id=consulta.clinica_id,
            status='in_progress'
        )
        db.session.add(nova)
        db.session.commit()

        message = 'Consulta salva e movida para o histórico!'
        flash(message, 'success')

    if wants_json:
        historico = (
            Consulta.query
            .filter_by(
                animal_id=consulta.animal_id,
                status='finalizada',
                clinica_id=consulta.clinica_id,
            )
            .order_by(Consulta.created_at.desc())
            .all()
        )
        html = render_template(
            'partials/historico_consultas.html',
            animal=consulta.animal,
            historico_consultas=historico,
        )
        appointments_html = None
        if consulta.appointment and consulta.clinica_id:
            clinic_appointments = (
                Appointment.query
                .filter_by(clinica_id=consulta.clinica_id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            appointments_grouped = group_appointments_by_day(clinic_appointments)
            appointments_html = render_template(
                'partials/appointments_table.html',
                appointments_grouped=appointments_grouped,
            )
        return jsonify(
            success=True,
            message=message,
            category='success',
            html=html,
            appointments_html=appointments_html,
        )

    return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))


@bp.route('/consulta/<int:consulta_id>/prescricao', methods=['POST'])
@login_required
def criar_prescricao(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem adicionar prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    medicamento = request.form.get('medicamento')
    dosagem = request.form.get('dosagem')
    frequencia = request.form.get('frequencia')
    duracao = request.form.get('duracao')
    observacoes = request.form.get('observacoes')

    # Se houver campos estruturados (dose, frequência ou duração),
    # ignoramos o campo de texto livre para evitar salvar ambos
    if dosagem or frequencia or duracao:
        observacoes = None
    # Caso contrário, se apenas o texto livre foi preenchido, os
    # campos estruturados não devem ser persistidos
    elif observacoes:
        dosagem = frequencia = duracao = None

    if not medicamento:
        flash('É necessário informar o nome do medicamento.', 'warning')
        return redirect(request.referrer)

    nova_prescricao = Prescricao(
        consulta_id=consulta.id,
        medicamento=medicamento,
        dosagem=dosagem,
        frequencia=frequencia,
        duracao=duracao,
        observacoes=observacoes
    )

    db.session.add(nova_prescricao)
    db.session.commit()

    flash('Prescrição adicionada com sucesso!', 'success')
    # criar_prescricao
    return redirect(url_for('consulta_qr', animal_id=Consulta.query.get(consulta_id).animal_id))


@bp.route('/prescricao/<int:prescricao_id>/deletar', methods=['POST'])
@login_required
def deletar_prescricao(prescricao_id):
    prescricao = Prescricao.query.get_or_404(prescricao_id)
    clinic_id = None
    if getattr(prescricao, 'bloco', None):
        clinic_id = prescricao.bloco.clinica_id
    if not clinic_id and prescricao.animal:
        clinic_id = prescricao.animal.clinica_id
    ensure_clinic_access(clinic_id)
    animal_id = prescricao.animal_id

    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    db.session.delete(prescricao)
    db.session.commit()
    flash('Prescrição removida com sucesso!', 'info')
    return redirect(url_for('consulta_qr', animal_id=animal_id))


@bp.route("/medicamento", methods=["POST"])
@login_required
def criar_medicamento():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()

    if not nome:
        return jsonify({"success": False, "message": "Nome é obrigatório"}), 400

    try:
        novo = Medicamento(
            nome=nome,
            principio_ativo=(data.get("principio_ativo") or "").strip() or None,
            classificacao=(data.get("classificacao") or "").strip() or None,
            via_administracao=(data.get("via_administracao") or "").strip() or None,
            dosagem_recomendada=(data.get("dosagem_recomendada") or "").strip() or None,
            frequencia=(data.get("frequencia") or "").strip() or None,
            duracao_tratamento=(data.get("duracao_tratamento") or "").strip() or None,
            observacoes=(data.get("observacoes") or "").strip() or None,
            bula=(data.get("bula") or "").strip() or None,
            created_by=current_user.id,
        )
        db.session.add(novo)
        db.session.commit()
        _clear_medication_search_cache()
        return jsonify({
            "success": True,
            "id": novo.id,
            "nome": novo.nome,
            "classificacao": novo.classificacao,
            "principio_ativo": novo.principio_ativo,
            "via_administracao": novo.via_administracao,
            "dosagem_recomendada": novo.dosagem_recomendada,
            "frequencia": novo.frequencia,
            "duracao_tratamento": novo.duracao_tratamento,
            "observacoes": novo.observacoes,
            "bula": novo.bula,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@bp.route("/medicamento/<int:med_id>", methods=["PUT", "DELETE"])
@login_required
def alterar_medicamento(med_id):
    medicamento = Medicamento.query.get_or_404(med_id)
    if medicamento.created_by != current_user.id and getattr(current_user, 'role', '') != 'admin':
        return jsonify({"success": False, "message": "Permissão negada"}), 403

    if request.method == "DELETE":
        db.session.delete(medicamento)
        db.session.commit()
        _clear_medication_search_cache()
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    campos = {
        "nome": "nome",
        "principio_ativo": "principio_ativo",
        "classificacao": "classificacao",
        "via_administracao": "via_administracao",
        "dosagem_recomendada": "dosagem_recomendada",
        "frequencia": "frequencia",
        "duracao_tratamento": "duracao_tratamento",
        "observacoes": "observacoes",
        "bula": "bula",
    }
    for key, attr in campos.items():
        if key in data:
            val = (data.get(key) or "").strip()
            setattr(medicamento, attr, val or None)

    db.session.commit()
    _clear_medication_search_cache()
    return jsonify({"success": True})


@bp.route("/apresentacao_medicamento", methods=["POST"])
def criar_apresentacao_medicamento():
    data = request.get_json(silent=True) or {}
    medicamento_id = data.get("medicamento_id")
    forma = (data.get("forma") or "").strip()
    concentracao = (data.get("concentracao") or "").strip()

    if not medicamento_id or not forma or not concentracao:
        return jsonify({"success": False, "message": "Dados obrigatórios ausentes"}), 400

    try:
        apresentacao = ApresentacaoMedicamento(
            medicamento_id=int(medicamento_id),
            forma=forma,
            concentracao=concentracao,
        )
        db.session.add(apresentacao)
        db.session.commit()
        _clear_medication_search_cache()
        return jsonify({"success": True, "id": apresentacao.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@bp.route("/medicamento/<int:med_id>/detalhe")
def detalhe_medicamento_busca(med_id):
    med = (
        Medicamento.query
        .options(
            selectinload(Medicamento.doses),
            selectinload(Medicamento.apresentacoes),
        )
        .get_or_404(med_id)
    )
    nome_exibicao = (request.args.get("nome_exibicao") or "").strip() or None
    nome_comercial_filtro = (request.args.get("nome_comercial_filtro") or "").strip() or None

    from services.bulario import serializar_medicamento_busca

    return jsonify(
        serializar_medicamento_busca(
            med,
            nome_exibicao=nome_exibicao,
            nome_comercial_filtro=nome_comercial_filtro,
        )
    )


@bp.route("/buscar_medicamentos")
def buscar_medicamentos():
    q = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", 15, type=int) or 15
    limit = min(max(limit, 1), 20)

    if len(q) < 2:
        return jsonify([])

    q_lower = q.lower()
    q_norm = unicodedata.normalize("NFKD", q_lower)
    q_norm = "".join(c for c in q_norm if not unicodedata.combining(c))

    def _norm_busca(valor):
        texto = unicodedata.normalize("NFKD", str(valor or "").lower())
        texto = "".join(c for c in texto if not unicodedata.combining(c))
        texto = re.sub(r"\bneom?c?icina\b|\bneonicina\b|\bneomicicina\b", "neomicina", texto)
        return texto

    q_norm = _norm_busca(q_norm)
    tokens_busca = [
        token
        for token in re.findall(r"[a-z0-9]{3,}", q_norm)
        if token not in {"com", "para", "por", "uso", "mg", "ml"}
    ]

    from services.species_ranking import (
        resolver_species_scope_do_animal,
        ordenar_por_species_scope,
    )
    scope_alvo = resolver_species_scope_do_animal(request.args.get('animal_id'))
    cache_key = (q_norm, tuple(tokens_busca), scope_alvo or "", limit)
    cached = _get_medication_search_cache(cache_key)
    if cached is not None:
        return jsonify(cached)

    # Busca ampla por nome OU princípio ativo — pool maior para poder re-ranquear
    like = f"%{q}%"
    filtros_busca = [
        Medicamento.nome.ilike(like),
        Medicamento.principio_ativo.ilike(like),
        cast(Medicamento.conteudo_estruturado, Text).ilike(like),
    ]
    for token in tokens_busca:
        token_like = f"%{token}%"
        filtros_busca.extend([
            Medicamento.nome.ilike(token_like),
            Medicamento.principio_ativo.ilike(token_like),
            cast(Medicamento.conteudo_estruturado, Text).ilike(token_like),
        ])

    resultados = (
        Medicamento.query
        .options(
            load_only(
                Medicamento.id,
                Medicamento.nome,
                Medicamento.principio_ativo,
                Medicamento.classificacao,
                Medicamento.via_administracao,
                Medicamento.dosagem_recomendada,
                Medicamento.frequencia,
                Medicamento.duracao_tratamento,
                Medicamento.conteudo_estruturado,
                Medicamento.species_scope,
            ),
            selectinload(Medicamento.doses).load_only(
                DoseMedicamento.id,
                DoseMedicamento.medicamento_id,
            ),
            selectinload(Medicamento.apresentacoes).load_only(
                ApresentacaoMedicamento.id,
                ApresentacaoMedicamento.medicamento_id,
            ),
        )
        .filter(or_(*filtros_busca))
        .order_by(Medicamento.nome)
        .limit(120)
        .all()
    )

    # Filtrar entradas "orphan": sem principio_ativo E sem doses, quando já existe
    # uma entrada canônica melhor no pool de resultados.
    principios_com_doses = {
        m.principio_ativo.lower()
        for m in resultados
        if m.principio_ativo and m.doses
    }
    filtrados = []
    for m in resultados:
        if not m.principio_ativo and not m.doses and principios_com_doses:
            if any(pa in m.nome.lower() for pa in principios_com_doses):
                continue
        filtrados.append(m)

    def _produto_vetsmart_match_info(m):
        conteudo = getattr(m, "conteudo_estruturado", None) or {}
        produtos = conteudo.get("produtos_vetsmart") if isinstance(conteudo, dict) else []
        if not isinstance(produtos, list):
            return None
        for prod in produtos:
            if not isinstance(prod, dict):
                continue
            if any(q_norm in _norm_busca(prod.get(campo)) for campo in ("nome", "fabricante", "principio_ativo")):
                return prod
            produto_haystack = " ".join(_norm_busca(prod.get(campo)) for campo in ("nome", "fabricante", "principio_ativo"))
            if tokens_busca and all(token in produto_haystack for token in tokens_busca):
                return prod
        return None

    def _haystack_medicamento(m):
        partes = [
            m.nome,
            m.principio_ativo,
            m.classificacao,
            m.via_administracao,
            m.dosagem_recomendada,
            m.frequencia,
            m.duracao_tratamento,
        ]
        conteudo = getattr(m, "conteudo_estruturado", None) or {}
        if isinstance(conteudo, dict):
            produtos = conteudo.get("produtos_vetsmart")
            if isinstance(produtos, list):
                for prod in produtos:
                    if isinstance(prod, dict):
                        partes.extend([prod.get("nome"), prod.get("fabricante"), prod.get("principio_ativo")])
        else:
            partes.append(conteudo)
        return " ".join(_norm_busca(parte) for parte in partes if parte)

    def _score(m):
        # Prioridade: (1) tem doses estruturadas, (2) match no início do nome,
        # (3) princípio ativo coincide exatamente, (4) tem dados básicos preenchidos
        tem_doses = 1 if m.doses else 0
        nome_norm = _norm_busca(m.nome)
        pa_norm = _norm_busca(m.principio_ativo)
        prefixo = 1 if nome_norm.startswith(q_norm) else 0
        pa_exato = 1 if pa_norm == q_norm else 0
        produto_match = _produto_vetsmart_match_info(m)
        produto_match_score = 1 if produto_match else 0
        haystack = _haystack_medicamento(m)
        todos_tokens = 1 if tokens_busca and all(token in haystack for token in tokens_busca) else 0
        qtd_tokens = sum(1 for token in tokens_busca if token in haystack)
        tem_dados = 1 if (m.via_administracao or m.dosagem_recomendada or m.frequencia) else 0
        return (todos_tokens, produto_match_score, qtd_tokens, tem_doses, prefixo, pa_exato, tem_dados)

    filtrados.sort(key=_score, reverse=True)

    # Re-ranqueamento opcional pela espécie do animal sob consulta. Não filtra
    # nada — apenas eleva itens compatíveis.
    if scope_alvo:
        filtrados = ordenar_por_species_scope(filtrados, scope_alvo)

    from services.bulario import serializar_medicamento_autocomplete
    saida = []
    for med in filtrados[:limit]:
        item = serializar_medicamento_autocomplete(med)
        produto_match = _produto_vetsmart_match_info(med)
        if produto_match:
            item["produto_match_nome"] = produto_match.get("nome")
            item["produto_match_fabricante"] = produto_match.get("fabricante")
            item["produto_match_vetsmart_id"] = produto_match.get("vetsmart_produto_id")
            item["nome_exibicao_busca"] = produto_match.get("nome") or item.get("nome")
        saida.append(item)
    return jsonify(_set_medication_search_cache(cache_key, saida))


@bp.route("/buscar_apresentacoes")
def buscar_apresentacoes():
    try:
        medicamento_id = request.args.get("medicamento_id")
        q = (request.args.get("q") or "").strip()

        if not medicamento_id or not medicamento_id.isdigit():
            return jsonify([])

        # Log for debugging
        print(f"Searching for presentations of medicamento_id={medicamento_id}, query='{q}'")

        apresentacoes = (
            ApresentacaoMedicamento.query
            .filter(
                ApresentacaoMedicamento.medicamento_id == int(medicamento_id),
                (ApresentacaoMedicamento.forma.ilike(f"%{q}%")) |
                (ApresentacaoMedicamento.concentracao.ilike(f"%{q}%"))
            )
            .all()
        )

        return jsonify([
            {"forma": a.forma, "concentracao": a.concentracao}
            for a in apresentacoes
        ])

    except Exception as e:
        print(f"[ERROR] /buscar_apresentacoes: {str(e)}")
        return jsonify({"error": str(e)}), 500


@bp.route("/medicamentos_favoritos", methods=["GET"])
@login_required
def listar_medicamentos_favoritos():
    """Retorna os medicamentos favoritados pelo veterinário logado."""
    from models.base import MedicamentoFavorito
    favs = (
        MedicamentoFavorito.query
        .filter_by(user_id=current_user.id)
        .order_by(MedicamentoFavorito.criado_em.desc())
        .all()
    )
    med_ids = [f.medicamento_id for f in favs]
    meds = {}
    if med_ids:
        meds = {
            med.id: med
            for med in (
                Medicamento.query
                .options(
                    selectinload(Medicamento.doses).load_only(
                        DoseMedicamento.id,
                        DoseMedicamento.medicamento_id,
                    ),
                    selectinload(Medicamento.apresentacoes).load_only(
                        ApresentacaoMedicamento.id,
                        ApresentacaoMedicamento.medicamento_id,
                    ),
                )
                .filter(Medicamento.id.in_(med_ids))
                .all()
            )
        }
    from services.bulario import serializar_medicamento_autocomplete
    resultado = []
    for f in favs:
        med = meds.get(f.medicamento_id)
        if med:
            entry = serializar_medicamento_autocomplete(med)
            entry["favorito"] = True
            resultado.append(entry)
    return jsonify(resultado)


@bp.route("/medicamentos_favoritos/<int:med_id>", methods=["POST", "DELETE"])
@login_required
def toggle_medicamento_favorito(med_id):
    """Adiciona (POST) ou remove (DELETE) um medicamento dos favoritos."""
    from models.base import MedicamentoFavorito
    from sqlalchemy.exc import IntegrityError

    med = Medicamento.query.get_or_404(med_id)

    if request.method == "POST":
        try:
            fav = MedicamentoFavorito(user_id=current_user.id, medicamento_id=med_id)
            db.session.add(fav)
            db.session.commit()
            return jsonify({"favorito": True, "id": med_id})
        except IntegrityError:
            db.session.rollback()
            return jsonify({"favorito": True, "id": med_id})  # já era favorito
    else:  # DELETE
        MedicamentoFavorito.query.filter_by(
            user_id=current_user.id, medicamento_id=med_id
        ).delete()
        db.session.commit()
        return jsonify({"favorito": False, "id": med_id})


@bp.route("/medicamentos_frequentes")
@login_required
def medicamentos_frequentes():
    """Retorna os medicamentos mais prescritos pelo veterinário logado.

    Usa prescricao_alias_medicamento como cache. Nomes não resolvidos passam por
    5 estratégias de matching (exato → normalizado → prefixo → variante → substring)
    e o resultado é persistido para requisições futuras.
    """
    try:
        from sqlalchemy import text as sql_text
        from services.prescricao_alias import resolver_e_persistir
        from services.bulario import serializar_medicamento_autocomplete

        rows = db.session.execute(sql_text("""
            SELECT p.medicamento, COUNT(*) AS total
            FROM prescricao p
            JOIN bloco_prescricao bp ON bp.id = p.bloco_id
            WHERE bp.saved_by_id = :uid
            GROUP BY p.medicamento
            ORDER BY total DESC
            LIMIT 40
        """), {"uid": current_user.id}).fetchall()

        saida = []
        ids_incluidos = set()
        nomes_vistos = set()

        for nome_prescrito, total in rows:
            nome_key = nome_prescrito.strip().lower()
            if nome_key in nomes_vistos:
                continue

            med_id = resolver_e_persistir(nome_prescrito, db.session, db)

            if med_id:
                if med_id in ids_incluidos:
                    nomes_vistos.add(nome_key)
                    continue
                med = (
                    Medicamento.query
                    .options(
                        selectinload(Medicamento.doses).load_only(
                            DoseMedicamento.id,
                            DoseMedicamento.medicamento_id,
                        ),
                        selectinload(Medicamento.apresentacoes).load_only(
                            ApresentacaoMedicamento.id,
                            ApresentacaoMedicamento.medicamento_id,
                        ),
                    )
                    .get(med_id)
                )
                if med:
                    entry = serializar_medicamento_autocomplete(med)
                    entry["total_prescricoes"] = total
                    entry["nome_prescrito_original"] = nome_prescrito
                    saida.append(entry)
                    ids_incluidos.add(med_id)
            else:
                saida.append({"id": None, "nome": nome_prescrito, "total_prescricoes": total})

            nomes_vistos.add(nome_key)
            if len(saida) >= 12:
                break

        return jsonify(saida)
    except Exception as e:
        print(f"[ERROR] /medicamentos_frequentes: {e}")
        import traceback; traceback.print_exc()
        return jsonify([])


@bp.route('/consulta/<int:consulta_id>/historico_prescricoes', methods=['GET'])
@login_required
def historico_prescricoes_partial(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    clinic_id = (
        consulta.clinica_id
        or current_user_clinic_id()
        or getattr(consulta.animal, 'clinica_id', None)
    )

    if not clinic_id:
        return jsonify({'success': False, 'message': 'Consulta sem clínica definida.'}), 400

    ensure_clinic_access(clinic_id)

    historico_html = _render_prescricao_history(consulta.animal, clinic_id)
    return jsonify({'success': True, 'html': historico_html})


@bp.route('/animal/<int:animal_id>/historico_exames', methods=['GET'])
@login_required
def historico_exames_partial(animal_id):
    animal = get_animal_or_404(animal_id)
    clinic_id = request.args.get('clinica_id', type=int) or getattr(animal, 'clinica_id', None) or current_user_clinic_id()

    if clinic_id:
        ensure_clinic_access(clinic_id)

    historico_html = render_template(
        'partials/historico_exames.html',
        animal=animal,
        clinic_scope_id=clinic_id,
    )
    return jsonify({'success': True, 'html': historico_html})


@bp.route('/animal/<int:animal_id>/historico_prescricoes', methods=['GET'])
@login_required
def recarregar_historico_prescricoes_ajax(animal_id):
    """Load prescription history for an animal by animal_id and clinic_id."""
    animal = get_animal_or_404(animal_id)
    clinic_id = request.args.get('clinic_id', type=int) or getattr(animal, 'clinica_id', None) or current_user_clinic_id()

    if clinic_id:
        ensure_clinic_access(clinic_id)

    historico_html = _render_prescricao_history(animal, clinic_id)
    return jsonify({'success': True, 'html': historico_html})


@bp.route('/consulta/<int:consulta_id>/prescricao/lote', methods=['POST'])
@login_required
def salvar_prescricoes_lote(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    data = request.get_json(silent=True) or {}
    novas_prescricoes = data.get('prescricoes', [])

    for item in novas_prescricoes:
        nova = Prescricao(
            animal_id=consulta.animal_id,
            medicamento=item.get('nome'),
            dosagem=item.get('dosagem'),
            frequencia=item.get('frequencia'),
            duracao=item.get('duracao'),
            observacoes=item.get('observacoes')
        )
        db.session.add(nova)

    db.session.commit()

    historico_html = _render_prescricao_history(consulta.animal, consulta.clinica_id)
    return jsonify({'status': 'ok', 'historico_html': historico_html})


@bp.route('/consulta/<int:consulta_id>/bloco_prescricao', methods=['POST'])
@login_required
def salvar_bloco_prescricao(consulta_id):
    consulta = get_consulta_or_404(consulta_id)

    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem prescrever.'}), 403

    dados = request.get_json(silent=True) or {}
    lista_prescricoes = dados.get('prescricoes') or []
    instrucoes = _normalizar_instrucoes_prescricao(dados.get('instrucoes_gerais'))
    instrucoes_texto = instrucoes

    if not lista_prescricoes and not instrucoes_texto.strip():
        return jsonify({'success': False, 'message': 'Informe ao menos uma prescrição ou instruções gerais.'}), 400

    clinic_id = (
        consulta.clinica_id
        or current_user_clinic_id()
        or getattr(consulta.animal, 'clinica_id', None)
    )
    if not clinic_id:
        return jsonify({'success': False, 'message': 'Consulta sem clínica definida.'}), 400

    ensure_clinic_access(clinic_id)
    if consulta.clinica_id and consulta.clinica_id != clinic_id:
        return jsonify({'success': False, 'message': 'Consulta pertence a outra clínica.'}), 400
    if not consulta.clinica_id:
        consulta.clinica_id = clinic_id

    # ⬇️ Aqui é onde a instrução geral precisa ser usada
    bloco = BlocoPrescricao(
        animal_id=consulta.animal_id,
        instrucoes_gerais=instrucoes,
        clinica_id=clinic_id,
    )
    bloco.saved_by = current_user
    bloco.saved_by_id = current_user.id
    db.session.add(bloco)
    db.session.flush()  # Garante o ID do bloco

    for item in lista_prescricoes:
        dosagem = item.get('dosagem')
        frequencia = item.get('frequencia')
        duracao = item.get('duracao')
        observacoes = item.get('observacoes')

        # Se qualquer campo estruturado estiver presente, descartamos o texto livre
        if dosagem or frequencia or duracao:
            observacoes = None
        # Caso contrário, usamos apenas o texto livre e ignoramos os outros
        elif observacoes:
            dosagem = frequencia = duracao = None

        nova = Prescricao(
            animal_id=consulta.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=dosagem,
            frequencia=frequencia,
            duracao=duracao,
            observacoes=observacoes
        )
        db.session.add(nova)

    db.session.commit()

    # Recarrega o animal para garantir que as prescrições recém-criadas
    # apareçam no histórico renderizado logo após o commit.
    animal_atualizado = Animal.query.get(consulta.animal_id)
    historico_html = _render_prescricao_history(animal_atualizado, clinic_id)
    return jsonify({
        'success': True,
        'message': 'Prescrições salvas com sucesso!',
        'html': historico_html
    })


@bp.route('/bloco_prescricao/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)
    if not is_veterinarian(current_user):
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir prescrições.'), 403
        flash('Apenas veterinários podem excluir prescrições.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    clinic_id = bloco.clinica_id
    db.session.delete(bloco)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = _render_prescricao_history(animal, clinic_id)
        return jsonify(success=True, html=historico_html)

    flash('Bloco de prescrição excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@bp.route('/bloco_prescricao/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)

    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem editar prescrições.', 'danger')
        return redirect(url_for('index'))

    return render_template('orcamentos/editar_bloco.html', bloco=bloco)


@bp.route('/bloco_prescricao/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    ensure_clinic_access(bloco.clinica_id)

    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403

    data = request.get_json(silent=True) or {}
    novos_medicamentos = data.get('medicamentos', [])
    instrucoes = _normalizar_instrucoes_prescricao(data.get('instrucoes_gerais'))

    # Limpa os medicamentos atuais do bloco
    for p in bloco.prescricoes:
        db.session.delete(p)

    # Adiciona os novos medicamentos ao bloco
    for item in novos_medicamentos:
        dosagem = item.get('dosagem')
        frequencia = item.get('frequencia')
        duracao = item.get('duracao')
        observacoes = item.get('observacoes')

        # Se qualquer campo estruturado estiver presente, descartamos o texto livre
        if dosagem or frequencia or duracao:
            observacoes = None
        # Caso contrário, usamos apenas o texto livre e ignoramos os outros
        elif observacoes:
            dosagem = frequencia = duracao = None

        nova = Prescricao(
            animal_id=bloco.animal_id,
            bloco_id=bloco.id,
            medicamento=item.get('medicamento'),
            dosagem=dosagem,
            frequencia=frequencia,
            duracao=duracao,
            observacoes=observacoes
        )
        db.session.add(nova)

    bloco.instrucoes_gerais = instrucoes
    bloco.saved_by = current_user
    bloco.saved_by_id = current_user.id
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/bloco_prescricao/<int:bloco_id>/imprimir')
@login_required
def imprimir_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    animal = bloco.animal
    owner_access = _current_user_owns_animal(animal)
    if not owner_access:
        ensure_clinic_access(bloco.clinica_id)

    if not owner_access and not is_veterinarian(current_user):
        flash('Apenas veterinários podem imprimir prescrições.', 'danger')
        return redirect(url_for('index'))

    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else bloco.saved_by
    if not veterinario and is_veterinarian(current_user):
        veterinario = current_user
    clinica = consulta.clinica if consulta and consulta.clinica else (
        veterinario.veterinario.clinica if veterinario and getattr(veterinario, "veterinario", None) else None
    )
    if not clinica:
        clinica = bloco.clinica
    salvo_por = bloco.saved_by or veterinario
    prescription_next_url = url_for('imprimir_bloco_prescricao', bloco_id=bloco.id)
    prescription_public_url = url_for('imprimir_bloco_prescricao', bloco_id=bloco.id, _external=True)
    first_access_url = url_for('first_access', next=prescription_next_url, _external=True)
    if tutor:
        first_access_url = _first_access_url_for_user(
            tutor,
            next_url=prescription_next_url,
            _external=True,
        )

    acompanhamento = bloco.acompanhamento
    pode_ativar_acompanhamento = acompanhamento is None and is_veterinarian(current_user)
    pode_enviar_assinatura = is_veterinarian(current_user)
    tratamento_first_access_url = None
    if acompanhamento:
        tratamento_next_url = url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id)
        tratamento_first_access_url = url_for('first_access', next=tratamento_next_url, _external=True)
        if tutor:
            tratamento_first_access_url = _first_access_url_for_user(
                tutor,
                next_url=tratamento_next_url,
                _external=True,
            )

    return render_template(
        'orcamentos/imprimir_bloco.html',
        bloco=bloco,
        consulta=consulta,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        salvo_por=salvo_por,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
        first_access_url=first_access_url,
        prescription_public_url=prescription_public_url,
        acompanhamento=acompanhamento,
        pode_ativar_acompanhamento=pode_ativar_acompanhamento,
        pode_enviar_assinatura=pode_enviar_assinatura,
        tratamento_first_access_url=tratamento_first_access_url,
        return_url=url_for('ficha_animal', animal_id=animal.id) if owner_access else url_for('consulta_direct', animal_id=animal.id),
    )


@bp.route('/bloco_prescricao/<int:bloco_id>/assinatura', methods=['POST'])
@login_required
def enviar_assinatura_bloco_prescricao(bloco_id):
    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    if not _current_user_owns_animal(bloco.animal):
        ensure_clinic_access(bloco.clinica_id)
    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem enviar a receita assinada.', 'danger')
        return redirect(url_for('imprimir_bloco_prescricao', bloco_id=bloco.id))

    arquivo = request.files.get('documento')
    if not arquivo or not arquivo.filename:
        flash('Selecione o arquivo da receita assinada.', 'warning')
        return redirect(url_for('imprimir_bloco_prescricao', bloco_id=bloco.id))

    original_name = secure_filename(arquivo.filename) or 'receita_assinada.pdf'
    stored_url = upload_to_s3(arquivo, f"{uuid.uuid4().hex}_{original_name}", folder='receitas_assinadas')
    if not stored_url:
        flash('Não foi possível enviar o arquivo. Tente novamente.', 'danger')
        return redirect(url_for('imprimir_bloco_prescricao', bloco_id=bloco.id))

    bloco.assinatura_arquivo_url = stored_url
    bloco.assinatura_enviada_em = now_in_brazil()
    bloco.assinatura_enviada_por_id = current_user.id
    db.session.commit()

    flash('Receita assinada enviada! Agora é só compartilhar pelo WhatsApp.', 'success')
    return redirect(url_for('imprimir_bloco_prescricao', bloco_id=bloco.id))


@bp.route('/bloco_prescricao/<int:bloco_id>/acompanhamento', methods=['POST'])
@login_required
def ativar_acompanhamento_tratamento(bloco_id):
    from services.tratamento import criar_acompanhamento

    bloco = BlocoPrescricao.query.get_or_404(bloco_id)
    if not _current_user_owns_animal(bloco.animal):
        ensure_clinic_access(bloco.clinica_id)
    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem ativar o acompanhamento.', 'danger')
        return redirect(request.referrer or url_for('index'))

    acompanhamento = bloco.acompanhamento
    if acompanhamento is None:
        from services.notifications import notify_user

        acompanhamento = criar_acompanhamento(bloco, current_user, now_in_brazil())
        db.session.commit()
        animal = bloco.animal
        tutor = animal.owner if animal else None
        if tutor:
            link_tutor = _first_access_url_for_user(
                tutor,
                next_url=url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id),
                _external=True,
            )
            notify_user(
                tutor,
                f'Acompanhe o tratamento de {animal.name} — PetOrlândia',
                (
                    f'Olá {tutor.name}! O tratamento de {animal.name} agora tem uma '
                    'página de acompanhamento: marque os medicamentos comprados, as '
                    'doses dadas e envie fotos da evolução.\n\n'
                    f'Acesse: {link_tutor}'
                ),
                kind='treatment',
            )
        flash('Acompanhamento ativado! Compartilhe o link com o tutor pelo WhatsApp.', 'success')
    return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id))


@bp.route('/tratamento/<int:tratamento_id>')
@login_required
def acompanhamento_tratamento(tratamento_id):
    from services.tratamento import resumo_progresso

    acompanhamento, is_owner = _tratamento_acompanhamento_or_404(tratamento_id)
    animal = acompanhamento.animal
    bloco = acompanhamento.bloco
    agora = now_in_brazil()
    hoje = agora.date()

    doses_hoje = []
    doses_atrasadas = []
    itens_view = []
    for item in acompanhamento.itens:
        previstas = 0
        feitas = 0
        proxima = None
        ultima_aplicacao = None
        for registro in item.registros:
            if registro.prevista_para is not None:
                previstas += 1
            if registro.status == 'feita':
                feitas += 1
                realizada = coerce_to_brazil_tz(registro.realizada_em) if registro.realizada_em else None
                if realizada and (ultima_aplicacao is None or realizada > ultima_aplicacao):
                    ultima_aplicacao = realizada
            elif registro.status == 'pendente' and registro.prevista_para is not None:
                prevista = coerce_to_brazil_tz(registro.prevista_para)
                if prevista.date() < hoje:
                    doses_atrasadas.append({'item': item, 'registro': registro, 'prevista': prevista})
                elif prevista.date() == hoje:
                    doses_hoje.append({'item': item, 'registro': registro, 'prevista': prevista})
                if proxima is None:
                    proxima = prevista
        itens_view.append({
            'item': item,
            'prescricao': item.prescricao,
            'previstas': previstas,
            'feitas': feitas,
            'percentual': round(100 * feitas / previstas) if previstas else None,
            'proxima': proxima,
            'ultima_aplicacao': ultima_aplicacao,
        })

    doses_hoje.sort(key=lambda d: d['prevista'])
    doses_atrasadas.sort(key=lambda d: d['prevista'])
    fotos = sorted(
        acompanhamento.fotos,
        key=lambda f: f.enviada_em or acompanhamento.data_inicio or agora,
        reverse=True,
    )

    tutor = animal.owner if animal else None
    is_vet_viewer = is_veterinarian(current_user)
    tutor_whatsapp_url = None
    if is_vet_viewer and tutor:
        tratamento_next_url = url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id)
        link_tutor = _first_access_url_for_user(tutor, next_url=tratamento_next_url, _external=True)
        mensagem = (
            f'Olá {tutor.name}! Acompanhe o tratamento de {animal.name} pelo PetOrlandia: '
            'marque as doses dadas e envie fotos da evolução.\n\n'
            f'Acesse: {link_tutor}'
        )
        tutor_whatsapp_url = _web_whatsapp_url(tutor.phone, mensagem)

    return render_template(
        'tratamento/acompanhamento.html',
        acompanhamento=acompanhamento,
        animal=animal,
        bloco=bloco,
        itens=itens_view,
        doses_hoje=doses_hoje,
        doses_atrasadas=doses_atrasadas,
        fotos=fotos,
        progresso=resumo_progresso(acompanhamento),
        is_owner=is_owner,
        is_vet_viewer=is_vet_viewer,
        tutor_whatsapp_url=tutor_whatsapp_url,
        hoje=hoje,
    )


@bp.route('/tratamento/item/<int:item_id>/comprado', methods=['POST'])
@login_required
def marcar_item_tratamento_comprado(item_id):
    item = ItemTratamento.query.get_or_404(item_id)
    acompanhamento, _ = _tratamento_acompanhamento_or_404(item.acompanhamento_id)
    if item.comprado_em:
        item.comprado_em = None
        item.comprado_por_id = None
    else:
        item.comprado_em = now_in_brazil()
        item.comprado_por_id = current_user.id
    db.session.commit()
    return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id) + '#compras')


@bp.route('/tratamento/registro/<int:registro_id>/marcar', methods=['POST'])
@login_required
def marcar_administracao_tratamento(registro_id):
    registro = AdministracaoRegistro.query.get_or_404(registro_id)
    item = registro.item
    acompanhamento, _ = _tratamento_acompanhamento_or_404(item.acompanhamento_id)

    status = (request.form.get('status') or '').strip()
    if status not in ('feita', 'pulada', 'pendente'):
        abort(400)

    registro.status = status
    if status == 'feita':
        registro.realizada_em = now_in_brazil()
        registro.realizada_por_id = current_user.id
    elif status == 'pulada':
        registro.realizada_em = None
        registro.realizada_por_id = current_user.id
    else:
        registro.realizada_em = None
        registro.realizada_por_id = None

    observacao = (request.form.get('observacao') or '').strip()
    if observacao:
        registro.observacao = observacao
    db.session.commit()
    return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id))


@bp.route('/tratamento/item/<int:item_id>/registrar', methods=['POST'])
@login_required
def registrar_aplicacao_tratamento(item_id):
    item = ItemTratamento.query.get_or_404(item_id)
    acompanhamento, _ = _tratamento_acompanhamento_or_404(item.acompanhamento_id)
    observacao = (request.form.get('observacao') or '').strip() or None
    db.session.add(AdministracaoRegistro(
        item_id=item.id,
        status='feita',
        realizada_em=now_in_brazil(),
        realizada_por_id=current_user.id,
        observacao=observacao,
    ))
    db.session.commit()
    flash('Aplicação registrada!', 'success')
    return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id))


@bp.route('/tratamento/<int:tratamento_id>/foto', methods=['POST'])
@login_required
def enviar_foto_tratamento(tratamento_id):
    acompanhamento, _ = _tratamento_acompanhamento_or_404(tratamento_id)
    arquivo = request.files.get('foto')
    if not arquivo or not arquivo.filename:
        flash('Selecione uma foto para enviar.', 'warning')
        return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id) + '#fotos')

    carimbo = now_in_brazil().strftime('%Y%m%d%H%M%S')
    filename = f'tratamento_{acompanhamento.id}_{carimbo}_{secure_filename(arquivo.filename)}'
    url = upload_to_s3(arquivo, filename, folder='tratamentos')
    if not url:
        flash('Não foi possível enviar a foto. Tente novamente.', 'danger')
        return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id) + '#fotos')

    db.session.add(FotoTratamento(
        acompanhamento_id=acompanhamento.id,
        url=url,
        observacao=(request.form.get('observacao') or '').strip() or None,
        enviada_por_id=current_user.id,
    ))
    db.session.commit()
    flash('Foto enviada! Ela ajuda o veterinário a avaliar a evolução.', 'success')
    return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id) + '#fotos')


@bp.route('/tratamento/<int:tratamento_id>/status', methods=['POST'])
@login_required
def alterar_status_tratamento(tratamento_id):
    acompanhamento, _ = _tratamento_acompanhamento_or_404(tratamento_id)
    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem alterar o status do tratamento.', 'danger')
        return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id))
    novo_status = (request.form.get('status') or '').strip()
    if novo_status not in ('ativo', 'concluido', 'interrompido'):
        abort(400)
    acompanhamento.status = novo_status
    db.session.commit()
    flash('Status do tratamento atualizado.', 'success')
    return redirect(url_for('acompanhamento_tratamento', tratamento_id=acompanhamento.id))


@bp.route('/animal/<int:animal_id>/bloco_exames', methods=['POST'])
@login_required
def salvar_bloco_exames(animal_id):
    data = request.get_json(silent=True) or {}
    exames_data = data.get('exames', [])
    observacoes_gerais = data.get('observacoes_gerais', '')

    bloco = BlocoExames(animal_id=animal_id, observacoes_gerais=observacoes_gerais)
    db.session.add(bloco)
    db.session.flush()  # Garante que bloco.id esteja disponível

    for exame in exames_data:
        exame_modelo = ExameSolicitado(
            bloco_id=bloco.id,
            nome=exame.get('nome'),
            justificativa=exame.get('justificativa'),
            status=exame.get('status', 'pendente'),
            resultado=exame.get('resultado'),
            performed_at=datetime.fromisoformat(exame['performed_at']) if exame.get('performed_at') else None,
        )
        db.session.add(exame_modelo)

    db.session.commit()
    animal = get_animal_or_404(animal_id)
    historico_html = render_template(
        'partials/historico_exames.html',
        animal=animal
    )
    return jsonify({'success': True, 'html': historico_html})


@bp.route('/buscar_exames')
@login_required
def buscar_exames():
    q = request.args.get('q', '').lower()
    exames = (
        ExameModelo.query
        .filter(ExameModelo.nome.ilike(f'%{q}%'))
        .order_by(ExameModelo.nome)
        .limit(40)
        .all()
    )

    from services.species_ranking import (
        resolver_species_scope_do_animal,
        ordenar_por_species_scope,
    )
    scope_alvo = resolver_species_scope_do_animal(request.args.get('animal_id'))
    if scope_alvo:
        exames = ordenar_por_species_scope(exames, scope_alvo)

    return jsonify([
        {
            'id': e.id,
            'nome': e.nome,
            'justificativa': e.justificativa,
            'species_scope': e.species_scope,
        }
        for e in exames[:15]
    ])


@bp.route('/exame_modelo', methods=['POST'])
@login_required
def criar_exame_modelo():
    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or '').strip()
    justificativa = (data.get('justificativa') or '').strip() or None
    if not nome:
        return jsonify({'error': 'Nome é obrigatório'}), 400
    exame = ExameModelo(nome=nome, justificativa=justificativa, created_by=current_user.id)
    db.session.add(exame)
    db.session.commit()
    return jsonify({'id': exame.id, 'nome': exame.nome, 'justificativa': exame.justificativa})


@bp.route('/exame_modelo/<int:exame_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_exame_modelo(exame_id):
    exame = ExameModelo.query.get_or_404(exame_id)
    if exame.created_by != current_user.id:
        return jsonify({'success': False, 'message': 'Permissão negada'}), 403

    if request.method == 'DELETE':
        db.session.delete(exame)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    nome = (data.get('nome') or exame.nome).strip()
    justificativa = data.get('justificativa', exame.justificativa)
    exame.nome = nome
    exame.justificativa = justificativa
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/imprimir_bloco_exames/<int:bloco_id>')
@login_required
def imprimir_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    animal = bloco.animal
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else None
    if not veterinario and current_user.is_authenticated and getattr(current_user, 'worker', None) == 'veterinario':
        veterinario = current_user
    clinica = consulta.clinica if consulta and consulta.clinica else None
    if not clinica and veterinario and getattr(veterinario, 'veterinario', None):
        vet = veterinario.veterinario
        if vet.clinica:
            clinica = vet.clinica
    if not clinica:
        clinica = getattr(animal, 'clinica', None)
    if not clinica:
        clinica_id = request.args.get('clinica_id', type=int)
        if clinica_id:
            clinica = Clinica.query.get_or_404(clinica_id)
    if not clinica:
        abort(400, description="É necessário informar uma clínica.")

    return render_template('orcamentos/imprimir_exames.html', bloco=bloco, animal=animal, tutor=tutor, clinica=clinica, veterinario=veterinario)


@bp.route('/bloco_exames/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    if not is_veterinarian(current_user):
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False,
                           message='Apenas veterinários podem excluir blocos de exames.'), 403
        flash('Apenas veterinários podem excluir blocos de exames.', 'danger')
        return redirect(request.referrer or url_for('index'))

    animal_id = bloco.animal_id
    db.session.delete(bloco)
    db.session.commit()

    if request.accept_mimetypes.accept_json:
        animal = get_animal_or_404(animal_id)
        historico_html = render_template('partials/historico_exames.html',
                                         animal=animal)
        return jsonify(success=True, html=historico_html)

    flash('Bloco de exames excluído com sucesso!', 'info')
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@bp.route('/bloco_exames/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    ensure_clinic_access(getattr(bloco.animal, 'clinica_id', None))
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar exames.'}), 403
    return render_template('orcamentos/editar_bloco_exames.html', bloco=bloco)


@bp.route('/exame/<int:exame_id>', methods=['PUT', 'DELETE'])
@login_required
def alterar_exame(exame_id):
    exame = ExameSolicitado.query.get_or_404(exame_id)
    ensure_clinic_access(getattr(exame.bloco.animal, 'clinica_id', None))

    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'error': 'Permissão negada.'}), 403

    if request.method == 'DELETE':
        try:
            db.session.delete(exame)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            print('Erro ao excluir exame:', e)
            return jsonify({'success': False, 'error': 'Erro ao excluir exame.'}), 500

    data = request.get_json(silent=True) or {}
    exame.nome = data.get('nome', exame.nome)
    exame.justificativa = data.get('justificativa', exame.justificativa)
    exame.status = data.get('status', exame.status)
    exame.resultado = data.get('resultado', exame.resultado)
    performed_at = data.get('performed_at')
    if performed_at:
        try:
            exame.performed_at = datetime.fromisoformat(performed_at)
        except ValueError:
            pass

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print('Erro ao editar exame:', e)
        return jsonify({'success': False, 'error': 'Erro ao editar exame.'}), 500


@bp.route('/bloco_exames/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    ensure_clinic_access(getattr(bloco.animal, 'clinica_id', None))
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinarios podem editar a solicitacao de exames.'}), 403

    dados = request.get_json(silent=True) or {}

    bloco.observacoes_gerais = dados.get('observacoes_gerais', '')

    # ---------- mapeia exames já existentes ----------
    existentes = {e.id: e for e in bloco.exames}
    enviados_ids = set()

    for ex_json in dados.get('exames', []):
        ex_id = ex_json.get('id')
        nome  = ex_json.get('nome', '').strip()
        just  = ex_json.get('justificativa', '').strip()

        if not nome:                 # pulamos entradas vazias
            continue

        if ex_id and ex_id in existentes:
            # --- atualizar exame já salvo ---
            exame = existentes[ex_id]
            exame.nome = nome
            exame.justificativa = just
            enviados_ids.add(ex_id)
        else:
            # --- criar exame novo ---
            novo = ExameSolicitado(
                bloco=bloco,
                nome=nome,
                justificativa=just,
                status='pendente',
            )
            db.session.add(novo)

    # ---------- remover os que ficaram de fora ----------
    for ex in bloco.exames:
        if ex.id not in enviados_ids and ex.id in existentes:
            db.session.delete(ex)

    db.session.commit()

    historico_html = render_template(
        'partials/historico_exames.html',
        animal=bloco.animal
    )
    return jsonify(success=True, html=historico_html)


@bp.route('/bloco_exames/<int:bloco_id>/realizacao', methods=['POST'])
@login_required
def atualizar_realizacao_exames(bloco_id):
    bloco = BlocoExames.query.get_or_404(bloco_id)
    ensure_clinic_access(getattr(bloco.animal, 'clinica_id', None))

    worker = (getattr(current_user, 'worker', None) or '').lower()
    if not (is_veterinarian(current_user) or worker == 'colaborador' or current_user.role == 'admin'):
        return jsonify({'success': False, 'message': 'Apenas profissionais da clinica podem registrar realizacao de exames.'}), 403

    if request.form or request.files:
        dados = json.loads(request.form.get('payload') or '{}')
    else:
        dados = request.get_json(silent=True) or {}

    existentes = {
        e.id: e
        for e in ExameSolicitado.query.filter_by(bloco_id=bloco.id).all()
    }
    exames_relacionados = {e.id: e for e in bloco.exames}
    allowed_statuses = {'pendente', 'concluido', 'cancelado'}
    notificacao_solicitada = bool(dados.get('notificar_solicitante'))
    mensagem_laudo = (dados.get('mensagem_laudo') or '').strip()
    exames_concluidos = []
    updates_exames = []

    for ex_json in dados.get('exames', []):
        try:
            ex_id = int(ex_json.get('id'))
        except (TypeError, ValueError):
            continue
        exame = existentes.get(ex_id)
        if not exame:
            exame = ExameSolicitado.query.filter_by(id=ex_id, bloco_id=bloco.id).first()
        if not exame:
            continue
        exames_para_atualizar = [exame]
        exame_relacionado = exames_relacionados.get(ex_id)
        if exame_relacionado is not None and exame_relacionado is not exame:
            exames_para_atualizar.append(exame_relacionado)

        status = (ex_json.get('status') or 'pendente').strip().lower()
        if status not in allowed_statuses:
            status = 'pendente'
        resultado = (ex_json.get('resultado') or '').strip() or None
        for exame_alvo in exames_para_atualizar:
            exame_alvo.status = status
            exame_alvo.resultado = resultado
            if mensagem_laudo:
                exame_alvo.laudo_message = mensagem_laudo

        performed_at_str = (ex_json.get('performed_at') or '').strip()
        if performed_at_str:
            try:
                performed_at = datetime.fromisoformat(performed_at_str)
            except ValueError:
                return jsonify({'success': False, 'message': 'Data de realizacao invalida.'}), 400
        else:
            performed_at = None
        for exame_alvo in exames_para_atualizar:
            exame_alvo.performed_at = performed_at

        arquivo_laudo = request.files.get(f'laudo_{ex_id}')
        if arquivo_laudo and arquivo_laudo.filename:
            original_filename = secure_filename(arquivo_laudo.filename)
            _, ext = os.path.splitext(original_filename)
            filename = f"{uuid.uuid4().hex}{ext.lower()}"
            laudo_url = upload_to_s3(arquivo_laudo, filename, folder='laudos_exames')
            if not laudo_url:
                return jsonify({'success': False, 'message': 'Nao foi possivel enviar o arquivo do laudo.'}), 500
            exame.laudo_url = laudo_url
            exame.laudo_filename = original_filename
            exame.laudo_uploaded_at = datetime.now(BR_TZ)
            for exame_alvo in exames_para_atualizar:
                exame_alvo.laudo_url = laudo_url
                exame_alvo.laudo_filename = original_filename
                exame_alvo.laudo_uploaded_at = exame.laudo_uploaded_at

        updates_exames.append({
            'status': exame.status,
            'resultado': exame.resultado,
            'performed_at': exame.performed_at,
            'laudo_url': exame.laudo_url,
            'laudo_filename': exame.laudo_filename,
            'laudo_uploaded_at': exame.laudo_uploaded_at,
            'laudo_message': exame.laudo_message,
            'exame_id': ex_id,
            'bloco_id': bloco.id,
        })

        if exame.status == 'concluido' and (exame.resultado or exame.laudo_url):
            exames_concluidos.append(exame)

    if notificacao_solicitada and exames_concluidos:
        clinica = getattr(bloco.animal, 'clinica', None)
        clinic_id = getattr(bloco.animal, 'clinica_id', None)
        animal_nome = getattr(bloco.animal, 'name', 'paciente') or 'paciente'
        exames_nomes = ', '.join(ex.nome for ex in exames_concluidos[:3])
        if len(exames_concluidos) > 3:
            exames_nomes = f"{exames_nomes} e mais {len(exames_concluidos) - 3}"
        texto_base = mensagem_laudo or 'O laudo do exame ja esta disponivel no historico de exames.'
        aviso = f"{texto_base} Paciente: {animal_nome}. Exame(s): {exames_nomes}."

        if clinic_id and _ensure_clinic_notifications_table():
            db.session.add(
                ClinicNotification(
                    clinic_id=clinic_id,
                    title='Laudo de exame disponivel',
                    message=aviso,
                    type='info',
                    month=datetime.now(BR_TZ).date().replace(day=1),
                )
            )

        clinic_owner_id = getattr(clinica, 'owner_id', None)
        if clinic_owner_id:
            db.session.add(
                Notification(
                    user_id=clinic_owner_id,
                    message=aviso,
                    channel='app',
                    kind='exam_report',
                )
            )

    db.session.flush()
    historico_html = render_template(
        'partials/historico_exames.html',
        animal=bloco.animal
    )
    for update_params in updates_exames:
        db.session.execute(
            text(
                """
                UPDATE exame_solicitado
                   SET status = :status,
                       resultado = :resultado,
                       performed_at = :performed_at,
                       laudo_url = :laudo_url,
                       laudo_filename = :laudo_filename,
                       laudo_uploaded_at = :laudo_uploaded_at,
                       laudo_message = :laudo_message
                 WHERE id = :exame_id AND bloco_id = :bloco_id
                """
            ),
            update_params,
        )
    db.session.commit()
    return jsonify(success=True, html=historico_html)


@bp.route('/novo_atendimento')
@login_required
def novo_atendimento():
    if not is_veterinarian(current_user):
        flash('Apenas veterinários podem acessar esta página.', 'danger')
        return redirect(url_for('index'))

    tutor_form = EditProfileForm()
    return render_template('agendamentos/novo_atendimento.html', tutor_form=tutor_form)


@bp.route("/appointments/<int:appointment_id>/close", methods=["GET", "POST"])
@login_required
def appointment_close(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    if not appointment.clinica_id:
        abort(403)

    clinic_id = current_user_clinic_id()
    if clinic_id and appointment.clinica_id != clinic_id and (current_user.role or "").lower() != "admin":
        abort(403)

    consulta = appointment.consulta
    items = list(consulta.orcamento_items) if consulta and consulta.orcamento_items else []
    service_items = [item for item in items if item.servico_id]
    product_items = [item for item in items if not item.servico_id]

    nfse_document = (
        FiscalDocument.query.filter_by(
            related_type="appointment",
            related_id=appointment.id,
            doc_type=FiscalDocumentType.NFSE,
        )
        .order_by(FiscalDocument.created_at.desc())
        .first()
    )
    nfe_document = (
        FiscalDocument.query.filter_by(
            related_type="appointment",
            related_id=appointment.id,
            doc_type=FiscalDocumentType.NFE,
        )
        .order_by(FiscalDocument.created_at.desc())
        .first()
    )

    if request.method == "POST":
        if not appointment.clinica or not appointment.clinica.fiscal_emitter:
            flash("Clínica sem emissor fiscal configurado.", "warning")
        else:
            result = close_appointment(appointment)
            nfse_document = result.nfse_document
            nfe_document = result.nfe_document
            if not service_items and not product_items:
                flash("Nenhum item fiscal para emissão.", "warning")
            else:
                flash("Fechamento fiscal enfileirado.", "success")

    return render_template(
        "appointment_close.html",
        appointment=appointment,
        consulta=consulta,
        service_items=service_items,
        product_items=product_items,
        nfse_document=nfse_document,
        nfe_document=nfe_document,
    )


@bp.route('/servico', methods=['POST'])
@login_required
def criar_servico_clinica():
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem adicionar itens.'}), 403
    data = request.get_json(silent=True) or {}
    descricao = data.get('descricao')
    valor = data.get('valor')
    procedure_code = (data.get('procedure_code') or '').strip() or None
    if not descricao or valor is None:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    clinica_id = None
    if getattr(current_user, 'veterinario', None):
        clinica_id = current_user.veterinario.clinica_id
    elif current_user.clinica_id:
        clinica_id = current_user.clinica_id
    servico = ServicoClinica(
        descricao=descricao,
        valor=valor,
        clinica_id=clinica_id,
        procedure_code=procedure_code,
    )
    db.session.add(servico)
    db.session.commit()
    return jsonify({
        'id': servico.id,
        'descricao': servico.descricao,
        'valor': float(servico.valor),
        'procedure_code': servico.procedure_code,
    }), 201


@bp.route('/imprimir_orcamento/<int:consulta_id>')
@login_required
def imprimir_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    animal = consulta.animal
    tutor = animal.owner
    veterinario = consulta.veterinario
    clinica = consulta.clinica or (
        veterinario.veterinario.clinica if veterinario and veterinario.veterinario else None
    )
    return render_template(
        'orcamentos/imprimir_orcamento.html',
        itens=consulta.orcamento_items,
        total=consulta.total_orcamento,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
    )


@bp.route('/imprimir_bloco_orcamento/<int:bloco_id>')
@login_required
def imprimir_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    animal = bloco.animal
    owner_access = _current_user_owns_animal(animal)
    if not owner_access:
        ensure_clinic_access(bloco.clinica_id)
    tutor = animal.owner
    consulta = animal.consultas[-1] if animal.consultas else None
    veterinario = consulta.veterinario if consulta else None
    if not veterinario and is_veterinarian(current_user):
        veterinario = current_user
    clinica = consulta.clinica if consulta and consulta.clinica else bloco.clinica
    return render_template(
        'orcamentos/imprimir_orcamento.html',
        itens=bloco.itens,
        total=bloco.total,
        animal=animal,
        tutor=tutor,
        clinica=clinica,
        veterinario=veterinario,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
        return_url=url_for('ficha_animal', animal_id=animal.id) if owner_access else url_for('consulta_direct', animal_id=animal.id),
    )


@bp.route('/orcamento/<int:orcamento_id>/imprimir')
@login_required
def imprimir_orcamento_padrao(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    if not can_view_budget(current_user, orcamento.clinica_id, orcamento.consulta_id):
        abort(404)
    return render_template(
        'orcamentos/imprimir_orcamento_padrao.html',
        itens=orcamento.items,
        total=orcamento.total,
        clinica=orcamento.clinica,
        orcamento=orcamento,
        veterinario=current_user,
        printing_user=current_user,
        printed_at=datetime.now(BR_TZ),
    )


@bp.route('/pagar_orcamento/<int:bloco_id>', methods=['GET', 'POST'])
@login_required
def pagar_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    animal = bloco.animal
    owner_access = _current_user_owns_animal(animal)
    if not owner_access:
        ensure_clinic_access(bloco.clinica_id)
    if not bloco.itens:
        if owner_access and not request.accept_mimetypes.accept_json:
            flash('Nenhum item no orçamento.', 'warning')
            return redirect(url_for('imprimir_bloco_orcamento', bloco_id=bloco.id))
        if request.accept_mimetypes.accept_json:
            return jsonify({'success': False, 'message': 'Nenhum item no orçamento.'}), 400
        flash('Nenhum item no orçamento.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    items = [
        PaymentItemDTO(
            item_id=str(it.id),
            title=it.descricao,
            quantity=1,
            unit_price=float(it.valor),
        )
        for it in bloco.itens
    ]

    try:
        back_url = url_for(
            'imprimir_bloco_orcamento',
            bloco_id=bloco.id,
            _external=True,
        ) if owner_access else url_for(
            'consulta_direct',
            animal_id=bloco.animal_id,
            _external=True,
        )
        preference = create_payment_preference(
            PaymentPreferenceDTO(
                items=items,
                external_reference=f'bloco_orcamento-{bloco.id}',
                back_url=back_url,
            ),
            _criar_preferencia_pagamento,
        )
    except PaymentPreferenceError as exc:
        if request.accept_mimetypes.accept_json:
            return jsonify({'success': False, 'message': str(exc)}), exc.status_code
        flash(str(exc), 'danger')
        if owner_access:
            return redirect(url_for('imprimir_bloco_orcamento', bloco_id=bloco.id))
        return redirect(url_for('consulta_direct', animal_id=bloco.animal_id))

    apply_payment_to_bloco(
        bloco=bloco,
        preference=preference,
        sync_payment_classification=_sync_orcamento_payment_classification,
    )

    tutor = getattr(animal, 'owner', None)
    tutor_user_id = getattr(animal, 'user_id', None)
    tutor_phone = getattr(tutor, 'phone', None) if tutor else None
    tutor_name = getattr(tutor, 'name', 'tutor') if tutor else 'tutor'
    animal_name = getattr(animal, 'name', 'pet')
    app_message_sent = False
    whatsapp_url = None
    message_content = (
        f'Olá, {tutor_name}.\n\n'
        f'O orçamento de {animal_name} foi finalizado e o link de pagamento está disponível:\n'
        f'{preference.payment_url}\n\n'
        'Para concluir, acesse o link acima e siga as instruções de pagamento.'
    )

    if tutor_phone:
        whatsapp_url = (
            f'https://api.whatsapp.com/send?phone={formatar_telefone(tutor_phone)}'
            f'&text={quote_plus(message_content)}'
        )

    if tutor_user_id:
        try:
            db.session.add(
                Message(
                    sender_id=current_user.id,
                    receiver_id=tutor_user_id,
                    animal_id=animal.id,
                    clinica_id=bloco.clinica_id,
                    content=message_content,
                    lida=False,
                )
            )
            db.session.commit()
            app_message_sent = True
        except Exception:  # pragma: no cover - avoid breaking payment flow on chat failure
            db.session.rollback()
            current_app.logger.exception(
                'Falha ao registrar mensagem interna de pagamento para bloco %s',
                bloco.id,
            )

    if request.accept_mimetypes.accept_json:
        historico_html = _render_orcamento_history(bloco.animal, bloco.clinica_id)
        return jsonify({
            'success': True,
            'whatsapp_url': whatsapp_url,
            'app_message_sent': app_message_sent,
            'payment_status': preference.payment_status,
            'html': historico_html,
            'message': 'Link de pagamento gerado com sucesso.'
        })
    return redirect(preference.payment_url)


@bp.route('/orcamento/<int:orcamento_id>/pagar', methods=['POST'])
@login_required
def gerar_link_pagamento_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    if not can_manage_budget(current_user, orcamento.clinica_id, orcamento.consulta_id):
        abort(404)
    if not orcamento.items:
        return jsonify({'success': False, 'message': 'Nenhum item no orçamento.'}), 400

    items = [
        PaymentItemDTO(
            item_id=str(item.id),
            title=item.descricao,
            quantity=1,
            unit_price=float(item.valor),
        )
        for item in orcamento.items
    ]

    try:
        preference = create_payment_preference(
            PaymentPreferenceDTO(
                items=items,
                external_reference=f'orcamento-{orcamento.id}',
                back_url=url_for(
                    'clinic_detail',
                    clinica_id=orcamento.clinica_id,
                    _external=True,
                ),
            ),
            _criar_preferencia_pagamento,
        )
    except PaymentPreferenceError as exc:
        return jsonify({'success': False, 'message': str(exc)}), exc.status_code

    apply_payment_to_orcamento(
        orcamento=orcamento,
        preference=preference,
        sync_payment_classification=_sync_orcamento_payment_classification,
    )

    payment_status_label = ORCAMENTO_PAYMENT_STATUS_LABELS.get(
        orcamento.payment_status, orcamento.payment_status
    )
    payment_status_style = ORCAMENTO_PAYMENT_STATUS_STYLES.get(
        orcamento.payment_status, 'secondary'
    )

    return jsonify({
        'success': True,
        'payment_link': preference.payment_url,
        'payment_status': preference.payment_status,
        'payment_status_label': payment_status_label,
        'payment_status_style': payment_status_style,
        'status': orcamento.status,
        'status_label': ORCAMENTO_STATUS_LABELS.get(orcamento.status, orcamento.status),
        'status_style': ORCAMENTO_STATUS_STYLES.get(orcamento.status, 'secondary'),
        'updated_at': orcamento.updated_at.isoformat() if orcamento.updated_at else None,
        'message': 'Link de pagamento gerado com sucesso.',
    })


@bp.route('/consulta/<int:consulta_id>/pagar_orcamento')
@login_required
def pagar_consulta_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not consulta.orcamento_items:
        flash('Nenhum item no orçamento.', 'warning')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    items = [
        {
            'id': str(it.id),
            'title': it.descricao,
            'quantity': 1,
            'unit_price': float(it.valor),
        }
        for it in consulta.orcamento_items
    ]

    back_urls = {
        s: url_for('consulta_direct', animal_id=consulta.animal_id, _external=True)
        for s in ('success', 'failure', 'pending')
    }
    preference_data = {
        'items': items,
        'external_reference': f'consulta-{consulta.id}',
        'notification_url': _mercadopago_notification_url(),
        'statement_descriptor': current_app.config.get('MERCADOPAGO_STATEMENT_DESCRIPTOR'),
        'back_urls': back_urls,
    }
    if _mp_auto_return_enabled(back_urls):
        preference_data['auto_return'] = 'approved'

    try:
        resp = mp_sdk().preference().create(preference_data)
    except Exception:
        current_app.logger.exception('Erro de conexão com Mercado Pago')
        flash('Falha ao conectar com Mercado Pago.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    if resp.get('status') != 201:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('consulta_direct', animal_id=consulta.animal_id))

    pref = resp['response']
    return redirect(pref['init_point'])


@bp.route('/consulta/<int:consulta_id>/orcamento_item', methods=['POST'])
@login_required
def adicionar_orcamento_item(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem adicionar itens.'}), 403
    data = request.get_json(silent=True) or {}
    clinic_id = _coerce_int(data.get('clinica_id'))
    if clinic_id is None:
        return jsonify({'success': False, 'message': 'Clínica obrigatória.'}), 400
    if not can_manage_budget(current_user, clinic_id, consulta.id):
        abort(404)
    if consulta.clinica_id and consulta.clinica_id != clinic_id:
        return jsonify({'success': False, 'message': 'Consulta pertence a outra clínica.'}), 400
    if not consulta.clinica_id:
        consulta.clinica_id = clinic_id
    servico_id = data.get('servico_id')
    descricao = data.get('descricao')
    valor = data.get('valor')
    procedure_code = (data.get('procedure_code') or '').strip() or None
    payer_type = data.get('payer_type') or default_payer_type_for_consulta(consulta)
    if payer_type not in PAYER_TYPE_LABELS:
        return jsonify({'success': False, 'message': 'Tipo de pagador inválido.'}), 400

    servico = None
    if servico_id:
        servico = ServicoClinica.query.get(servico_id)
        if not servico:
            return jsonify({'success': False, 'message': 'Item não encontrado.'}), 404
        if servico.clinica_id and servico.clinica_id != clinic_id:
            return jsonify({'success': False, 'message': 'Item indisponível para esta clínica.'}), 403
        descricao = servico.descricao
        if valor is None:
            valor = servico.valor
        if not procedure_code:
            procedure_code = servico.procedure_code

    if not descricao or valor is None:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    orcamento = None
    orcamento = consulta.orcamento
    if not orcamento:
        desc = f"Orçamento da consulta {consulta.id} - {consulta.animal.name}"
        orcamento = Orcamento(
            clinica_id=clinic_id,
            consulta_id=consulta.id,
            descricao=desc,
        )
        db.session.add(orcamento)
        db.session.flush()

    item = OrcamentoItem(
        consulta_id=consulta.id,
        orcamento_id=orcamento.id if orcamento else None,
        descricao=descricao,
        valor=valor,
        servico_id=servico.id if servico else None,
        clinica_id=clinic_id,
        procedure_code=procedure_code,
        payer_type=payer_type,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({
        'id': item.id,
        'descricao': item.descricao,
        'valor': float(item.valor),
        'total': float(consulta.total_orcamento),
        'payer_type': item.payer_type,
        'payer_label': payer_type_label(item.payer_type),
        'coverage_status': item.coverage_status,
        'coverage_label': coverage_label(item.coverage_status),
        'coverage_badge': coverage_badge(item.coverage_status),
        'coverage_message': item.coverage_message,
    }), 201


@bp.route('/consulta/orcamento_item/<int:item_id>', methods=['DELETE'])
@login_required
def deletar_orcamento_item(item_id):
    item = OrcamentoItem.query.get_or_404(item_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem remover itens.'}), 403
    consulta = item.consulta
    if not can_manage_budget(current_user, consulta.clinica_id, consulta.id):
        abort(404)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'total': float(consulta.total_orcamento)}), 200


@bp.route('/consulta/<int:consulta_id>/bloco_orcamento', methods=['POST'])
@login_required
def salvar_bloco_orcamento(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem salvar orçamento.'}), 403
    if not consulta.orcamento_items:
        return jsonify({'success': False, 'message': 'Nenhum item no orçamento.'}), 400
    data = request.get_json(silent=True) or {}
    clinic_id = _coerce_int(data.get('clinica_id'))
    if clinic_id is None:
        return jsonify({'success': False, 'message': 'Clínica obrigatória.'}), 400
    if not can_manage_budget(current_user, clinic_id, consulta.id):
        abort(404)
    if consulta.clinica_id and consulta.clinica_id != clinic_id:
        return jsonify({'success': False, 'message': 'Consulta pertence a outra clínica.'}), 400
    if not consulta.clinica_id:
        consulta.clinica_id = clinic_id
    discount_percent = data.get('discount_percent')
    discount_value = data.get('discount_value')
    tutor_notes = (data.get('tutor_notes') or '').strip() or None
    bloco = BlocoOrcamento(
        animal_id=consulta.animal_id,
        clinica_id=clinic_id,
        tutor_notes=tutor_notes,
        payment_status='draft'
    )
    db.session.add(bloco)
    db.session.flush()
    for item in list(consulta.orcamento_items):
        item.bloco_id = bloco.id
        item.consulta_id = None
        db.session.add(item)
    total_bruto = sum((item.valor for item in bloco.itens), Decimal('0.00'))
    total_particular = sum(
        (item.valor for item in bloco.itens if (item.payer_type or 'particular') == 'particular'),
        Decimal('0.00')
    )
    desconto_decimal = Decimal('0.00')
    try:
        if discount_value is not None:
            desconto_decimal = Decimal(str(discount_value))
        elif discount_percent is not None:
            percentual = Decimal(str(discount_percent))
            desconto_decimal = (total_particular * percentual) / Decimal('100')
    except Exception:
        desconto_decimal = Decimal('0.00')

    if desconto_decimal < 0:
        desconto_decimal = Decimal('0.00')
    if desconto_decimal > total_particular:
        desconto_decimal = total_particular

    bloco.discount_percent = None
    if discount_percent is not None:
        try:
            bloco.discount_percent = Decimal(str(discount_percent))
        except Exception:
            bloco.discount_percent = None
    bloco.discount_value = desconto_decimal if desconto_decimal else None
    bloco.net_total = total_bruto - desconto_decimal if total_bruto is not None else None
    if bloco.net_total is not None and bloco.net_total < 0:
        bloco.net_total = Decimal('0.00')
    db.session.commit()
    historico_html = _render_orcamento_history(consulta.animal, consulta.clinica_id)
    return jsonify({'success': True, 'html': historico_html})


@bp.route('/consulta/<int:consulta_id>/historico_orcamentos', methods=['GET'])
@login_required
def historico_orcamentos_partial(consulta_id):
    consulta = get_consulta_or_404(consulta_id)
    clinic_id = consulta.clinica_id or current_user_clinic_id() or getattr(consulta.animal, 'clinica_id', None)

    if clinic_id and not can_view_budget(current_user, clinic_id, consulta.id):
        abort(404)

    historico_html = _render_orcamento_history(consulta.animal, clinic_id)
    return jsonify({'success': True, 'html': historico_html})


@bp.route('/bloco_orcamento/<int:bloco_id>/deletar', methods=['POST'])
@login_required
def deletar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    if not can_manage_budget(current_user, bloco.clinica_id):
        abort(404)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem excluir.'}), 403
    animal_id = bloco.animal_id
    clinic_id = bloco.clinica_id
    db.session.delete(bloco)
    db.session.commit()
    if request.accept_mimetypes.accept_json:
        animal = Animal.query.get(animal_id)
        historico_html = _render_orcamento_history(
            animal,
            clinic_id or getattr(animal, 'clinica_id', None)
        )
        return jsonify({'success': True, 'html': historico_html})
    return redirect(url_for('consulta_direct', animal_id=animal_id))


@bp.route('/bloco_orcamento/<int:bloco_id>/editar', methods=['GET'])
@login_required
def editar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    if not can_manage_budget(current_user, bloco.clinica_id):
        abort(404)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403
    return render_template('orcamentos/editar_bloco_orcamento.html', bloco=bloco)


@bp.route('/bloco_orcamento/<int:bloco_id>/atualizar', methods=['POST'])
@login_required
def atualizar_bloco_orcamento(bloco_id):
    bloco = BlocoOrcamento.query.get_or_404(bloco_id)
    if not can_manage_budget(current_user, bloco.clinica_id):
        abort(404)
    if not is_veterinarian(current_user):
        return jsonify({'success': False, 'message': 'Apenas veterinários podem editar.'}), 403

    data = request.get_json(silent=True) or {}
    clinic_id = _coerce_int(data.get('clinica_id'))
    if clinic_id is None:
        return jsonify({'success': False, 'message': 'Clínica obrigatória.'}), 400
    if not can_manage_budget(current_user, clinic_id):
        abort(404)
    if clinic_id != bloco.clinica_id:
        abort(404)
    itens = data.get('itens', [])

    for item in list(bloco.itens):
        db.session.delete(item)

    for it in itens:
        descricao = (it.get('descricao') or '').strip()
        valor = it.get('valor')
        if not descricao or valor is None:
            continue
        try:
            valor_decimal = Decimal(str(valor))
        except Exception:
            continue
        bloco.itens.append(
            OrcamentoItem(
                descricao=descricao,
                valor=valor_decimal,
                clinica_id=bloco.clinica_id,
            )
        )

    db.session.flush()
    _sync_orcamento_payment_classification(bloco)
    db.session.commit()

    historico_html = _render_orcamento_history(bloco.animal, bloco.clinica_id)
    return jsonify(success=True, html=historico_html)

