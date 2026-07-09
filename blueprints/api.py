"""API JSON (mobile/integrações/ChatGPT) — views do domínio.

``is_veterinarian`` e ``ensure_clinic_access`` são late-bound via módulo app
(testes fazem monkeypatch desses nomes — contrato do antigo lazy_view).
"""
import re
from datetime import date, datetime, timedelta
from typing import Optional, Set
from urllib.parse import parse_qs, urlparse

import requests
from flask import Blueprint, abort, g, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import and_, false, func, or_
from sqlalchemy.orm import joinedload

from extensions import csrf, db
from helpers import (
    appointments_to_events,
    clinicas_do_usuario,
    consulta_to_event,
    exam_to_event,
    geocode_address,
    get_available_times,
    get_weekly_schedule,
    has_professional_access,
    has_veterinarian_profile,
    is_slot_available,
    to_timezone_aware,
    unique_items_by_id,
    vaccine_to_event,
)
from models import (
    Animal,
    AnimalDocumento,
    Appointment,
    Clinica,
    Consulta,
    DataSharePartyType,
    DataShareRequest,
    DeliveryRequest,
    ExamAppointment,
    ExameImagem,
    ExameImagemPdfAccessLog,
    Order,
    Payment,
    User,
    Vacina,
    Veterinario,
)
from services import (
    build_usage_history,
    coverage_label,
    find_active_share,
    get_calendar_access_scope,
    insurer_token_valid,
)
from services.appointments import ReturnAppointmentDTO, schedule_return_appointment
from services.oauth_provider import _oauth_allowed_scopes, _oauth_issuer
from time_utils import BR_TZ, coerce_to_brazil_tz, normalize_to_utc, utcnow

from app import (
    MCP_FILE_REFERENCE_OR_STRING_SCHEMA,
    MCP_FILE_REFERENCE_SCHEMA,
    _activate_share_request,
    _apply_calendar_date_window,
    _apply_calendar_datetime_window,
    _calendar_window_from_request,
    _can_request_share,
    _create_external_onboarding_invite,
    _default_share_duration,
    _ensure_pending,
    _integration_accessible_consultas_query,
    _integration_build_clinical_pendencies,
    _integration_build_clinical_summary,
    _integration_build_handoff,
    _integration_build_today_agenda,
    _integration_confirmation_error,
    _integration_create_exam_block,
    _integration_create_exame_imagem,
    _integration_create_or_reuse_tutor_and_pets,
    _integration_ensure_clinic_admin_user,
    _integration_error,
    _integration_exame_imagem_document_payload,
    _integration_exame_imagem_pdf_summary,
    _integration_execute_assistant_action,
    _integration_extract_freeform_intake,
    _integration_extract_pdf_file_reference,
    _integration_find_accessible_animal,
    _integration_find_exame_by_documento,
    _integration_find_or_create_external_clinic,
    _integration_find_or_create_pet_for_tutor,
    _integration_find_or_create_tutor_for_clinic,
    _integration_format_datetime,
    _integration_generate_tutor_guidance,
    _integration_infer_assistant_action,
    _integration_list_exame_imagem_history,
    _integration_normalize_match_text,
    _integration_ok,
    _integration_parse_date_arg,
    _integration_parse_time_arg,
    _integration_professional_error,
    _integration_reconcile_exam_documents,
    _integration_release_exame_imagem,
    _integration_request_json,
    _integration_schedule_consulta,
    _integration_serialize_exame_imagem,
    _integration_store_exame_pdf,
    _integration_upsert_consulta,
    _integration_user_can_access_exame_imagem,
    _integration_user_clinic_id,
    _invite_payload,
    _is_tutor_portal_user,
    _mcp_find_animal_for_tool,
    _notify_clinic_share_decision,
    _notify_tutor_share_request,
    _public_pricing_config,
    _serialize_calendar_pet,
    _serialize_clinic_share_payload,
    _serialize_share_access,
    _serialize_share_request,
    _serialize_tutor_share_payload,
    _share_request_or_404,
    _share_request_target_animals,
    current_user_clinic_id,
    get_user_or_404,
    integration_bearer_required,
)

bp = Blueprint("api_routes", __name__)


def get_blueprint():
    return bp


def is_veterinarian(*args, **kwargs):
    import app as app_module

    return app_module.is_veterinarian(*args, **kwargs)


def ensure_clinic_access(*args, **kwargs):
    import app as app_module

    return app_module.ensure_clinic_access(*args, **kwargs)


# Views de mensagens expostas sob /api (vivem em blueprints/mensagens.py)
from blueprints.mensagens import (  # noqa: E402
    api_conversa_admin_message,
    api_conversa_message,
    api_message_threads,
)

bp.add_url_rule("/api/messages/threads", view_func=api_message_threads)
bp.add_url_rule(
    "/api/conversa/<int:animal_id>/<int:user_id>",
    view_func=api_conversa_message,
    methods=["POST"],
)
bp.add_url_rule("/api/conversa_admin", view_func=api_conversa_admin_message, methods=["POST"])
bp.add_url_rule(
    "/api/conversa_admin/<int:user_id>",
    view_func=api_conversa_admin_message,
    methods=["POST"],
)


@bp.route("/api/cep/<cep>", methods=["GET"])
def api_cep_lookup(cep: str):
    """Lookup CEP information using a list of public providers.

    The frontend calls this endpoint instead of contacting third-party
    services directly, which avoids CORS issues in the browser and lets us
    provide consistent error handling/fallbacks.
    """

    sanitized = re.sub(r'\D', '', cep or '')
    if len(sanitized) != 8:
        return jsonify(success=False, error='CEP inválido'), 400

    providers = (
        ('https://viacep.com.br/ws/{cep}/json/', 'viacep'),
        ('https://brasilapi.com.br/api/cep/v1/{cep}', 'brasilapi'),
    )

    def _normalize(payload: dict, provider: str):
        if not isinstance(payload, dict):
            return None

        if provider == 'viacep':
            if payload.get('erro'):
                return None
            return {
                'cep': payload.get('cep'),
                'logradouro': payload.get('logradouro'),
                'complemento': payload.get('complemento'),
                'bairro': payload.get('bairro'),
                'localidade': payload.get('localidade'),
                'uf': payload.get('uf'),
            }

        if provider == 'brasilapi':
            if payload.get('errors') or payload.get('message'):
                return None
            return {
                'cep': payload.get('cep'),
                'logradouro': payload.get('street') or payload.get('logradouro'),
                'complemento': payload.get('complement'),
                'bairro': payload.get('neighborhood') or payload.get('bairro'),
                'localidade': payload.get('city') or payload.get('localidade'),
                'uf': payload.get('state') or payload.get('uf'),
            }

        return None

    for template, provider in providers:
        url = template.format(cep=sanitized)
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        normalized = _normalize(payload, provider)
        if normalized:
            return jsonify(success=True, data=normalized)

    return jsonify(success=False, error='CEP não encontrado'), 404


@bp.route("/api/geocode/reverse", methods=["GET"])
def api_reverse_geocode():
    """Resolve latitude/longitude into address data for the form.

    This endpoint wraps the public Nominatim API to avoid CORS issues
    and to normalize the response to the fields expected by the
    frontend address form.
    """

    def _state_from_address(address: dict):
        iso_code = address.get('ISO3166-2-lvl4') or address.get('ISO3166-2-lvl3')
        if isinstance(iso_code, str) and '-' in iso_code:
            candidate = iso_code.split('-')[-1]
            if len(candidate) == 2:
                return candidate
        state_code = address.get('state_code')
        if isinstance(state_code, str) and len(state_code) == 2:
            return state_code
        return None

    def _first_of(address: dict, *keys):
        for key in keys:
            value = address.get(key)
            if value:
                return value
        return None

    try:
        lat = float(request.args.get('lat', ''))
        lon = float(request.args.get('lon', ''))
    except ValueError:
        return jsonify(success=False, error='Coordenadas inválidas'), 400

    params = {
        'format': 'jsonv2',
        'lat': lat,
        'lon': lon,
        'addressdetails': 1,
    }

    headers = {'User-Agent': 'petorlandia-geocoder/1.0'}
    try:
        response = requests.get('https://nominatim.openstreetmap.org/reverse', params=params, headers=headers, timeout=8)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return jsonify(success=False, error='Não foi possível obter o endereço'), 502

    address = payload.get('address') or {}
    if not address:
        return jsonify(success=False, error='Endereço não encontrado'), 404

    normalized = {
        'cep': address.get('postcode'),
        'logradouro': _first_of(address, 'road', 'residential', 'pedestrian', 'path'),
        'numero': address.get('house_number'),
        'complemento': _first_of(address, 'building', 'amenity'),
        'bairro': _first_of(address, 'suburb', 'neighbourhood', 'city_district'),
        'localidade': _first_of(address, 'city', 'town', 'village'),
        'uf': _state_from_address(address),
    }

    return jsonify(success=True, data=normalized)


@bp.route("/api/geocode/address", methods=["POST"])
def api_forward_geocode():
    """Resolve an address into coordinates using the same backend helper.

    The frontend uses this when geolocation is unavailable/disabled to still
    estimate coordinates based on the typed address fields (CEP, street and
    number). The response mirrors the reverse geocode structure but only
    returns latitude/longitude.
    """

    payload = request.get_json(silent=True) or {}

    def _get(field: str):
        return (request.form.get(field) or payload.get(field) or '').strip()

    cep = _get('cep')
    rua = _get('rua')
    numero = _get('numero')
    bairro = _get('bairro')
    cidade = _get('cidade')
    estado = _get('estado')

    if not any([cep, rua, bairro, cidade, estado]):
        return jsonify(success=False, error='Informe CEP ou endereço para geocodificar'), 400

    coords = geocode_address(
        cep=cep,
        rua=rua,
        numero=numero,
        bairro=bairro,
        cidade=cidade,
        estado=estado,
    )

    if not coords:
        return jsonify(success=False, error='Endereço não encontrado'), 404

    lat, lon = coords
    return jsonify(success=True, data={'lat': lat, 'lon': lon})


@bp.route("/api/seguradoras/sinistros", methods=["POST"])
@csrf.exempt
def api_criar_sinistro():
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    payload = request.get_json(silent=True) or {}
    subscription_id = payload.get('subscription_id') or payload.get('subscriptionId')
    if not subscription_id:
        return jsonify({'error': 'subscription_id é obrigatório'}), 400
    from models import HealthSubscription, HealthClaim
    subscription = HealthSubscription.query.get_or_404(subscription_id)
    consulta_id = payload.get('consulta_id') or payload.get('consultaId')
    coverage_code = payload.get('procedure_code') or payload.get('procedureCode')
    coverage = None
    if coverage_code and subscription.plan:
        coverage = next((c for c in subscription.plan.coverages if c.matches(coverage_code)), None)
    claim = HealthClaim(
        subscription_id=subscription.id,
        consulta_id=consulta_id,
        coverage_id=coverage.id if coverage else None,
        insurer_reference=payload.get('reference') or payload.get('id'),
        request_format='fhir' if payload.get('resourceType') else 'json',
        payload=payload,
        status=payload.get('status') or 'received',
    )
    db.session.add(claim)
    db.session.commit()
    return jsonify({'id': claim.id, 'status': claim.status}), 201


@bp.route("/api/seguradoras/sinistros/<int:claim_id>", methods=["GET"])
@csrf.exempt
def api_status_sinistro(claim_id):
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    from models import HealthClaim
    claim = HealthClaim.query.get_or_404(claim_id)
    return jsonify({
        'id': claim.id,
        'status': claim.status,
        'consulta_id': claim.consulta_id,
        'subscription_id': claim.subscription_id,
        'coverage_id': claim.coverage_id,
        'payload': claim.payload,
        'response_payload': claim.response_payload,
    })


@bp.route("/api/seguradoras/planos/<int:plan_id>/historico", methods=["GET"])
@csrf.exempt
def api_historico_uso(plan_id):
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    limit = request.args.get('limit', 50, type=int)
    history = build_usage_history(plan_id=plan_id, limit=limit)
    return jsonify({'plan_id': plan_id, 'historico': history})


@bp.route("/api/seguradoras/consultas/<int:consulta_id>/autorizacao", methods=["GET"])
@csrf.exempt
def api_status_autorizacao(consulta_id):
    token = request.headers.get('X-Insurer-Token')
    if not insurer_token_valid(token):
        abort(401)
    consulta = Consulta.query.get_or_404(consulta_id)
    return jsonify({
        'consulta_id': consulta.id,
        'animal_id': consulta.animal_id,
        'status': consulta.authorization_status,
        'status_label': coverage_label(consulta.authorization_status),
        'checked_at': consulta.authorization_checked_at.isoformat() if consulta.authorization_checked_at else None,
        'notes': consulta.authorization_notes,
    })


@bp.route("/api/shares", methods=["GET", "POST"])
@login_required
def shares_api():
    if request.method == 'POST':
        if not _can_request_share(current_user):
            return (
                jsonify(success=False, message='Apenas colaboradores podem solicitar compartilhamentos.', category='danger'),
                403,
            )
        clinic_id = current_user_clinic_id()
        if not clinic_id:
            return jsonify(success=False, message='Associe-se a uma clínica antes de solicitar acesso.', category='warning'), 400
        payload = request.get_json(silent=True) or {}
        tutor_id = payload.get('tutor_id')
        if not tutor_id:
            return jsonify(success=False, message='tutor_id é obrigatório.', category='danger'), 400
        tutor = User.query.get_or_404(tutor_id)
        try:
            animal = _share_request_target_animals(tutor.id, payload.get('animal_id'))
        except ValueError as exc:
            return jsonify(success=False, message=str(exc), category='danger'), 400
        parties = [(DataSharePartyType.clinic, clinic_id)]
        existing_access = find_active_share(parties, user_id=tutor.id, animal_id=getattr(animal, 'id', None))
        if existing_access:
            return jsonify(success=False, message='Este tutor já concedeu acesso à sua clínica.', category='info'), 409
        pending = (
            DataShareRequest.query.filter_by(
                tutor_id=tutor.id,
                clinic_id=clinic_id,
                animal_id=getattr(animal, 'id', None),
                status='pending',
            )
            .order_by(DataShareRequest.created_at.desc())
            .first()
        )
        if pending and pending.is_pending():
            return jsonify(success=False, message='Já existe um pedido pendente para este tutor.', category='warning'), 409
        expires_days = _default_share_duration(payload.get('expires_in_days'))
        expires_at = utcnow() + timedelta(days=expires_days)
        message = (payload.get('message') or payload.get('grant_reason') or '').strip() or None
        share_request = DataShareRequest(
            tutor_id=tutor.id,
            animal_id=getattr(animal, 'id', None),
            clinic_id=clinic_id,
            requested_by_id=current_user.id,
            message=message,
            expires_at=expires_at,
        )
        db.session.add(share_request)
        db.session.commit()
        _notify_tutor_share_request(share_request)
        return jsonify(success=True, request=_serialize_share_request(share_request)), 201

    scope = request.args.get('scope') or ('tutor' if _is_tutor_portal_user(current_user) else 'clinic')
    if scope == 'tutor' and _is_tutor_portal_user(current_user):
        payload = _serialize_tutor_share_payload(current_user)
    else:
        payload = _serialize_clinic_share_payload(current_user)
    return jsonify(payload)


@bp.route("/api/shares/<int:request_id>/approve", methods=["POST"])
@login_required
def approve_share_request(request_id):
    if not _is_tutor_portal_user(current_user):
        abort(403)
    share_request = _share_request_or_404(request_id)
    _ensure_pending(share_request)
    payload = request.get_json(silent=True) or {}
    access = _activate_share_request(share_request, expires_in_days=payload.get('expires_in_days'))
    db.session.commit()
    _notify_clinic_share_decision(share_request, True)
    return jsonify(success=True, request=_serialize_share_request(share_request), access=_serialize_share_access(access))


@bp.route("/api/shares/<int:request_id>/deny", methods=["POST"])
@login_required
def deny_share_request(request_id):
    if not _is_tutor_portal_user(current_user):
        abort(403)
    share_request = _share_request_or_404(request_id)
    _ensure_pending(share_request)
    payload = request.get_json(silent=True) or {}
    reason = (payload.get('reason') or '').strip() or None
    share_request.status = 'denied'
    share_request.denied_at = utcnow()
    share_request.denial_reason = reason
    db.session.add(share_request)
    db.session.commit()
    _notify_clinic_share_decision(share_request, False)
    return jsonify(success=True, request=_serialize_share_request(share_request))


@bp.route("/api/shares/confirm", methods=["POST"])
@login_required
def confirm_share_request():
    if not _is_tutor_portal_user(current_user):
        abort(403)
    payload = request.get_json(silent=True) or {}
    token = payload.get('token')
    if not token:
        return jsonify(success=False, message='Token é obrigatório.', category='danger'), 400
    share_request = DataShareRequest.query.filter_by(token=token).first()
    if not share_request or share_request.tutor_id != current_user.id:
        return jsonify(success=False, message='Pedido não encontrado.', category='warning'), 404
    if payload.get('decision', 'approve').lower() == 'deny':
        _ensure_pending(share_request)
        share_request.status = 'denied'
        share_request.denied_at = utcnow()
        share_request.denial_reason = (payload.get('reason') or '').strip() or None
        db.session.add(share_request)
        db.session.commit()
        _notify_clinic_share_decision(share_request, False)
        return jsonify(success=True, request=_serialize_share_request(share_request))
    _ensure_pending(share_request)
    access = _activate_share_request(share_request)
    db.session.commit()
    _notify_clinic_share_decision(share_request, True)
    return jsonify(success=True, request=_serialize_share_request(share_request), access=_serialize_share_access(access))


@bp.route("/api/share-requests/<string:token>", methods=["GET"])
@login_required
def share_request_detail(token):
    if not _is_tutor_portal_user(current_user):
        abort(403)
    share_request = DataShareRequest.query.filter_by(token=token).first_or_404()
    if share_request.tutor_id != current_user.id:
        abort(404)
    return jsonify(_serialize_share_request(share_request))


@bp.route("/api/delivery_counts", methods=["GET"])
@login_required
def api_delivery_counts():
    """Return delivery counts for the current user."""
    base = DeliveryRequest.query.filter_by(archived=False)
    if current_user.worker == "delivery":
        base = base.filter(DeliveryRequest.tipo_entrega == 'plataforma')
        available_total = base.filter_by(status="pendente").count()
        doing = base.filter_by(worker_id=current_user.id,
                              status="em_andamento").count()
        done = base.filter_by(worker_id=current_user.id,
                             status="concluida").count()
        canceled = base.filter_by(worker_id=current_user.id,
                                 status="cancelada").count()
    else:
        base = base.filter_by(requested_by_id=current_user.id)
        available_total = 0
        doing = base.filter_by(status="em_andamento").count()
        done = base.filter_by(status="concluida").count()
        canceled = base.filter_by(status="cancelada").count()

    return jsonify(
        available_total=available_total,
        doing=doing,
        done=done,
        canceled=canceled,
    )


@bp.route("/api/payment_status/<int:payment_id>", methods=["GET"])
def api_payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if current_user.is_authenticated and payment.user_id != current_user.id:
        abort(403)
    return jsonify(status=payment.status.name)


@bp.route("/api/minhas-compras", methods=["GET"])
@login_required
def api_minhas_compras():
    orders = (Order.query
              .options(joinedload(Order.payment))
              .filter_by(user_id=current_user.id)
              .order_by(Order.created_at.desc())
              .all())
    data = [
        {
            "id": o.id,
            "data": o.created_at.isoformat(),
            "valor": float((getattr(o.payment, "amount", None) if o.payment else None) or o.total_value()),
            "status": (o.payment.status.value if o.payment else "Pendente"),
        }
        for o in orders
    ]
    return jsonify(data)


@bp.route("/api/integrations/me", methods=["GET"])
@integration_bearer_required('profile')
def api_integrations_me():
    auth_user = g.integration_current_user
    return _integration_ok({
        'sub': str(auth_user.id),
        'user_id': auth_user.id,
        'name': auth_user.name,
        'email': auth_user.email,
        'role': auth_user.role,
        'worker': getattr(auth_user, 'worker', None),
        'clinica_id': _integration_user_clinic_id(auth_user),
    })


@bp.route("/api/integrations/pets", methods=["GET"])
@integration_bearer_required('pets:read')
def api_integrations_pets():
    auth_user = g.integration_current_user

    query = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
        )
        .filter(Animal.removido_em.is_(None))
    )

    role = (getattr(auth_user, 'role', '') or '').lower()
    if role == 'admin':
        clinic_id = request.args.get('clinica_id', type=int)
        if clinic_id:
            query = query.filter(Animal.clinica_id == clinic_id)
    elif has_professional_access(auth_user):
        clinic_id = _integration_user_clinic_id(auth_user)
        if not clinic_id:
            return _integration_ok([])
        query = query.filter(Animal.clinica_id == clinic_id)
    else:
        query = query.filter(Animal.user_id == auth_user.id)

    pets = query.order_by(Animal.date_added.desc()).all()
    return _integration_ok([_serialize_calendar_pet(pet) for pet in pets])


@bp.route("/api/integrations/appointments", methods=["GET"])
@integration_bearer_required('appointments:read')
def api_integrations_appointments():
    auth_user = g.integration_current_user
    query = Appointment.query
    role = (getattr(auth_user, 'role', '') or '').lower()

    if role == 'admin':
        clinic_id = request.args.get('clinica_id', type=int)
        if clinic_id:
            query = query.filter(Appointment.clinica_id == clinic_id)
    elif has_veterinarian_profile(auth_user):
        veterinarian = getattr(auth_user, 'veterinario', None)
        if not veterinarian:
            return _integration_ok([])
        query = query.filter(Appointment.veterinario_id == veterinarian.id)
    elif getattr(auth_user, 'worker', None) == 'colaborador':
        clinic_id = _integration_user_clinic_id(auth_user)
        if not clinic_id:
            return _integration_ok([])
        query = query.filter(Appointment.clinica_id == clinic_id)
    else:
        query = query.filter(Appointment.tutor_id == auth_user.id)

    appointments = query.order_by(Appointment.scheduled_at.desc()).limit(200).all()
    payload = [
        {
            'id': item.id,
            'scheduled_at': item.scheduled_at.isoformat() if item.scheduled_at else None,
            'status': item.status,
            'animal_id': item.animal_id,
            'tutor_id': item.tutor_id,
            'veterinario_id': item.veterinario_id,
            'clinica_id': item.clinica_id,
        }
        for item in appointments
    ]
    return _integration_ok(payload)


@bp.route("/api/integrations/clinical-summary/<int:animal_id>", methods=["GET"])
@integration_bearer_required('clinical_summary:read')
def api_integrations_clinical_summary(animal_id):
    auth_user = g.integration_current_user
    clinic_id = request.args.get('clinica_id', type=int)
    animal = _integration_find_accessible_animal(auth_user, animal_id=animal_id, clinic_id=clinic_id)
    if not animal:
        return _integration_error(
            'animal_not_found',
            'Animal not found within the accessible integration scope.',
            404,
            animal_id=animal_id,
        )
    return _integration_ok(_integration_build_clinical_summary(auth_user, animal))


@bp.route("/api/integrations/today-agenda", methods=["GET"])
@integration_bearer_required('appointments:read')
def api_integrations_today_agenda():
    auth_user = g.integration_current_user
    raw_date = request.args.get('date', '').strip()
    target_date = None
    if raw_date:
        try:
            target_date = date.fromisoformat(raw_date)
        except ValueError:
            return _integration_error(
                'invalid_date',
                'The date query parameter must use the YYYY-MM-DD format.',
                400,
                date=raw_date,
            )
    return _integration_ok(_integration_build_today_agenda(auth_user, target_date=target_date))


@bp.route("/api/integrations/clinical-pendencies", methods=["GET"])
@integration_bearer_required('appointments:read', 'exams:read', 'vaccines:read')
def api_integrations_clinical_pendencies():
    auth_user = g.integration_current_user
    clinic_id = request.args.get('clinica_id', type=int)
    return _integration_ok(_integration_build_clinical_pendencies(auth_user, clinic_id=clinic_id))


@bp.route("/api/integrations/tutor-guidance/<int:animal_id>", methods=["GET"])
@integration_bearer_required('tutor_guidance:generate')
def api_integrations_tutor_guidance(animal_id):
    auth_user = g.integration_current_user
    clinic_id = request.args.get('clinica_id', type=int)
    animal = _integration_find_accessible_animal(auth_user, animal_id=animal_id, clinic_id=clinic_id)
    if not animal:
        return _integration_error(
            'animal_not_found',
            'Animal not found within the accessible integration scope.',
            404,
            animal_id=animal_id,
        )

    consulta_id = request.args.get('consulta_id', type=int)
    return _integration_ok(_integration_generate_tutor_guidance(auth_user, animal, consulta_id=consulta_id))


@bp.route("/api/integrations/handoff/<int:animal_id>", methods=["GET"])
@integration_bearer_required('handoff:read')
def api_integrations_handoff(animal_id):
    auth_user = g.integration_current_user
    clinic_id = request.args.get('clinica_id', type=int)
    animal = _integration_find_accessible_animal(auth_user, animal_id=animal_id, clinic_id=clinic_id)
    if not animal:
        return _integration_error(
            'animal_not_found',
            'Animal not found within the accessible integration scope.',
            404,
            animal_id=animal_id,
        )

    consulta_id = request.args.get('consulta_id', type=int)
    return _integration_ok(_integration_build_handoff(auth_user, animal, consulta_id=consulta_id))


@bp.route("/api/integrations/intake/interpret", methods=["POST"])
@csrf.exempt
@integration_bearer_required('profile')
def api_integrations_interpret_intake():
    payload, error = _integration_request_json()
    if error:
        return error
    try:
        return _integration_ok(_integration_extract_freeform_intake(payload))
    except ValueError as exc:
        return _integration_error('invalid_intake_payload', str(exc), 400)


@bp.route("/api/integrations/assistant", methods=["POST"])
@csrf.exempt
@integration_bearer_required('profile')
def api_integrations_operational_assistant():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error

    try:
        planning = _integration_infer_assistant_action(auth_user, payload)
    except ValueError as exc:
        return _integration_error('invalid_assistant_payload', str(exc), 400)

    confirmed = str(payload.get('confirmar_gravacao') or '').strip().lower() in {'sim', 's', 'yes', 'true', '1'}
    response_payload = {
        **planning,
        'executado': False,
        'requer_confirmacao': True,
        'confirmacao_necessaria': 'confirmar_gravacao="sim"',
    }
    if not confirmed:
        return _integration_ok(response_payload)

    action_scopes = {
        'cadastrar_tutor_e_pets': {'tutors:write', 'pets:write'},
        'agendar_consulta': {'appointments:write'},
        'registrar_consulta_clinica': {'consultations:write'},
        'criar_exame_imagem': {'exams:write'},
    }.get(planning.get('acao_sugerida'), set())
    granted_scopes = set(g.integration_auth.get('scopes') or [])
    missing_scopes = sorted(action_scopes.difference(granted_scopes))
    if missing_scopes:
        return _integration_error(
            'insufficient_scope',
            'Access token does not grant the required scope for the inferred action.',
            403,
            missing_scopes=missing_scopes,
        )

    try:
        result = _integration_execute_assistant_action(auth_user, planning)
    except PermissionError as exc:
        return _integration_error('professional_account_required', str(exc), 403)
    except ValueError as exc:
        return _integration_error('assistant_action_incomplete', str(exc), 400)

    response_payload['executado'] = True
    response_payload['resultado_execucao'] = result
    return _integration_ok(response_payload)


@bp.route("/api/integrations/tutors-with-pets", methods=["POST"])
@csrf.exempt
@integration_bearer_required('tutors:write', 'pets:write')
def api_integrations_create_tutor_and_pets():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    professional_error = _integration_professional_error(auth_user, veterinarian_only=True)
    if professional_error:
        return professional_error

    tutor_data = payload.get('tutor') or {}
    pets_data = payload.get('pets') or []
    if not isinstance(tutor_data, dict) or not isinstance(pets_data, list) or not tutor_data or not pets_data:
        return _integration_error(
            'invalid_registration_payload',
            'Informe tutor e ao menos um pet para cadastro.',
            400,
        )

    try:
        result = _integration_create_or_reuse_tutor_and_pets(
            auth_user,
            tutor_data,
            pets_data,
            observacao_clinica=payload.get('observacao_clinica'),
            disponibilidade=payload.get('disponibilidade'),
        )
    except ValueError as exc:
        return _integration_error('invalid_registration_payload', str(exc), 400)
    return _integration_ok(result, 201)


@bp.route("/api/integrations/consultations", methods=["POST"])
@csrf.exempt
@integration_bearer_required('consultations:write')
def api_integrations_create_or_update_consultation():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    professional_error = _integration_professional_error(auth_user, veterinarian_only=True)
    if professional_error:
        return professional_error

    animal = _mcp_find_animal_for_tool(auth_user, payload)
    if not animal:
        return _integration_error(
            'animal_not_found',
            'Animal not found within the accessible integration scope.',
            404,
        )

    try:
        consulta = _integration_upsert_consulta(auth_user, animal, payload)
    except ValueError as exc:
        return _integration_error('invalid_consultation_payload', str(exc), 400)
    return _integration_ok({
        'consulta_id': consulta.id,
        'animal_id': consulta.animal_id,
        'status': consulta.status,
        'queixa_principal': consulta.queixa_principal,
        'conduta': consulta.conduta,
    }, 201)


@bp.route("/api/integrations/exam-blocks", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_create_exam_block():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    professional_error = _integration_professional_error(auth_user, veterinarian_only=True)
    if professional_error:
        return professional_error

    animal = _mcp_find_animal_for_tool(auth_user, payload)
    if not animal:
        return _integration_error(
            'animal_not_found',
            'Animal not found within the accessible integration scope.',
            404,
        )

    try:
        bloco = _integration_create_exam_block(auth_user, animal, payload)
    except ValueError as exc:
        return _integration_error('invalid_exam_block_payload', str(exc), 400)
    return _integration_ok({
        'bloco_id': bloco.id,
        'animal_id': animal.id,
        'total_exames': len(payload.get('exames') or []),
    }, 201)


@bp.route("/api/integrations/image-exams", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_create_exame_imagem():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    professional_error = _integration_professional_error(auth_user, veterinarian_only=True)
    if professional_error:
        return professional_error
    try:
        result = _integration_create_exame_imagem(auth_user, payload)
    except ValueError as exc:
        return _integration_error('invalid_exame_imagem_payload', str(exc), 400)
    return _integration_ok(result, 201)


@bp.route("/api/integrations/requesting-clinics", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_find_or_create_requesting_clinic():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    professional_error = _integration_professional_error(auth_user, veterinarian_only=True)
    if professional_error:
        return professional_error
    try:
        clinic, created = _integration_find_or_create_external_clinic(auth_user, {
            'nome': payload.get('nome_clinica'),
            'cnpj': payload.get('cnpj'),
            'email': payload.get('email'),
            'telefone': payload.get('telefone'),
        })
        db.session.commit()
    except ValueError as exc:
        return _integration_error('invalid_requesting_clinic_payload', str(exc), 400)
    return _integration_ok({'clinica': {'id': clinic.id, 'nome': clinic.nome, 'cnpj': clinic.cnpj, 'email': clinic.email, 'telefone': clinic.telefone, 'criada_agora': created}}, 201)


@bp.route("/api/integrations/exam-tutor-animal", methods=["POST"])
@csrf.exempt
@integration_bearer_required('tutors:write', 'pets:write')
def api_integrations_find_or_create_tutor_animal_for_exam():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    professional_error = _integration_professional_error(auth_user, veterinarian_only=True)
    if professional_error:
        return professional_error
    clinic_id = payload.get('clinica_id') or _integration_user_clinic_id(auth_user)
    clinic = db.session.get(Clinica, int(clinic_id or 0))
    if not clinic:
        return _integration_error('clinic_required', 'Informe clinica_id ou conecte um usuario com clinica vinculada.', 400)
    try:
        tutor, tutor_created, provisional = _integration_find_or_create_tutor_for_clinic(
            auth_user,
            clinic,
            {'nome': payload.get('nome_tutor'), 'telefone': payload.get('telefone'), 'email': payload.get('email')},
        )
        animal, animal_created = _integration_find_or_create_pet_for_tutor(
            auth_user,
            clinic,
            tutor,
            {'nome': payload.get('nome_animal'), 'especie': payload.get('especie'), 'idade': payload.get('idade'), 'raca': payload.get('raca'), 'sexo': payload.get('sexo')},
        )
        db.session.commit()
    except ValueError as exc:
        return _integration_error('invalid_tutor_animal_payload', str(exc), 400)
    return _integration_ok({
        'tutor': {'id': tutor.id, 'nome': tutor.name, 'criado_agora': tutor_created, 'email_provisorio': provisional},
        'animal': {'id': animal.id, 'nome': animal.name, 'criado_agora': animal_created},
        'clinica': {'id': clinic.id, 'nome': clinic.nome},
    }, 201)


@bp.route("/api/integrations/image-exams/pdf", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_attach_exame_imagem_pdf():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    exame = db.session.get(ExameImagem, int(payload.get('exame_id') or 0))
    if not exame:
        return _integration_error('exame_imagem_not_found', 'Exame de imagem nao encontrado.', 404)
    if getattr(auth_user, 'role', '') != 'admin' and exame.profissional_id != auth_user.id:
        return _integration_error('exame_imagem_forbidden', 'Somente o profissional criador pode anexar PDF.', 403)
    file_ref = _integration_extract_pdf_file_reference(payload)
    try:
        result = _integration_store_exame_pdf(auth_user, exame, file_ref)
    except ValueError as exc:
        return _integration_error('invalid_exame_imagem_pdf', str(exc), 400)
    return _integration_ok({'exame': result})


@bp.route("/api/integrations/image-exams/release-clinic", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_release_exame_to_clinic():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    try:
        result = _integration_release_exame_imagem(auth_user, payload, target='clinica')
    except PermissionError as exc:
        return _integration_error('exame_imagem_forbidden', str(exc), 403)
    except ValueError as exc:
        return _integration_error('invalid_exame_imagem_release', str(exc), 400)
    return _integration_ok({'exame': result})


@bp.route("/api/integrations/image-exams/release-tutor", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_release_exame_to_tutor():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    try:
        result = _integration_release_exame_imagem(auth_user, payload, target='tutor')
    except PermissionError as exc:
        return _integration_error('exame_imagem_forbidden', str(exc), 403)
    except ValueError as exc:
        return _integration_error('invalid_exame_imagem_release', str(exc), 400)
    return _integration_ok({'exame': result})


@bp.route("/api/integrations/clinic-first-access-invites", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_generate_clinic_first_access_invite():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    try:
        clinic = db.session.get(Clinica, int(payload.get('clinica_id'))) if payload.get('clinica_id') else None
        if not clinic and payload.get('nome_clinica'):
            clinic, _created = _integration_find_or_create_external_clinic(auth_user, {'nome': payload.get('nome_clinica'), 'email': payload.get('email'), 'telefone': payload.get('telefone')})
        if not clinic:
            raise ValueError('Informe clinica_id ou nome_clinica.')
        if not (payload.get('email') or payload.get('telefone') or clinic.email or clinic.telefone):
            raise ValueError('Informe email ou telefone para enviar o primeiro acesso da clinica.')
        _integration_ensure_clinic_admin_user(
            clinic,
            email=payload.get('email'),
            phone=payload.get('telefone'),
            name=payload.get('nome_responsavel') or payload.get('responsavel_nome'),
        )
        exame = db.session.get(ExameImagem, int(payload.get('exame_id'))) if payload.get('exame_id') else None
        if exame:
            _integration_reconcile_exam_documents(exame.animal, [exame])
        invite = _create_external_onboarding_invite('clinic', auth_user, clinic=clinic, tutor=getattr(exame, 'tutor', None), animal=getattr(exame, 'animal', None), exam=getattr(exame, 'exame_solicitado', None), exam_image=exame, message='Primeiro acesso gratuito da clinica requisitante.')
        db.session.commit()
    except ValueError as exc:
        return _integration_error('invalid_clinic_invite_payload', str(exc), 400)
    return _integration_ok({'convite': {'token': invite.token if invite else None, **_invite_payload(invite)}}, 201)


@bp.route("/api/integrations/tutor-access-invites", methods=["POST"])
@csrf.exempt
@integration_bearer_required('exams:write')
def api_integrations_generate_tutor_access_invite():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    try:
        tutor = db.session.get(User, int(payload.get('tutor_id'))) if payload.get('tutor_id') else None
        animal = db.session.get(Animal, int(payload.get('animal_id'))) if payload.get('animal_id') else None
        if not tutor and payload.get('nome_tutor') and animal and animal.owner:
            if _integration_normalize_match_text(animal.owner.name) == _integration_normalize_match_text(payload.get('nome_tutor')):
                tutor = animal.owner
        if not tutor or not animal or animal.user_id != tutor.id:
            raise ValueError('Informe tutor e animal vinculados.')
        exame = db.session.get(ExameImagem, int(payload.get('exame_id'))) if payload.get('exame_id') else None
        if exame:
            _integration_reconcile_exam_documents(exame.animal, [exame])
        invite = _create_external_onboarding_invite('tutor', auth_user, clinic=animal.clinica, tutor=tutor, animal=animal, exam=getattr(exame, 'exame_solicitado', None), exam_image=exame, message='Acesso restrito a ficha do proprio animal.')
        db.session.commit()
    except ValueError as exc:
        return _integration_error('invalid_tutor_invite_payload', str(exc), 400)
    return _integration_ok({'convite': {'token': invite.token if invite else None, **_invite_payload(invite)}}, 201)


@bp.route("/api/integrations/medical-history", methods=["GET"])
@integration_bearer_required('clinical_summary:read', 'exams:read')
def api_integrations_list_animal_medical_history():
    auth_user = g.integration_current_user
    animal = _integration_find_accessible_animal(auth_user, animal_id=request.args.get('animal_id', type=int), animal_name=request.args.get('nome_animal'))
    if not animal:
        return _integration_error('animal_not_found', 'Animal not found within the accessible integration scope.', 404)
    exames_imagem = _integration_list_exame_imagem_history(auth_user, animal)
    if _integration_reconcile_exam_documents(animal, exames_imagem):
        db.session.commit()
    allowed_document_ids = {exame.documento_id for exame in exames_imagem if exame.documento_id}
    documentos_query = AnimalDocumento.query.filter_by(animal_id=animal.id)
    if (getattr(auth_user, 'role', '') or '').lower() != 'admin':
        documentos_query = documentos_query.filter(AnimalDocumento.id.in_(allowed_document_ids or {0}))
    return _integration_ok({
        'animal': _serialize_calendar_pet(animal),
        'consultas': [
            {'id': c.id, 'data': _integration_format_datetime(c.created_at), 'titulo': c.queixa_principal or 'Consulta', 'status': c.status}
            for c in _integration_accessible_consultas_query(auth_user).filter(Consulta.animal_id == animal.id).order_by(Consulta.created_at.desc()).limit(20).all()
        ],
        'exames': [_integration_serialize_exame_imagem(exame, auth_user) for exame in exames_imagem],
        'documentos_anexados': [
            {'id': d.id, 'filename': d.filename, 'descricao': d.descricao, 'uploaded_at': _integration_format_datetime(d.uploaded_at), 'pdf_disponivel': bool(d.file_url)}
            for d in documentos_query.order_by(AnimalDocumento.uploaded_at.desc()).limit(20).all()
        ],
        'pdfs_disponiveis': [
            summary
            for summary in (
                _integration_exame_imagem_pdf_summary(exame, auth_user)
                for exame in exames_imagem
            )
            if summary
        ],
    })


@bp.route("/api/integrations/clinical-document", methods=["GET"])
@integration_bearer_required('exams:read')
def api_integrations_get_clinical_document():
    auth_user = g.integration_current_user
    exame = None
    if request.args.get('exame_id'):
        exame = db.session.get(ExameImagem, int(request.args.get('exame_id') or 0))
        if exame:
            _integration_reconcile_exam_documents(exame.animal, [exame])
    elif request.args.get('documento_id'):
        documento = db.session.get(AnimalDocumento, int(request.args.get('documento_id') or 0))
        if documento:
            exame = _integration_find_exame_by_documento(documento, auth_user)
    if not exame:
        return _integration_error('document_not_found', 'Documento clinico nao encontrado.', 404)
    if not _integration_user_can_access_exame_imagem(auth_user, exame):
        return _integration_error('document_forbidden', 'Sem permissao para acessar este documento.', 403)
    if exame.arquivo_pdf_url:
        db.session.add(ExameImagemPdfAccessLog(
            exame_imagem_id=exame.id,
            user_id=auth_user.id,
            action='view',
            ip_address=request.headers.get('X-Forwarded-For', request.remote_addr),
            user_agent=(request.headers.get('User-Agent') or '')[:255],
        ))
        db.session.commit()
    else:
        db.session.commit()
    return _integration_ok(_integration_exame_imagem_document_payload(exame, auth_user))


@bp.route("/api/integrations/appointments", methods=["POST"])
@csrf.exempt
@integration_bearer_required('appointments:write')
def api_integrations_create_appointment():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error

    animal = _mcp_find_animal_for_tool(auth_user, payload)
    if not animal:
        return _integration_error(
            'animal_not_found',
            'Animal not found within the accessible integration scope.',
            404,
        )
    try:
        appointment = _integration_schedule_consulta(auth_user, animal, payload)
    except PermissionError as exc:
        return _integration_error('professional_account_required', str(exc), 403)
    except ValueError as exc:
        return _integration_error('invalid_appointment_payload', str(exc), 400)

    return _integration_ok({
        'appointment_id': appointment.id,
        'animal_id': appointment.animal_id,
        'tipo': appointment.kind,
        'status': appointment.status,
        'scheduled_at': _integration_format_datetime(appointment.scheduled_at),
    }, 201)


@bp.route("/api/integrations/returns", methods=["POST"])
@csrf.exempt
@integration_bearer_required('appointments:write')
def api_integrations_create_return_appointment():
    auth_user = g.integration_current_user
    payload, error = _integration_request_json()
    if error:
        return error
    confirmation_error = _integration_confirmation_error(payload)
    if confirmation_error:
        return confirmation_error
    professional_error = _integration_professional_error(auth_user, veterinarian_only=True)
    if professional_error:
        return professional_error

    consulta_id = payload.get('consulta_id')
    try:
        consulta_id_int = int(consulta_id)
    except (TypeError, ValueError):
        return _integration_error('invalid_return_payload', 'consulta_id deve ser numerico.', 400)

    clinic_id = _integration_user_clinic_id(auth_user)
    consulta = (
        _integration_accessible_consultas_query(auth_user, clinic_id=clinic_id)
        .filter(Consulta.id == consulta_id_int)
        .first()
    )
    if not consulta:
        return _integration_error(
            'consultation_not_found',
            'Consulta nao encontrada no escopo disponivel para este usuario.',
            404,
        )

    try:
        result = schedule_return_appointment(
            consulta=consulta,
            actor_id=auth_user.id,
            actor_vet_id=getattr(getattr(auth_user, 'veterinario', None), 'id', None),
            payload=ReturnAppointmentDTO(
                date=_integration_parse_date_arg(payload.get('data')),
                time=_integration_parse_time_arg(payload.get('hora')),
                veterinarian_id=int(payload.get('veterinario_id') or auth_user.veterinario.id),
                reason=(payload.get('motivo') or '').strip() or None,
            ),
        )
    except ValueError as exc:
        return _integration_error('invalid_return_payload', str(exc), 400)
    if not result.success:
        return _integration_error('return_schedule_unavailable', result.message, 409)

    appointment = (
        Appointment.query
        .filter_by(consulta_id=consulta.id, kind='retorno')
        .order_by(Appointment.created_at.desc(), Appointment.id.desc())
        .first()
    )
    if not appointment:
        return _integration_error('return_schedule_unknown', result.message, 500)

    return _integration_ok({
        'appointment_id': appointment.id,
        'consulta_id': consulta.id,
        'animal_id': appointment.animal_id,
        'status': appointment.status,
        'scheduled_at': _integration_format_datetime(appointment.scheduled_at),
    }, 201)


@bp.route("/api/integrations/openapi.json", methods=["GET"])
def api_integrations_openapi():
    issuer = _oauth_issuer()
    scopes = {
        scope: scope
        for scope in sorted(_oauth_allowed_scopes())
    }
    write_confirmation = {
        'type': 'string',
        'description': 'Obrigatorio para acoes que gravam dados. Use exatamente "sim" apos confirmacao explicita do usuario.',
        'enum': ['sim'],
    }

    def ok_response(description='Resposta padrao da integracao.'):
        return {
            'description': description,
            'content': {
                'application/json': {
                    'schema': {
                        'type': 'object',
                        'properties': {'data': {'type': 'object'}},
                    }
                }
            },
        }

    def json_body(schema):
        return {
            'required': True,
            'content': {
                'application/json': {
                    'schema': schema,
                }
            },
        }

    spec = {
        'openapi': '3.1.0',
        'info': {
            'title': 'PetOrlandia ChatGPT Actions',
            'version': '1.0.0',
            'description': (
                'Actions para usar o PetOrlandia no ChatGPT com OAuth. '
                'Acoes de escrita exigem confirmar_gravacao="sim".'
            ),
            'x-logo': {
                'url': f'{issuer}/static/chatgpt_app_icon.png',
                'altText': 'PetOrlandia',
            },
        },
        'servers': [{'url': issuer}],
        'components': {
            'schemas': {},
            'securitySchemes': {
                'PetOrlandiaOAuth': {
                    'type': 'oauth2',
                    'flows': {
                        'authorizationCode': {
                            'authorizationUrl': f'{issuer}/oauth/authorize',
                            'tokenUrl': f'{issuer}/oauth/token',
                            'scopes': scopes,
                        }
                    },
                }
            }
        },
        'security': [{'PetOrlandiaOAuth': ['profile']}],
        'paths': {
            '/api/public/pricing': {
                'get': {
                    'operationId': 'obterPricingPublicoPetOrlandia',
                    'summary': 'Obter configuracao publica central de planos e precos',
                    'security': [],
                    'responses': {'200': ok_response('Pricing publico obtido.')},
                }
            },
            '/api/integrations/me': {
                'get': {
                    'operationId': 'obterPerfilPetOrlandia',
                    'summary': 'Obter perfil conectado',
                    'security': [{'PetOrlandiaOAuth': ['profile']}],
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/pets': {
                'get': {
                    'operationId': 'listarPetsPetOrlandia',
                    'summary': 'Listar pets acessiveis',
                    'security': [{'PetOrlandiaOAuth': ['pets:read']}],
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/appointments': {
                'get': {
                    'operationId': 'listarAgendamentosPetOrlandia',
                    'summary': 'Listar agendamentos acessiveis',
                    'security': [{'PetOrlandiaOAuth': ['appointments:read']}],
                    'responses': {'200': ok_response()},
                },
                'post': {
                    'operationId': 'agendarConsultaPetOrlandia',
                    'summary': 'Agendar consulta, vacina ou retorno para um pet',
                    'description': 'Acao consequencial. Confirme com o usuario antes de enviar.',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['appointments:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'animal_id': {'type': 'integer'},
                            'nome_animal': {'type': 'string'},
                            'veterinario_id': {'type': 'integer'},
                            'data': {'type': 'string', 'format': 'date'},
                            'hora': {'type': 'string', 'description': 'HH:MM'},
                            'tipo': {'type': 'string'},
                            'motivo': {'type': 'string'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['data', 'hora', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Agendamento criado.')},
                },
            },
            '/api/integrations/clinical-summary/{animal_id}': {
                'get': {
                    'operationId': 'obterResumoClinicoPetOrlandia',
                    'summary': 'Obter resumo clinico de um animal',
                    'security': [{'PetOrlandiaOAuth': ['clinical_summary:read']}],
                    'parameters': [{'name': 'animal_id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}}],
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/today-agenda': {
                'get': {
                    'operationId': 'listarAgendaDoDiaPetOrlandia',
                    'summary': 'Listar agenda do dia',
                    'security': [{'PetOrlandiaOAuth': ['appointments:read']}],
                    'parameters': [{'name': 'date', 'in': 'query', 'required': False, 'schema': {'type': 'string', 'format': 'date'}}],
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/clinical-pendencies': {
                'get': {
                    'operationId': 'listarPendenciasClinicasPetOrlandia',
                    'summary': 'Listar pendencias clinicas',
                    'security': [{'PetOrlandiaOAuth': ['appointments:read', 'exams:read', 'vaccines:read']}],
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/tutor-guidance/{animal_id}': {
                'get': {
                    'operationId': 'gerarOrientacaoTutorPetOrlandia',
                    'summary': 'Gerar orientacao ao tutor',
                    'security': [{'PetOrlandiaOAuth': ['tutor_guidance:generate']}],
                    'parameters': [
                        {'name': 'animal_id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}},
                        {'name': 'consulta_id', 'in': 'query', 'required': False, 'schema': {'type': 'integer'}},
                    ],
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/handoff/{animal_id}': {
                'get': {
                    'operationId': 'gerarHandoffClinicoPetOrlandia',
                    'summary': 'Gerar handoff clinico',
                    'security': [{'PetOrlandiaOAuth': ['handoff:read']}],
                    'parameters': [
                        {'name': 'animal_id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}},
                        {'name': 'consulta_id', 'in': 'query', 'required': False, 'schema': {'type': 'integer'}},
                    ],
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/intake/interpret': {
                'post': {
                    'operationId': 'interpretarMensagemLivrePetOrlandia',
                    'summary': 'Interpretar mensagem livre sem gravar dados',
                    'security': [{'PetOrlandiaOAuth': ['profile']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'texto': {'type': 'string'},
                            'mensagens': {'type': 'array', 'items': {'type': 'object'}},
                        },
                    }),
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/assistant': {
                'post': {
                    'operationId': 'assistenteOperacionalPetOrlandia',
                    'summary': 'Planejar ou executar acao operacional por texto livre',
                    'description': 'Sem confirmar_gravacao, apenas planeja. Com confirmar_gravacao="sim", pode gravar dados.',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['profile', 'tutors:write', 'pets:write', 'appointments:write', 'consultations:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'texto': {'type': 'string'},
                            'mensagens': {'type': 'array', 'items': {'type': 'object'}},
                            'confirmar_gravacao': write_confirmation,
                        },
                    }),
                    'responses': {'200': ok_response()},
                }
            },
            '/api/integrations/tutors-with-pets': {
                'post': {
                    'operationId': 'cadastrarTutorEPetsPetOrlandia',
                    'summary': 'Cadastrar ou reaproveitar tutor e pets',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['tutors:write', 'pets:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'tutor': {'type': 'object'},
                            'pets': {'type': 'array', 'items': {'type': 'object'}},
                            'observacao_clinica': {'type': 'string'},
                            'disponibilidade': {'type': 'string'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['tutor', 'pets', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Tutor e pets cadastrados ou reaproveitados.')},
                }
            },
            '/api/integrations/consultations': {
                'post': {
                    'operationId': 'registrarConsultaClinicaPetOrlandia',
                    'summary': 'Registrar ou atualizar consulta clinica',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['consultations:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'animal_id': {'type': 'integer'},
                            'nome_animal': {'type': 'string'},
                            'consulta_id': {'type': 'integer'},
                            'queixa_principal': {'type': 'string'},
                            'historico_clinico': {'type': 'string'},
                            'exame_fisico': {'type': 'string'},
                            'diagnostico': {'type': 'string'},
                            'conduta': {'type': 'string'},
                            'exames_solicitados': {'type': 'string'},
                            'prescricao': {'type': 'string'},
                            'finalizar': {'type': 'boolean'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Consulta criada ou atualizada.')},
                }
            },
            '/api/integrations/exam-blocks': {
                'post': {
                    'operationId': 'registrarBlocoExamesPetOrlandia',
                    'summary': 'Registrar bloco de exames',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'animal_id': {'type': 'integer'},
                            'nome_animal': {'type': 'string'},
                            'observacoes_gerais': {'type': 'string'},
                            'exames': {'type': 'array', 'items': {'type': 'object'}},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['exames', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Bloco de exames criado.')},
                }
            },
            '/api/integrations/image-exams': {
                'post': {
                    'operationId': 'criarExameImagemPetOrlandia',
                    'summary': 'Criar exame de imagem vinculado a animal, tutor e clinica requisitante',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'animal_id': {'type': 'integer'},
                            'nome_animal': {'type': 'string'},
                            'tutor_id': {'type': 'integer'},
                            'nome_tutor': {'type': 'string'},
                            'clinica_id': {'type': 'integer'},
                            'nome_clinica': {'type': 'string'},
                            'tipo_exame': {'type': 'string'},
                            'data_exame': {'type': 'string'},
                            'profissional_nome': {'type': 'string'},
                            'profissional_crmv': {'type': 'string'},
                            'descricao': {'type': 'string'},
                            'impressao_diagnostica': {'type': 'string'},
                            'status': {'type': 'string', 'enum': ['rascunho', 'finalizado', 'liberado_para_clinica', 'liberado_para_tutor']},
                            'finalizar': {'type': 'boolean'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['tipo_exame', 'data_exame', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Exame de imagem criado.')},
                }
            },
            '/api/integrations/requesting-clinics': {
                'post': {
                    'operationId': 'buscarOuCriarClinicaRequisitantePetOrlandia',
                    'summary': 'Buscar ou criar clinica requisitante para exame de imagem',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'nome_clinica': {'type': 'string'},
                            'cnpj': {'type': 'string'},
                            'email': {'type': 'string'},
                            'telefone': {'type': 'string'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['nome_clinica', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Clinica requisitante encontrada ou criada.')},
                }
            },
            '/api/integrations/exam-tutor-animal': {
                'post': {
                    'operationId': 'buscarOuCriarTutorAnimalPetOrlandia',
                    'summary': 'Buscar ou criar tutor e animal para fluxo de exame',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['tutors:write', 'pets:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'clinica_id': {'type': 'integer'},
                            'nome_tutor': {'type': 'string'},
                            'telefone': {'type': 'string'},
                            'email': {'type': 'string'},
                            'nome_animal': {'type': 'string'},
                            'especie': {'type': 'string'},
                            'idade': {'type': 'string'},
                            'raca': {'type': 'string'},
                            'sexo': {'type': 'string'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['nome_tutor', 'nome_animal', 'especie', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Tutor e animal encontrados ou criados.')},
                }
            },
            '/api/integrations/image-exams/pdf': {
                'post': {
                    'operationId': 'anexarPdfExameImagemPetOrlandia',
                    'summary': 'Anexar PDF ao exame de imagem',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'exame_id': {'type': 'integer'},
                            'arquivo_pdf': MCP_FILE_REFERENCE_SCHEMA,
                            'attachment_id': MCP_FILE_REFERENCE_OR_STRING_SCHEMA,
                            'download_url': {'type': 'string'},
                            'file_name': {'type': 'string'},
                            'mime_type': {'type': 'string'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['exame_id', 'confirmar_gravacao'],
                    }),
                    'responses': {'200': ok_response('PDF anexado.')},
                }
            },
            '/api/integrations/image-exams/release-clinic': {
                'post': {
                    'operationId': 'liberarExameParaClinicaPetOrlandia',
                    'summary': 'Liberar exame de imagem para a clinica requisitante',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {'exame_id': {'type': 'integer'}, 'clinica_id': {'type': 'integer'}, 'confirmar_gravacao': write_confirmation},
                        'required': ['exame_id', 'clinica_id', 'confirmar_gravacao'],
                    }),
                    'responses': {'200': ok_response('Exame liberado para clinica.')},
                }
            },
            '/api/integrations/image-exams/release-tutor': {
                'post': {
                    'operationId': 'liberarExameParaTutorPetOrlandia',
                    'summary': 'Liberar exame de imagem para o tutor',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {'exame_id': {'type': 'integer'}, 'tutor_id': {'type': 'integer'}, 'confirmar_gravacao': write_confirmation},
                        'required': ['exame_id', 'tutor_id', 'confirmar_gravacao'],
                    }),
                    'responses': {'200': ok_response('Exame liberado para tutor.')},
                }
            },
            '/api/integrations/clinic-first-access-invites': {
                'post': {
                    'operationId': 'gerarConvitePrimeiroAcessoClinicaPetOrlandia',
                    'summary': 'Gerar convite de primeiro acesso gratuito da clinica',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {'clinica_id': {'type': 'integer'}, 'nome_clinica': {'type': 'string'}, 'email': {'type': 'string'}, 'telefone': {'type': 'string'}, 'exame_id': {'type': 'integer'}, 'confirmar_gravacao': write_confirmation},
                        'required': ['confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Convite da clinica gerado.')},
                }
            },
            '/api/integrations/tutor-access-invites': {
                'post': {
                    'operationId': 'gerarConviteAcessoTutorPetOrlandia',
                    'summary': 'Gerar convite de acesso restrito do tutor',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['exams:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {'tutor_id': {'type': 'integer'}, 'nome_tutor': {'type': 'string'}, 'animal_id': {'type': 'integer'}, 'exame_id': {'type': 'integer'}, 'confirmar_gravacao': write_confirmation},
                        'required': ['animal_id', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Convite do tutor gerado.')},
                }
            },
            '/api/integrations/medical-history': {
                'get': {
                    'operationId': 'listarHistoricoMedicoAnimalPetOrlandia',
                    'summary': 'Listar historico medico do animal com links humanos de portal ou download',
                    'security': [{'PetOrlandiaOAuth': ['clinical_summary:read', 'exams:read']}],
                    'parameters': [
                        {'name': 'animal_id', 'in': 'query', 'required': False, 'schema': {'type': 'integer'}},
                        {'name': 'nome_animal', 'in': 'query', 'required': False, 'schema': {'type': 'string'}},
                    ],
                    'responses': {'200': ok_response('Historico medico listado.')},
                }
            },
            '/api/integrations/clinical-document': {
                'get': {
                    'operationId': 'obterDocumentoClinicoPetOrlandia',
                    'summary': 'Obter documento clinico com shareable_url para usuario final e metadado tecnico protegido',
                    'security': [{'PetOrlandiaOAuth': ['exams:read']}],
                    'parameters': [
                        {'name': 'exame_id', 'in': 'query', 'required': False, 'schema': {'type': 'integer'}},
                        {'name': 'documento_id', 'in': 'query', 'required': False, 'schema': {'type': 'integer'}},
                    ],
                    'responses': {'200': ok_response('Documento clinico obtido.')},
                }
            },
            '/api/integrations/returns': {
                'post': {
                    'operationId': 'agendarRetornoPetOrlandia',
                    'summary': 'Agendar retorno a partir de consulta existente',
                    'x-openai-isConsequential': True,
                    'security': [{'PetOrlandiaOAuth': ['appointments:write']}],
                    'requestBody': json_body({
                        'type': 'object',
                        'properties': {
                            'consulta_id': {'type': 'integer'},
                            'data': {'type': 'string', 'format': 'date'},
                            'hora': {'type': 'string', 'description': 'HH:MM'},
                            'veterinario_id': {'type': 'integer'},
                            'motivo': {'type': 'string'},
                            'confirmar_gravacao': write_confirmation,
                        },
                        'required': ['consulta_id', 'data', 'hora', 'confirmar_gravacao'],
                    }),
                    'responses': {'201': ok_response('Retorno agendado.')},
                }
            },
        },
    }
    return jsonify(spec)


@bp.route("/api/my_pets", methods=["GET"])
@login_required
def api_my_pets():
    """Return the authenticated tutor's pets ordered by recency."""
    pets = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
        )
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.date_added.desc())
        .all()
    )
    return jsonify([_serialize_calendar_pet(p) for p in pets])


@bp.route("/api/public/pricing", methods=["GET"])
def api_public_pricing():
    return jsonify(_public_pricing_config())


@bp.route("/api/clinic_pets", methods=["GET"])
@login_required
def api_clinic_pets():
    """Return pets associated with the current clinic (or admin selection)."""

    if not has_professional_access(current_user) and current_user.role != 'admin':
        return api_my_pets()

    clinic_id = None
    view_as = request.args.get('view_as')

    if current_user.role == 'admin':
        if view_as == 'veterinario':
            vet_id = request.args.get('veterinario_id', type=int)
            if vet_id:
                veterinario = Veterinario.query.get(vet_id)
                clinic_id = veterinario.clinica_id if veterinario else None
        elif view_as == 'colaborador':
            colaborador_id = request.args.get('colaborador_id', type=int)
            if colaborador_id:
                colaborador = User.query.get(colaborador_id)
                clinic_id = colaborador.clinica_id if colaborador else None
        if clinic_id is None:
            clinic_id = request.args.get('clinica_id', type=int)
        if clinic_id is None:
            # Default to the first accessible clinic for the admin, if any.
            clinic_rows = clinicas_do_usuario().with_entities(Clinica.id).all()
            for row in clinic_rows:
                try:
                    clinic_id = row[0]
                except (TypeError, IndexError):
                    clinic_id = getattr(row, 'id', None)
                if clinic_id:
                    break
    else:
        clinic_id = current_user_clinic_id()

    if not clinic_id:
        return jsonify([])

    last_appt = (
        db.session.query(
            Appointment.animal_id,
            func.max(Appointment.scheduled_at).label('last_at'),
        )
        .filter(Appointment.clinica_id == clinic_id)
        .group_by(Appointment.animal_id)
        .subquery()
    )

    pets = (
        Animal.query
        .options(
            joinedload(Animal.species),
            joinedload(Animal.breed),
            joinedload(Animal.owner),
        )
        .outerjoin(last_appt, Animal.id == last_appt.c.animal_id)
        .filter(Animal.removido_em.is_(None))
        .filter(
            or_(
                Animal.clinica_id == clinic_id,
                last_appt.c.last_at.isnot(None),
            )
        )
        .order_by(func.coalesce(last_appt.c.last_at, Animal.date_added).desc())
        .all()
    )

    return jsonify([_serialize_calendar_pet(p) for p in pets])


@bp.route("/api/my_appointments", methods=["GET"])
@login_required
def api_my_appointments():
    """Return the current user's appointments as calendar events."""
    from models import (
        Appointment,
        ExamAppointment,
        Vacina,
        Animal,
        Veterinario,
        User,
        Clinica,
    )

    query = Appointment.query
    calendar_window = _calendar_window_from_request()
    is_vet = is_veterinarian(current_user)
    context = {
        'mode': None,
        'tutor_id': None,
        'vet': None,
        'clinic_ids': [],
    }
    is_vet = is_veterinarian(current_user)

    is_vet = is_veterinarian(current_user)

    if current_user.role == 'admin':
        def _coerce_first_int(values):
            if values is None:
                return None
            if isinstance(values, (list, tuple)):
                values = values[0] if values else None
            if values in (None, ""):
                return None
            try:
                return int(values)
            except (TypeError, ValueError):
                return None

        def _admin_view_context():
            referrer_params = {}
            if request.referrer:
                parsed = urlparse(request.referrer)
                referrer_params = parse_qs(parsed.query)
            view_as = request.args.get('view_as') or referrer_params.get('view_as', [None])[0]
            vet_id = request.args.get('veterinario_id', type=int)
            if vet_id is None:
                vet_id = _coerce_first_int(referrer_params.get('veterinario_id'))
            clinic_id = request.args.get('clinica_id', type=int)
            if clinic_id is None:
                clinic_id = _coerce_first_int(referrer_params.get('clinica_id'))
            tutor_id = request.args.get('tutor_id', type=int)
            if tutor_id is None:
                tutor_id = _coerce_first_int(referrer_params.get('tutor_id'))
            return view_as, vet_id, clinic_id, tutor_id

        accessible_clinic_ids = None

        def _accessible_clinic_ids():
            nonlocal accessible_clinic_ids
            if accessible_clinic_ids is None:
                rows = clinicas_do_usuario().with_entities(Clinica.id).all()
                clinic_ids = []
                for row in rows:
                    try:
                        clinic_id_value = row[0]
                    except (TypeError, IndexError):
                        clinic_id_value = getattr(row, 'id', None)
                    if clinic_id_value is None or clinic_id_value in clinic_ids:
                        continue
                    clinic_ids.append(clinic_id_value)
                accessible_clinic_ids = clinic_ids
            return accessible_clinic_ids

        view_as, vet_id, clinic_id, tutor_id = _admin_view_context()

        context['clinic_ids'] = list(_accessible_clinic_ids())
        if view_as == 'tutor' and tutor_id:
            context['mode'] = 'tutor'
            context['tutor_id'] = tutor_id
        elif view_as == 'veterinario':
            target_vet = Veterinario.query.get(vet_id) if vet_id else None
            context['mode'] = 'veterinario'
            context['vet'] = target_vet
            target_clinics = []
            if clinic_id:
                target_clinics.append(clinic_id)
            elif context['clinic_ids']:
                target_clinics.extend(context['clinic_ids'])
            context['clinic_ids'] = [cid for cid in target_clinics if cid]
        elif view_as == 'colaborador':
            target_clinics = []
            if clinic_id:
                target_clinics.append(clinic_id)
            elif context['clinic_ids']:
                target_clinics.extend(context['clinic_ids'])
            context['mode'] = 'clinics'
            context['clinic_ids'] = [cid for cid in target_clinics if cid]
        else:
            context['mode'] = 'clinics'

        def _creator_clinic_filter(clinic_ids):
            sanitized = [cid for cid in (clinic_ids or []) if cid]
            if not sanitized:
                return None
            return Appointment.creator.has(
                or_(
                    User.clinica_id.in_(sanitized),
                    User.veterinario.has(
                        or_(
                            Veterinario.clinica_id.in_(sanitized),
                            Veterinario.clinicas.any(Clinica.id.in_(sanitized)),
                        )
                    ),
                )
            )

        if view_as == 'veterinario':
            if not vet_id and getattr(current_user, 'veterinario', None):
                vet_id = current_user.veterinario.id
            filters = []
            if vet_id:
                filters.append(Appointment.veterinario_id == vet_id)
                target_vet = target_vet or Veterinario.query.get(vet_id)
            target_vet_user_id = getattr(target_vet, 'user_id', None) if target_vet else None
            if target_vet_user_id:
                filters.append(Appointment.created_by == target_vet_user_id)
            if filters:
                query = query.filter(or_(*filters) if len(filters) > 1 else filters[0])
        elif view_as == 'colaborador':
            clinic_ids = list(_accessible_clinic_ids())
            if clinic_id and clinic_id not in clinic_ids:
                clinic_ids.append(clinic_id)
            if clinic_ids:
                creator_filter = _creator_clinic_filter(clinic_ids)
                clinic_filters = [Appointment.clinica_id.in_(clinic_ids)]
                if creator_filter is not None:
                    clinic_filters.append(creator_filter)
                query = query.filter(
                    or_(*clinic_filters)
                    if len(clinic_filters) > 1
                    else clinic_filters[0]
                )
        elif view_as == 'tutor':
            target_tutor_id = tutor_id or current_user.id
            query = query.filter(Appointment.tutor_id == target_tutor_id)
        else:
            clinic_ids = _accessible_clinic_ids()
            if clinic_ids:
                creator_filter = _creator_clinic_filter(clinic_ids)
                clinic_filters = [
                    Appointment.clinica_id.in_(clinic_ids),
                    Appointment.veterinario.has(
                        Veterinario.clinica_id.in_(clinic_ids)
                    ),
                ]
                if creator_filter is not None:
                    clinic_filters.append(creator_filter)
                query = query.filter(
                    or_(*clinic_filters)
                    if len(clinic_filters) > 1
                    else clinic_filters[0]
                )
            if not context['clinic_ids']:
                context['clinic_ids'] = [cid for cid in (clinic_ids or []) if cid]
            context['mode'] = context['mode'] or 'clinics'
    elif is_vet:
        query = query.filter(
            or_(
                Appointment.veterinario_id == current_user.veterinario.id,
                Appointment.created_by == current_user.id,
            )
        )
        vet_profile = current_user.veterinario
        context['mode'] = 'veterinario'
        context['vet'] = vet_profile
        clinic_ids = []
        primary_clinic = getattr(vet_profile, 'clinica_id', None)
        if primary_clinic:
            clinic_ids.append(primary_clinic)
        for clinic in getattr(vet_profile, 'clinicas', []) or []:
            clinic_id_value = getattr(clinic, 'id', None)
            if clinic_id_value and clinic_id_value not in clinic_ids:
                clinic_ids.append(clinic_id_value)
        context['clinic_ids'] = clinic_ids
    elif current_user.worker == 'colaborador' and current_user.clinica_id:
        query = query.filter(
            or_(
                Appointment.clinica_id == current_user.clinica_id,
                Appointment.created_by == current_user.id,
            )
        )
        context['mode'] = 'clinics'
        context['clinic_ids'] = [current_user.clinica_id]
    else:
        query = query.filter_by(tutor_id=current_user.id)
        context['mode'] = 'tutor'
        context['tutor_id'] = current_user.id

    query = _apply_calendar_datetime_window(query, Appointment.scheduled_at, calendar_window)
    appts = query.order_by(Appointment.scheduled_at).all()
    events = appointments_to_events(appts)

    existing_event_ids = set()
    for event in events:
        event_id = event.get('id') if isinstance(event, dict) else None
        if event_id:
            existing_event_ids.add(event_id)

    def _append_event(event):
        if not event or not isinstance(event, dict):
            return
        event_id = event.get('id')
        if event_id and event_id in existing_event_ids:
            return
        events.append(event)
        if event_id:
            existing_event_ids.add(event_id)

    def _extend_exam_events(*, or_filters=None, and_filters=None):
        query_obj = ExamAppointment.query.outerjoin(ExamAppointment.animal)
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        query_obj = _apply_calendar_datetime_window(
            query_obj,
            ExamAppointment.scheduled_at,
            calendar_window,
        )
        exam_items = query_obj.order_by(ExamAppointment.scheduled_at).all()
        for exam in unique_items_by_id(exam_items):
            event = exam_to_event(exam)
            if event:
                _append_event(event)

    def _extend_vaccine_events(*, or_filters=None, and_filters=None):
        query_obj = Vacina.query.outerjoin(Vacina.animal)
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        query_obj = _apply_calendar_date_window(
            query_obj,
            Vacina.aplicada_em,
            calendar_window,
        )
        vaccine_items = query_obj.order_by(Vacina.aplicada_em).all()
        for vaccine in unique_items_by_id(vaccine_items):
            event = vaccine_to_event(vaccine)
            if event:
                _append_event(event)

    def _extend_consulta_events(*, or_filters=None, and_filters=None):
        query_obj = (
            Consulta.query
            .outerjoin(Consulta.animal)
            .options(
                joinedload(Consulta.animal).joinedload(Animal.owner),
                joinedload(Consulta.veterinario),
                joinedload(Consulta.clinica),
            )
            .filter(Consulta.status == 'finalizada')
        )
        and_conditions = [cond for cond in (and_filters or []) if cond is not None]
        if and_conditions:
            query_obj = query_obj.filter(*and_conditions)
        or_conditions = [cond for cond in (or_filters or []) if cond is not None]
        if or_conditions:
            query_obj = query_obj.filter(or_(*or_conditions))
        query_obj = _apply_calendar_datetime_window(
            query_obj,
            func.coalesce(Consulta.finalizada_em, Consulta.created_at),
            calendar_window,
        )
        consulta_items = query_obj.order_by(Consulta.created_at).all()
        for consulta in unique_items_by_id(consulta_items):
            event = consulta_to_event(consulta)
            if event:
                _append_event(event)

    def _extend_for_tutor(tutor_id):
        if not tutor_id:
            return
        tutor_vet = None
        if current_user.is_authenticated and current_user.id == tutor_id:
            tutor_vet = getattr(current_user, 'veterinario', None)
        else:
            tutor_obj = User.query.get(tutor_id)
            tutor_vet = getattr(tutor_obj, 'veterinario', None) if tutor_obj else None
        or_filters = [
            ExamAppointment.requester_id == tutor_id,
            Animal.user_id == tutor_id,
        ]
        if tutor_vet:
            or_filters.append(ExamAppointment.specialist_id == tutor_vet.id)
        _extend_exam_events(or_filters=or_filters)
        _extend_vaccine_events(
            or_filters=[
                Animal.user_id == tutor_id,
                Vacina.aplicada_por == tutor_id,
            ],
            and_filters=[
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            ],
        )
        _extend_consulta_events(or_filters=[Animal.user_id == tutor_id])

    def _extend_for_vet(vet_profile, clinic_ids=None):
        if not vet_profile:
            return
        vet_id = getattr(vet_profile, 'id', None)
        if not vet_id:
            return
        sanitized_clinic_ids = [cid for cid in (clinic_ids or []) if cid]
        vet_user_id = getattr(vet_profile, 'user_id', None)
        exam_filters = [ExamAppointment.specialist_id == vet_id]
        exam_filters.append(ExamAppointment.status.in_(['pending', 'confirmed']))
        if sanitized_clinic_ids:
            exam_filters.append(
                or_(
                    Animal.clinica_id.in_(sanitized_clinic_ids),
                    ExamAppointment.specialist.has(
                        Veterinario.clinica_id.in_(sanitized_clinic_ids)
                    ),
                )
            )
        _extend_exam_events(and_filters=exam_filters)

        vaccine_filters = [
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em >= date.today(),
        ]
        vet_user_id = getattr(vet_profile, 'user_id', None)
        if vet_user_id:
            vaccine_filters.append(Vacina.aplicada_por == vet_user_id)
        if sanitized_clinic_ids:
            vaccine_filters.append(Animal.clinica_id.in_(sanitized_clinic_ids))
        _extend_vaccine_events(and_filters=vaccine_filters)

        consulta_filters = []
        if vet_user_id:
            consulta_filters.append(Consulta.created_by == vet_user_id)
        if sanitized_clinic_ids:
            consulta_filters.append(Consulta.clinica_id.in_(sanitized_clinic_ids))
        if consulta_filters:
            _extend_consulta_events(and_filters=consulta_filters)

    def _extend_for_clinics(clinic_ids):
        sanitized = [cid for cid in (clinic_ids or []) if cid]
        if not sanitized:
            return
        clinic_filters = [
            or_(
                Animal.clinica_id.in_(sanitized),
                ExamAppointment.specialist.has(
                    Veterinario.clinica_id.in_(sanitized)
                ),
            ),
            ExamAppointment.status.in_(['pending', 'confirmed']),
        ]
        _extend_exam_events(and_filters=clinic_filters)
        vaccine_filters = [
            Animal.clinica_id.in_(sanitized),
            Vacina.aplicada_em.isnot(None),
            Vacina.aplicada_em >= date.today(),
        ]
        _extend_vaccine_events(and_filters=vaccine_filters)
        _extend_consulta_events(and_filters=[Consulta.clinica_id.in_(sanitized)])

    if context['mode'] == 'tutor':
        _extend_for_tutor(context.get('tutor_id'))
    elif context['mode'] == 'veterinario':
        _extend_for_vet(context.get('vet'), context.get('clinic_ids'))
    elif context['mode'] == 'clinics':
        _extend_for_clinics(context.get('clinic_ids'))

    return jsonify(events)


@bp.route("/api/user_appointments/<int:user_id>", methods=["GET"])
@login_required
def api_user_appointments(user_id):
    """Return appointments for the selected user (admin only)."""
    if current_user.role != 'admin':
        abort(403)

    user = get_user_or_404(user_id)
    vet = getattr(user, 'veterinario', None)
    calendar_window = _calendar_window_from_request()

    appointment_filters = [Appointment.tutor_id == user.id]
    if vet:
        appointment_filters.append(Appointment.veterinario_id == vet.id)
    appointments_query = Appointment.query.filter(or_(*appointment_filters))
    appointments_query = _apply_calendar_datetime_window(
        appointments_query,
        Appointment.scheduled_at,
        calendar_window,
    )
    appointments = appointments_query.order_by(Appointment.scheduled_at).all()

    events = appointments_to_events(appointments)

    exam_filters = [ExamAppointment.requester_id == user.id]
    if vet:
        exam_filters.append(ExamAppointment.specialist_id == vet.id)
    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_filters.append(Animal.user_id == user.id)
    if exam_filters:
        exam_query = _apply_calendar_datetime_window(
            exam_query,
            ExamAppointment.scheduled_at,
            calendar_window,
        )
        exam_appointments = (
            exam_query.filter(or_(*exam_filters))
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        for exam in unique_items_by_id(exam_appointments):
            event = exam_to_event(exam)
            if event:
                events.append(event)

    vaccine_filters = [Animal.user_id == user.id, Vacina.aplicada_por == user.id]
    vaccine_query = Vacina.query.outerjoin(Vacina.animal)
    if vaccine_filters:
        vaccine_query = _apply_calendar_date_window(
            vaccine_query,
            Vacina.aplicada_em,
            calendar_window,
        )
        vaccine_appointments = (
            vaccine_query.filter(
                or_(*vaccine_filters),
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            )
            .order_by(Vacina.aplicada_em)
            .all()
        )
        for vac in unique_items_by_id(vaccine_appointments):
            event = vaccine_to_event(vac)
            if event:
                events.append(event)

    return jsonify(events)


@bp.route("/api/appointments/<int:appointment_id>/reschedule", methods=["POST"])
@login_required
def api_reschedule_appointment(appointment_id):
    """Update the schedule of an appointment after drag & drop operations."""

    appointment = Appointment.query.get_or_404(appointment_id)

    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if is_vet or is_collaborator:
        if is_vet:
            user_clinic = current_user.veterinario.clinica_id
        else:
            user_clinic = current_user.clinica_id
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id
        if appointment_clinic != user_clinic:
            abort(403)
    elif current_user.role != 'admin' and appointment.tutor_id != current_user.id:
        abort(403)

    data = request.get_json(silent=True) or {}
    start_str = data.get('start') or data.get('startStr')

    def _parse_client_datetime(value):
        if not value or not isinstance(value, str):
            return None
        value = value.strip()
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    new_start = _parse_client_datetime(start_str)
    if not new_start:
        return jsonify({'success': False, 'message': 'Horário inválido.'}), 400

    if new_start.tzinfo is None:
        new_start_local = new_start
    else:
        new_start_local = new_start.astimezone(BR_TZ).replace(tzinfo=None)

    new_start_utc = normalize_to_utc(new_start)

    existing_local = coerce_to_brazil_tz(appointment.scheduled_at).replace(tzinfo=None)

    if (
        not is_slot_available(appointment.veterinario_id, new_start_local, kind=appointment.kind)
        and new_start_local != existing_local
    ):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.',
        }), 400

    appointment.scheduled_at = new_start_utc
    db.session.commit()

    updated_start = to_timezone_aware(appointment.scheduled_at)
    return jsonify({
        'success': True,
        'message': 'Agendamento atualizado com sucesso.',
        'start': updated_start.isoformat() if updated_start else None,
    })


@bp.route("/api/clinic_appointments/<int:clinica_id>", methods=["GET"])
@login_required
def api_clinic_appointments(clinica_id):
    """Return appointments for a clinic as calendar events."""
    ensure_clinic_access(clinica_id)
    from models import User, Clinica
    calendar_window = _calendar_window_from_request()

    calendar_access_scope = get_calendar_access_scope(current_user)
    full_calendar_clinic_ids = calendar_access_scope.full_access_clinic_ids
    has_full_clinic_access = calendar_access_scope.allows_all_veterinarians()
    if not has_full_clinic_access:
        if full_calendar_clinic_ids is None:
            has_full_clinic_access = True
        else:
            has_full_clinic_access = clinica_id in full_calendar_clinic_ids

    allowed_veterinarian_ids: Optional[Set[int]] = None
    if not has_full_clinic_access:
        vet_scope = calendar_access_scope.veterinarian_ids or set()
        allowed_veterinarian_ids = set(vet_scope)

    creator_filter = Appointment.creator.has(
        or_(
            User.clinica_id == clinica_id,
            User.veterinario.has(
                or_(
                    Veterinario.clinica_id == clinica_id,
                    Veterinario.clinicas.any(Clinica.id == clinica_id),
                )
            ),
        )
    )

    appt_filters = [Appointment.clinica_id == clinica_id, creator_filter]
    appt_query = Appointment.query.filter(or_(*appt_filters))
    appt_query = _apply_calendar_datetime_window(
        appt_query,
        Appointment.scheduled_at,
        calendar_window,
    )
    appts = appt_query.order_by(Appointment.scheduled_at).all()

    if allowed_veterinarian_ids is not None:
        appts = [
            appt
            for appt in appts
            if getattr(appt, 'veterinario_id', None) in allowed_veterinarian_ids
        ]

    events = appointments_to_events(appts)

    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_query = _apply_calendar_datetime_window(
        exam_query,
        ExamAppointment.scheduled_at,
        calendar_window,
    )
    exam_appointments = (
        exam_query
        .filter(
            or_(
                Animal.clinica_id == clinica_id,
                ExamAppointment.specialist.has(Veterinario.clinica_id == clinica_id),
            ),
            ExamAppointment.status.in_(['pending', 'confirmed']),
        )
        .order_by(ExamAppointment.scheduled_at)
        .all()
    )

    if allowed_veterinarian_ids is not None:
        exam_appointments = [
            exam
            for exam in exam_appointments
            if getattr(exam, 'specialist_id', None) in allowed_veterinarian_ids
        ]

    for exam in unique_items_by_id(exam_appointments):
        event = exam_to_event(exam)
        if event:
            events.append(event)

    vaccine_events: list[dict] = []
    if has_full_clinic_access:
        vaccine_query = Vacina.query.outerjoin(Vacina.animal)
        vaccine_query = _apply_calendar_date_window(
            vaccine_query,
            Vacina.aplicada_em,
            calendar_window,
        )
        vaccine_appointments = (
            vaccine_query
            .filter(
                Animal.clinica_id == clinica_id,
                Vacina.aplicada_em.isnot(None),
                Vacina.aplicada_em >= date.today(),
            )
            .order_by(Vacina.aplicada_em)
            .all()
        )
        for vaccine in unique_items_by_id(vaccine_appointments):
            event = vaccine_to_event(vaccine)
            if event:
                vaccine_events.append(event)

    events.extend(vaccine_events)

    consulta_query = (
        Consulta.query
        .outerjoin(Consulta.animal)
        .options(
            joinedload(Consulta.animal).joinedload(Animal.owner),
            joinedload(Consulta.veterinario),
            joinedload(Consulta.clinica),
        )
        .filter(
            Consulta.status == 'finalizada',
            Consulta.clinica_id == clinica_id,
        )
        .order_by(Consulta.finalizada_em, Consulta.created_at)
    )
    consulta_query = _apply_calendar_datetime_window(
        consulta_query,
        func.coalesce(Consulta.finalizada_em, Consulta.created_at),
        calendar_window,
    )
    consultas = consulta_query.all()
    if allowed_veterinarian_ids is not None:
        allowed_user_ids = {
            user_id
            for (user_id,) in (
                db.session.query(Veterinario.user_id)
                .filter(Veterinario.id.in_(allowed_veterinarian_ids))
                .all()
            )
            if user_id is not None
        }
        consultas = [
            consulta
            for consulta in consultas
            if getattr(consulta, 'created_by', None) in allowed_user_ids
        ]
    for consulta in unique_items_by_id(consultas):
        event = consulta_to_event(consulta)
        if event:
            events.append(event)

    return jsonify(events)


@bp.route("/api/vet_appointments/<int:veterinario_id>", methods=["GET"])
@login_required
def api_vet_appointments(veterinario_id):
    """Return appointments for a veterinarian as calendar events."""
    veterinario = Veterinario.query.get_or_404(veterinario_id)
    calendar_window = _calendar_window_from_request()

    calendar_access_scope = get_calendar_access_scope(current_user)
    vet_clinic_ids = set()
    primary_clinic_id = getattr(veterinario, 'clinica_id', None)
    if primary_clinic_id:
        vet_clinic_ids.add(primary_clinic_id)
    for clinic in getattr(veterinario, 'clinicas', []) or []:
        clinic_id_value = getattr(clinic, 'id', None)
        if clinic_id_value:
            vet_clinic_ids.add(clinic_id_value)

    requested_clinic_ids = []
    for value in request.args.getlist('clinica_id'):
        try:
            clinic_id_value = int(value)
        except (TypeError, ValueError):
            continue
        if clinic_id_value not in requested_clinic_ids:
            requested_clinic_ids.append(clinic_id_value)

    query = Appointment.query.filter_by(veterinario_id=veterinario_id)
    target_clinic_ids = []

    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if current_user.role == 'admin':
        if requested_clinic_ids:
            filtered_requested = calendar_access_scope.filter_clinic_ids(requested_clinic_ids)
            if filtered_requested:
                query = query.filter(Appointment.clinica_id.in_(filtered_requested))
                target_clinic_ids = filtered_requested
            else:
                query = query.filter(false())
                target_clinic_ids = []
    elif is_vet:
        current_vet = getattr(current_user, 'veterinario', None)
        if not current_vet:
            abort(403)
        if current_vet.id != veterinario_id:
            if not calendar_access_scope.allows_veterinarian(veterinario):
                abort(403)
            candidate_clinic_ids = requested_clinic_ids or list(vet_clinic_ids)
            if requested_clinic_ids and vet_clinic_ids:
                candidate_clinic_ids = [
                    clinic_id
                    for clinic_id in requested_clinic_ids
                    if clinic_id in vet_clinic_ids
                ]
            filtered_clinic_ids = calendar_access_scope.filter_clinic_ids(
                candidate_clinic_ids
            )
            if filtered_clinic_ids:
                query = query.filter(Appointment.clinica_id.in_(filtered_clinic_ids))
                target_clinic_ids = filtered_clinic_ids
            elif candidate_clinic_ids:
                query = query.filter(false())
                target_clinic_ids = []
            elif requested_clinic_ids:
                query = query.filter(false())
                target_clinic_ids = []
    elif is_collaborator:
        collaborator_clinic_id = getattr(current_user, 'clinica_id', None)
        ensure_clinic_access(collaborator_clinic_id)
        if not collaborator_clinic_id:
            abort(404)
        if vet_clinic_ids and collaborator_clinic_id not in vet_clinic_ids:
            abort(404)
        authorized_clinics = calendar_access_scope.filter_clinic_ids(
            [collaborator_clinic_id]
        )
        if authorized_clinics:
            query = query.filter(Appointment.clinica_id.in_(authorized_clinics))
            target_clinic_ids = authorized_clinics
        else:
            query = query.filter(false())
            target_clinic_ids = []
    else:
        abort(403)

    query = _apply_calendar_datetime_window(query, Appointment.scheduled_at, calendar_window)
    appointments = query.order_by(Appointment.scheduled_at).all()
    events = appointments_to_events(appointments)

    consulta_filters = [
        Consulta.status == 'finalizada',
        Consulta.created_by == getattr(veterinario, 'user_id', None),
    ]
    if target_clinic_ids:
        consulta_filters.append(Consulta.clinica_id.in_(target_clinic_ids))
    elif requested_clinic_ids:
        consulta_filters.append(false())
    consulta_query = (
        Consulta.query
        .outerjoin(Consulta.animal)
        .options(
            joinedload(Consulta.animal).joinedload(Animal.owner),
            joinedload(Consulta.veterinario),
            joinedload(Consulta.clinica),
        )
        .filter(*consulta_filters)
        .order_by(Consulta.finalizada_em, Consulta.created_at)
    )
    consulta_query = _apply_calendar_datetime_window(
        consulta_query,
        func.coalesce(Consulta.finalizada_em, Consulta.created_at),
        calendar_window,
    )
    consultas = consulta_query.all()
    for consulta in unique_items_by_id(consultas):
        event = consulta_to_event(consulta)
        if event:
            events.append(event)

    exam_filters = [
        ExamAppointment.specialist_id == veterinario_id,
        ExamAppointment.status.in_(['pending', 'confirmed']),
    ]

    if target_clinic_ids:
        animal_clinic_filter = Animal.clinica_id.in_(target_clinic_ids)
        specialist_clinic_filter = ExamAppointment.specialist.has(
            Veterinario.clinica_id.in_(target_clinic_ids)
        )
        exam_filters.append(
            or_(
                animal_clinic_filter,
                and_(Animal.clinica_id.is_(None), specialist_clinic_filter),
            )
        )

    exam_query = ExamAppointment.query.outerjoin(ExamAppointment.animal)
    exam_query = _apply_calendar_datetime_window(
        exam_query,
        ExamAppointment.scheduled_at,
        calendar_window,
    )
    exam_appointments = (
        exam_query.filter(*exam_filters)
        .order_by(ExamAppointment.scheduled_at)
        .all()
    )

    for exam in unique_items_by_id(exam_appointments):
        event = exam_to_event(exam)
        if event:
            events.append(event)

    vaccine_filters = [
        Vacina.aplicada_em.isnot(None),
        Vacina.aplicada_em >= date.today(),
    ]

    vet_user_id = getattr(veterinario, 'user_id', None)
    if vet_user_id:
        vaccine_filters.append(Vacina.aplicada_por == vet_user_id)

    if target_clinic_ids:
        vaccine_filters.append(Animal.clinica_id.in_(target_clinic_ids))

    vaccine_query = Vacina.query.outerjoin(Vacina.animal)
    vaccine_query = _apply_calendar_date_window(
        vaccine_query,
        Vacina.aplicada_em,
        calendar_window,
    )
    vaccine_appointments = (
        vaccine_query.filter(*vaccine_filters)
        .order_by(Vacina.aplicada_em)
        .all()
    )

    for vaccine in unique_items_by_id(vaccine_appointments):
        event = vaccine_to_event(vaccine)
        if event:
            events.append(event)

    return jsonify(events)


@bp.route("/api/specialists", methods=["GET"])
def api_specialists():
    from models import Veterinario, Specialty
    specialty_id = request.args.get('specialty_id', type=int)
    query = Veterinario.query
    if specialty_id:
        query = query.join(Veterinario.specialties).filter(Specialty.id == specialty_id)
    vets = query.all()
    return jsonify([
        {
            'id': v.id,
            'nome': v.user.name,
            'especialidades': [s.nome for s in v.specialties],
        }
        for v in vets
    ])


@bp.route("/api/specialties", methods=["GET"])
def api_specialties():
    from models import Specialty
    specs = Specialty.query.order_by(Specialty.nome).all()
    return jsonify([{ 'id': s.id, 'nome': s.nome } for s in specs])


@bp.route("/api/specialist/<int:veterinario_id>/available_times", methods=["GET"])
def api_specialist_available_times(veterinario_id):
    date_str = request.args.get('date')
    if not date_str:
        return jsonify([])
    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    kind = request.args.get('kind', 'consulta')
    include_booked = request.args.get('include_booked', '').lower() in ('1', 'true', 'yes', 'on')
    times = get_available_times(
        veterinario_id,
        date_obj,
        kind=kind,
        include_booked=include_booked,
    )
    return jsonify(times)


@bp.route("/api/specialist/<int:veterinario_id>/weekly_schedule", methods=["GET"])
def api_specialist_weekly_schedule(veterinario_id):
    start_str = request.args.get('start')
    days = int(request.args.get('days', 7))
    start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today()
    data = get_weekly_schedule(veterinario_id, start_date, days)
    return jsonify(data)

