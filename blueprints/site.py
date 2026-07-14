"""Views do domínio site_routes (migrado do app.py)."""
from flask import Blueprint
import os, requests
from datetime import date, datetime, timedelta
from extensions import db
from flask import abort, current_app, flash, jsonify, make_response, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from forms import AppointmentRequestForm, AppointmentRequestResponseForm, ProfessionalServiceForm, VetProfileForm, VeterinarianMembershipCancelTrialForm, VeterinarianMembershipCheckoutForm, VeterinarianMembershipRequestNewTrialForm
from helpers import ensure_veterinarian_membership, has_veterinarian_profile
from models import (
    Animal,
    Appointment,
    Clinica,
    Consulta,
    DeliveryRequest,
    ExameModelo,
    Message,
    Order,
    Prescricao,
    ProfessionalService,
    User,
    Vacina,
    VacinaModelo,
    Veterinario,
)
from services.oauth_provider import _oauth_issuer
from services.product_analytics import track_event
from sqlalchemy.orm import joinedload, selectinload
from time_utils import normalize_to_utc, now_in_brazil, utcnow

# Helpers ainda hospedados no app.py (realocação em fases futuras).
from app import (  # noqa: E402
    EASTER_EGG_STATIC_DIR,
    PaymentPreferenceError,
    SERVICE_RECOMMENDATION_CATALOG,
    _apply_professional_service_form,
    _appointment_request_within_vet_schedule,
    _build_service_recommendation,
    _current_professional_service_audience,
    _ensure_professional_services_table,
    _format_reais,
    _get_veterinarian_membership_price,
    _is_bh_consulta_extra_public_profile,
    _is_public_veterinarian,
    _is_robson_santos_public_profile,
    _is_ultrasound_vet,
    _normalize_public_text,
    _populate_professional_service_form,
    _professional_service_query,
    _public_veterinarians_query,
    _render_vet_public_profile,
    _service_lowest_public_price,
    _service_public_price_options,
    _set_vet_coverage_cities,
    _vacinas_parceiro_serializer,
    _vacserv_refund_payment,
    _vet_all_public_cities,
    _vet_matches_public_city,
    _vet_public_service_notes,
    _web_whatsapp_url,
    avisar_admin_nova_solicitacao,
    get_user_or_404,
    public_price_from_professional_price,
    registrar_feedback_solicitacao,
)

bp = Blueprint("site_routes", __name__)


def get_blueprint():
    return bp


def _criar_preferencia_pagamento(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._criar_preferencia_pagamento.
    import app as app_module
    return app_module._criar_preferencia_pagamento(*args, **kwargs)


def _is_admin(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._is_admin.
    import app as app_module
    return app_module._is_admin(*args, **kwargs)


def mp_sdk(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.mp_sdk.
    import app as app_module
    return app_module.mp_sdk(*args, **kwargs)


def reverse_geocode_city(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.reverse_geocode_city.
    import app as app_module
    return app_module.reverse_geocode_city(*args, **kwargs)



@bp.route("/surpresa")
def secret_game():
    if not EASTER_EGG_STATIC_DIR.exists():
        abort(404)
    return send_from_directory(str(EASTER_EGG_STATIC_DIR), "index.html")


@bp.route("/surpresa/partituras-list")
def secret_game_partituras():
    """Lista as partituras (MusicXML) disponíveis para o Estúdio de Prática."""
    import re

    folder = EASTER_EGG_STATIC_DIR / "partituras"
    items = []
    if folder.exists():
        files = sorted(
            list(folder.glob("*.musicxml"))
            + list(folder.glob("*.xml"))
            + list(folder.glob("*.mxl"))
        )
        for f in files:
            label = f.stem.replace("_", " ").title()
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"<work-title>(.*?)</work-title>", txt)
                if m and m.group(1).strip():
                    label = m.group(1).strip()
            except Exception:
                pass
            items.append({"file": f.name, "label": label})
    return jsonify(items)


@bp.route("/surpresa/<path:filename>")
def secret_game_static(filename: str):
    return send_from_directory(str(EASTER_EGG_STATIC_DIR), filename)


@bp.route('/veterinario/assinatura')
@login_required
def veterinarian_membership():
    role = getattr(current_user, 'role', None)
    role_lower = role.lower() if isinstance(role, str) else ''
    is_admin = bool(current_user.is_authenticated and role_lower == 'admin')
    has_profile = has_veterinarian_profile(current_user)

    if not (is_admin or has_profile):
        abort(403)

    membership = None
    if has_profile:
        membership = ensure_veterinarian_membership(current_user.veterinario)

    status = request.args.get('status')

    checkout_form = VeterinarianMembershipCheckoutForm()
    price = _get_veterinarian_membership_price()
    trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)

    return render_template(
        'veterinarios/membership.html',
        membership=membership,
        checkout_form=checkout_form,
        price=price,
        trial_days=trial_days,
        status=status,
    )


@bp.route('/veterinario/assinatura/checkout', methods=['POST'])
@login_required
def veterinarian_membership_checkout():
    role = getattr(current_user, 'role', None)
    role_lower = role.lower() if isinstance(role, str) else ''
    is_admin = bool(current_user.is_authenticated and role_lower == 'admin')
    has_profile = has_veterinarian_profile(current_user)

    if not (is_admin or has_profile):
        abort(403)

    form = VeterinarianMembershipCheckoutForm()
    if not form.validate_on_submit():
        flash('Não foi possível iniciar a assinatura. Tente novamente.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    membership = None
    if has_profile:
        membership = ensure_veterinarian_membership(current_user.veterinario)
    trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
    if membership:
        membership.ensure_trial_dates(trial_days)

    price = _get_veterinarian_membership_price()

    if membership and membership.id is None:
        db.session.flush()

    reason_suffix = current_user.name.strip() if (current_user.name or '').strip() else current_user.email
    reason = f'Assinatura Profissional PetOrlândia - {reason_suffix}'

    preapproval_data = {
        'reason': reason,
        'back_url': url_for('veterinarian_membership', _external=True),
        'payer_email': current_user.email,
        'auto_recurring': {
            'frequency': 1,
            'frequency_type': 'months',
            'transaction_amount': float(price),
            'currency_id': 'BRL',
        },
    }

    if membership and membership.id:
        preapproval_data['external_reference'] = f'vet-membership-{membership.id}'

    try:
        resp = mp_sdk().preapproval().create(preapproval_data)
    except Exception:  # noqa: BLE001
        current_app.logger.exception('Erro de conexão com Mercado Pago para assinatura de veterinário')
        db.session.rollback()
        flash('Não foi possível iniciar o pagamento. Tente novamente em instantes.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    if resp.get('status') not in {200, 201}:
        current_app.logger.error('MP error (HTTP %s): %s', resp.get('status'), resp)
        db.session.rollback()
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    init_point = (
        resp.get('response', {}).get('init_point')
        or resp.get('response', {}).get('sandbox_init_point')
    )

    if not init_point:
        flash('Erro ao iniciar pagamento.', 'danger')
        return redirect(url_for('veterinarian_membership'))

    db.session.commit()

    return redirect(init_point)


@bp.route('/veterinario/assinatura/<int:membership_id>/cancelar_avaliacao', methods=['POST'])
@login_required
def veterinarian_cancel_trial(membership_id):
    from models import VeterinarianMembership

    membership = VeterinarianMembership.query.get_or_404(membership_id)
    form = VeterinarianMembershipCancelTrialForm()

    if not form.validate_on_submit():
        flash('Não foi possível cancelar a avaliação gratuita. Tente novamente.', 'danger')
        return redirect(url_for('conversa_admin'))

    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'
    owns_membership = (
        has_veterinarian_profile(current_user)
        and membership.veterinario_id == current_user.veterinario.id
    )

    if not (is_admin or owns_membership):
        abort(403)

    if not membership.is_trial_active():
        flash('O período de avaliação gratuita já havia sido encerrado.', 'info')
    else:
        membership.trial_ends_at = utcnow() - timedelta(seconds=1)
        db.session.add(membership)
        db.session.commit()
        flash('Período de avaliação gratuita cancelado com sucesso.', 'success')

    if is_admin and membership.veterinario and membership.veterinario.user:
        return redirect(url_for('conversa_admin', user_id=membership.veterinario.user.id))

    return redirect(url_for('conversa_admin'))


@bp.route('/veterinario/assinatura/<int:membership_id>/nova_avaliacao', methods=['POST'])
@login_required
def veterinarian_request_new_trial(membership_id):
    from models import VeterinarianMembership

    membership = VeterinarianMembership.query.get_or_404(membership_id)
    form = VeterinarianMembershipRequestNewTrialForm()

    if not form.validate_on_submit():
        flash('Não foi possível iniciar uma nova avaliação gratuita. Tente novamente.', 'danger')
        return redirect(url_for('conversa_admin'))

    is_admin = current_user.is_authenticated and (current_user.role or '').lower() == 'admin'
    owns_membership = (
        has_veterinarian_profile(current_user)
        and membership.veterinario_id == current_user.veterinario.id
    )

    if not (is_admin or owns_membership):
        abort(403)

    if not is_admin:
        admin_user = User.query.filter_by(role='admin').first()
        if not admin_user:
            flash('Não foi possível localizar um administrador. Tente novamente mais tarde.', 'danger')
        else:
            content = (
                'Olá! Gostaria de solicitar a reativação da minha assinatura de veterinário '
                f'(assinatura #{membership.id}).'
            )
            message = Message(
                sender_id=current_user.id,
                receiver_id=admin_user.id,
                content=content,
            )
            db.session.add(message)
            db.session.commit()
            flash('Seu pedido foi enviado ao administrador. Aguarde a confirmação.', 'success')
        return redirect(url_for('conversa_admin'))

    if membership.is_trial_active():
        flash('A avaliação gratuita atual ainda está ativa.', 'info')
    elif membership.has_valid_payment():
        flash('Não é possível iniciar uma nova avaliação gratuita com uma assinatura ativa.', 'warning')
    else:
        trial_days = current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30)
        membership.restart_trial(trial_days)
        db.session.add(membership)
        db.session.commit()
        flash('Novo período de avaliação gratuita iniciado com sucesso.', 'success')

    if is_admin and membership.veterinario and membership.veterinario.user:
        return redirect(url_for('conversa_admin', user_id=membership.veterinario.user.id))

    return redirect(url_for('conversa_admin'))


@bp.route('/painel')
@login_required
def painel_dashboard():
    if not _is_admin():
        abort(403)
    # O dashboard canônico do admin é o index do Flask-Admin.
    return redirect(url_for('painel_admin.index'))


@bp.route('/')
def index():
    if not current_user.is_authenticated:
        return render_template('index.html')

    meus_pets = (
        Animal.query
        .filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .filter(Animal.is_alive.isnot(False))
        .order_by(Animal.date_added.desc())
        .all()
    )

    doses_atrasadas = {}
    proximas_vacinas = {}
    proximos_agendamentos = {}
    pet_ids = [pet.id for pet in meus_pets]
    if pet_ids:
        hoje = date.today()
        vacinas_pendentes = (
            Vacina.query
            .filter(Vacina.animal_id.in_(pet_ids))
            .filter(Vacina.aplicada.is_(False))
            .filter(Vacina.aplicada_em.isnot(None))
            .order_by(Vacina.aplicada_em)
            .all()
        )
        for vacina in vacinas_pendentes:
            if vacina.aplicada_em < hoje:
                doses_atrasadas.setdefault(vacina.animal_id, []).append(vacina)
            elif vacina.animal_id not in proximas_vacinas:
                proximas_vacinas[vacina.animal_id] = vacina

        agendamentos = (
            Appointment.query
            .filter(Appointment.animal_id.in_(pet_ids))
            .filter(Appointment.scheduled_at >= utcnow())
            .filter(Appointment.status.in_(["scheduled", "accepted"]))
            .order_by(Appointment.scheduled_at)
            .all()
        )
        for agendamento in agendamentos:
            if agendamento.animal_id not in proximos_agendamentos:
                proximos_agendamentos[agendamento.animal_id] = agendamento

    return render_template(
        'index.html',
        meus_pets=meus_pets,
        doses_atrasadas=doses_atrasadas,
        proximas_vacinas=proximas_vacinas,
        proximos_agendamentos=proximos_agendamentos,
    )


@bp.route('/privacy')
def privacy():
    return render_template('privacy.html')


@bp.route('/support')
def support():
    return render_template(
        'support.html',
        support_email=current_app.config.get('SUPPORT_EMAIL'),
        support_phone=current_app.config.get('SUPPORT_PHONE'),
    )


@bp.route('/integracoes/pacs')
def pacs_onboarding():
    """Passo a passo público de integração do ultrassom (Orthanc/DICOM)."""
    issuer = _oauth_issuer()
    return render_template(
        'pacs_onboarding.html',
        webhook_url=f'{issuer}/api/integrations/orthanc/webhook',
    )


@bp.route('/chatgpt')
def chatgpt_onboarding():
    issuer = _oauth_issuer()
    return render_template(
        'chatgpt_onboarding.html',
        mcp_url=f'{issuer}/mcp/v2',
        auth_url=f'{issuer}/oauth/authorize',
        token_url=f'{issuer}/oauth/token',
    )


@bp.route('/terms')
def terms():
    return render_template('terms.html')


@bp.route('/.well-known/openai-apps-challenge')
def openai_apps_challenge():
    token = (current_app.config.get('OPENAI_APPS_CHALLENGE_TOKEN') or os.environ.get('OPENAI_APPS_CHALLENGE_TOKEN') or '').strip()
    if not token:
        abort(404)
    response = make_response(token)
    response.mimetype = 'text/plain'
    return response


@bp.route('/robots.txt')
def robots_txt():
    """Expose crawler guidance for the public marketing and catalog pages."""
    sitemap_url = url_for('site_routes.sitemap_xml', _external=True)
    response = make_response(
        "User-agent: *\n"
        "Disallow: /login\n"
        "Disallow: /register\n"
        "Disallow: /painel\n"
        "Disallow: /admin\n"
        f"Sitemap: {sitemap_url}\n"
    )
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response


@bp.route('/sitemap.xml')
def sitemap_xml():
    """Small explicit sitemap for stable, public acquisition pages."""
    base = _oauth_issuer()
    paths = ('/', '/loja', '/servicos', '/privacy', '/terms', '/support', '/chatgpt')
    body = ''.join(f'<url><loc>{base}{path}</loc></url>' for path in paths)
    response = make_response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'{body}</urlset>'
    )
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return response


@bp.route('/service-worker.js')
def service_worker():
    return send_from_directory(current_app.static_folder, 'service-worker.js')


@bp.route('/veterinario/servicos', methods=['GET', 'POST'])
@login_required
def professional_services_manage():
    if not has_veterinarian_profile(current_user):
        flash('Complete seu cadastro de veterinário para gerenciar serviços.', 'warning')
        return redirect(url_for('mensagens'))

    _ensure_professional_services_table()
    vet = current_user.veterinario
    editing_id = request.args.get('editar', type=int)
    editing_service = None
    if editing_id:
        editing_service = ProfessionalService.query.filter_by(
            id=editing_id,
            veterinario_id=vet.id,
        ).first_or_404()

    if request.method == 'POST' and request.form.get('action') == 'delete':
        service_id = request.form.get('service_id', type=int)
        service = ProfessionalService.query.filter_by(
            id=service_id,
            veterinario_id=vet.id,
        ).first_or_404()
        db.session.delete(service)
        db.session.commit()
        flash('Serviço removido.', 'success')
        return redirect(url_for('professional_services_manage'))

    form = ProfessionalServiceForm()
    if request.method == 'POST' and form.validate_on_submit():
        service_id = request.form.get('service_id', type=int)
        if service_id:
            service = ProfessionalService.query.filter_by(
                id=service_id,
                veterinario_id=vet.id,
            ).first_or_404()
        else:
            service = ProfessionalService(veterinario_id=vet.id)
            db.session.add(service)
        _apply_professional_service_form(service, form)
        db.session.commit()
        flash('Serviço salvo e disponibilidade pública atualizada.', 'success')
        return redirect(url_for('professional_services_manage'))

    if request.method == 'GET' and editing_service:
        _populate_professional_service_form(form, editing_service)

    services = (
        ProfessionalService.query
        .filter_by(veterinario_id=vet.id)
        .order_by(ProfessionalService.active.desc(), ProfessionalService.service_type, ProfessionalService.title)
        .all()
    )
    return render_template(
        'veterinarios/professional_services.html',
        form=form,
        editing_service=editing_service,
        services=services,
        public_price_from_professional_price=public_price_from_professional_price,
        format_reais=_format_reais,
    )


@bp.route('/veterinario/<int:veterinario_id>/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_agendamento(veterinario_id):
    """Tutor cria uma solicitação de agendamento (sem ver a agenda do profissional)."""
    from models import Veterinario, Animal, AppointmentRequest, Message

    veterinario = Veterinario.query.get_or_404(veterinario_id)
    if not _is_public_veterinarian(veterinario):
        abort(404)
    if request.method == 'GET':
        return _render_vet_public_profile(veterinario)

    animals = (
        Animal.query
        .filter(Animal.user_id == current_user.id, Animal.removido_em.is_(None))
        .order_by(Animal.name)
        .all()
    )
    form = AppointmentRequestForm()
    form.animal_id.choices = [(a.id, a.name) for a in animals]

    if not animals:
        flash('Cadastre um pet antes de solicitar um agendamento.', 'warning')
        return redirect(url_for('vet_detail', veterinario_id=veterinario_id))

    if not form.validate_on_submit():
        flash('Verifique os campos da solicitação.', 'warning')
        return redirect(url_for('vet_detail', veterinario_id=veterinario_id))

    animal = next((a for a in animals if a.id == form.animal_id.data), None)
    if animal is None:
        flash('Selecione um pet válido.', 'warning')
        return redirect(url_for('vet_detail', veterinario_id=veterinario_id))

    req = AppointmentRequest(
        tutor_id=current_user.id,
        animal_id=animal.id,
        veterinario_id=veterinario.id,
        clinica_id=veterinario.clinica_id,
        kind=form.kind.data,
        mode=form.mode.data,
        preferred_date=form.preferred_date.data,
        preferred_time=form.preferred_time.data,
        notes=(form.notes.data or '').strip() or None,
        status='pending',
    )
    db.session.add(req)

    quando = req.preferred_date.strftime('%d/%m/%Y')
    if req.preferred_time:
        quando += f" às {req.preferred_time.strftime('%H:%M')}"
    db.session.add(Message(
        sender_id=current_user.id,
        receiver_id=veterinario.user_id,
        animal_id=animal.id,
        content=(
            f"Nova solicitação de {req.kind_label.lower()} ({req.mode_label.lower()}) "
            f"para {animal.name}. Preferência: {quando}."
            + (f" Obs.: {req.notes}" if req.notes else "")
        ),
    ))
    registrar_feedback_solicitacao(
        current_user,
        (
            f"Recebemos sua solicitação de {req.kind_label.lower()} para {animal.name} "
            f"(preferência: {quando}). Você será avisado assim que o profissional confirmar. "
            f"Acompanhe em Minhas Solicitações."
        ),
        kind='appointment_request',
    )
    db.session.commit()
    from services.notifications import notify_admin_action

    notify_admin_action(
        title=f'Nova solicitacao de {req.kind_label.lower()}',
        body=(
            f'Tutor: {getattr(current_user, "name", "?")} ({getattr(current_user, "email", "?")})\n'
            f'Pet: {animal.name}\n'
            f'Profissional: {veterinario.user.name if veterinario.user else veterinario.id}\n'
            f'Preferencia: {quando}\n'
            + (f'Observacoes: {req.notes}\n' if req.notes else '')
        ),
        event_type='appointment_request.created',
        entity_type='appointment_request',
        entity_id=req.id,
        priority='high',
        url=url_for('solicitacoes_recebidas', _external=True),
        idempotency_key=f'appointment-request:{req.id}',
    )
    avisar_admin_nova_solicitacao(
        f'Nova solicitação de {req.kind_label.lower()}',
        (
            f'Tutor: {getattr(current_user, "name", "?")} ({getattr(current_user, "email", "?")})\n'
            f'Pet: {animal.name}\n'
            f'Profissional: {veterinario.user.name if veterinario.user else veterinario.id}\n'
            f'Preferência: {quando}\n'
            + (f'Observações: {req.notes}\n' if req.notes else '')
        ),
    )
    flash('Solicitação enviada! O profissional vai confirmar e você será avisado.', 'success')
    return redirect(url_for('minhas_solicitacoes'))


@bp.route('/minhas-solicitacoes')
@login_required
def minhas_solicitacoes():
    """Lista as solicitações de agendamento do tutor logado, com status."""
    from models import AppointmentRequest

    solicitacoes = (
        AppointmentRequest.query
        .filter_by(tutor_id=current_user.id)
        .order_by(AppointmentRequest.created_at.desc())
        .all()
    )
    return render_template('agendamentos/minhas_solicitacoes.html', solicitacoes=solicitacoes)


@bp.route('/solicitacoes/<int:request_id>/cancelar', methods=['POST'])
@login_required
def cancelar_solicitacao(request_id):
    from models import AppointmentRequest

    req = AppointmentRequest.query.get_or_404(request_id)
    if req.tutor_id != current_user.id:
        abort(403)
    if req.status == 'pending':
        req.status = 'cancelled'
        req.responded_at = utcnow()
        db.session.commit()
        flash('Solicitação cancelada.', 'info')
    return redirect(url_for('minhas_solicitacoes'))


@bp.route('/solicitacoes-recebidas')
@login_required
def solicitacoes_recebidas():
    """Caixa de entrada do profissional: solicitações a confirmar/recusar."""
    from models import AppointmentRequest

    vet = getattr(current_user, 'veterinario', None)
    if vet is None and current_user.role != 'admin':
        abort(403)

    query = AppointmentRequest.query
    if current_user.role != 'admin':
        query = query.filter_by(veterinario_id=vet.id)
    solicitacoes = query.order_by(
        AppointmentRequest.status != 'pending',
        AppointmentRequest.created_at.desc(),
    ).all()
    response_form = AppointmentRequestResponseForm()
    return render_template(
        'agendamentos/solicitacoes_recebidas.html',
        solicitacoes=solicitacoes,
        response_form=response_form,
    )


@bp.route('/solicitacoes/<int:request_id>/responder', methods=['POST'])
@login_required
def responder_solicitacao(request_id):
    """Profissional confirma (gera Appointment) ou recusa uma solicitação."""
    from models import AppointmentRequest, Appointment, Message

    req = AppointmentRequest.query.get_or_404(request_id)
    vet = getattr(current_user, 'veterinario', None)
    is_owner_vet = vet is not None and vet.id == req.veterinario_id
    if not (is_owner_vet or current_user.role == 'admin'):
        abort(403)
    if req.status != 'pending':
        flash('Esta solicitação já foi respondida.', 'info')
        return redirect(url_for('solicitacoes_recebidas'))

    form = AppointmentRequestResponseForm()
    if not form.validate_on_submit():
        flash('Verifique os campos da resposta.', 'warning')
        return redirect(url_for('solicitacoes_recebidas'))

    action = request.form.get('action', 'confirm')
    note = (form.response_note.data or '').strip() or None

    if action == 'decline':
        req.status = 'declined'
        req.response_note = note
        req.responded_at = utcnow()
        db.session.add(Message(
            sender_id=current_user.id,
            receiver_id=req.tutor_id,
            animal_id=req.animal_id,
            content=(
                f"Sua solicitação de {req.kind_label.lower()} para {req.animal.name} "
                f"não pôde ser atendida." + (f" {note}" if note else "")
            ),
        ))
        registrar_feedback_solicitacao(
            req.tutor,
            (
                f"Sua solicitação de {req.kind_label.lower()} para {req.animal.name} "
                f"não pôde ser atendida." + (f" {note}" if note else "")
            ),
            kind='appointment_request',
        )
        db.session.commit()
        flash('Solicitação recusada e tutor avisado.', 'info')
        return redirect(url_for('solicitacoes_recebidas'))

    # Confirmação: cria o Appointment real no horário definido pelo profissional.
    confirm_date = form.date.data or req.preferred_date
    confirm_time = form.time.data or req.preferred_time
    if not confirm_time:
        flash('Defina um horário para confirmar o agendamento.', 'warning')
        return redirect(url_for('solicitacoes_recebidas'))

    if not _appointment_request_within_vet_schedule(req.veterinario_id, confirm_date, confirm_time):
        flash('Escolha um horário dentro da carga horária cadastrada do veterinário.', 'warning')
        return redirect(url_for('solicitacoes_recebidas'))

    scheduled_local = datetime.combine(confirm_date, confirm_time)
    scheduled_at = normalize_to_utc(scheduled_local)

    appt = Appointment(
        animal_id=req.animal_id,
        tutor_id=req.tutor_id,
        veterinario_id=req.veterinario_id,
        clinica_id=req.clinica_id,
        scheduled_at=scheduled_at,
        status='scheduled',
        kind=req.kind,
        notes=req.notes,
        created_by=current_user.id,
    )
    db.session.add(appt)
    db.session.flush()

    req.status = 'confirmed'
    req.response_note = note
    req.appointment_id = appt.id
    req.responded_at = utcnow()
    db.session.add(Message(
        sender_id=current_user.id,
        receiver_id=req.tutor_id,
        animal_id=req.animal_id,
        content=(
            f"Seu {req.kind_label.lower()} para {req.animal.name} foi confirmado para "
            f"{scheduled_local.strftime('%d/%m/%Y %H:%M')}." + (f" {note}" if note else "")
        ),
    ))
    registrar_feedback_solicitacao(
        req.tutor,
        (
            f"Seu {req.kind_label.lower()} para {req.animal.name} foi confirmado para "
            f"{scheduled_local.strftime('%d/%m/%Y %H:%M')}." + (f" {note}" if note else "")
        ),
        kind='appointment_request',
    )
    db.session.commit()
    flash('Agendamento confirmado e tutor avisado.', 'success')
    return redirect(url_for('solicitacoes_recebidas'))


@bp.route('/veterinario/<int:veterinario_id>/profile', methods=['POST'])
@login_required
def update_vet_profile(veterinario_id):
    from models import Specialty
    vet = Veterinario.query.get_or_404(veterinario_id)
    if vet.user_id != current_user.id and not _is_admin():
        abort(403)
    form = VetProfileForm(prefix=f"vetprofile_{veterinario_id}")
    form.specialties.choices = [(s.id, s.nome) for s in Specialty.query.order_by(Specialty.nome).all()]
    next_url = request.form.get('next') or url_for('index')
    if form.validate_on_submit():
        vet.user.name = form.name.data.strip()
        if form.phone.data is not None:
            vet.user.phone = form.phone.data.strip() or None
        vet.crmv = form.crmv.data.strip()
        vet.crmv_estado = form.crmv_estado.data or None
        selected_ids = form.specialties.data or []
        vet.specialties = Specialty.query.filter(Specialty.id.in_(selected_ids)).all()
        _set_vet_coverage_cities(vet, form.cidades_atendidas.data)
        db.session.commit()
        flash('Perfil atualizado com sucesso.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')
    return redirect(next_url)


@bp.route('/admin/repasses-frete')
@login_required
def admin_repasses_frete():
    """Painel semanal de repasse de frete aos entregadores.

    Frete só é liberado quando o tutor confirma o recebimento do pedido;
    o pagamento é feito em lote (ciclo semanal), por entregador.
    """
    if not _is_admin():
        abort(403)
    from services.repasses import resumo_repasses

    entregas = (
        DeliveryRequest.query
        .options(
            joinedload(DeliveryRequest.order),
            joinedload(DeliveryRequest.worker),
            joinedload(DeliveryRequest.casa_de_racao),
            joinedload(DeliveryRequest.clinica),
        )
        .filter(
            DeliveryRequest.status == 'concluida',
            DeliveryRequest.tipo_entrega != 'propria',
        )
        .order_by(DeliveryRequest.completed_at.desc())
        .all()
    )
    return render_template('admin/repasses_frete.html', grupos=resumo_repasses(entregas))


@bp.route('/admin/repasses-frete/pagar/<int:worker_id>', methods=['POST'])
@login_required
def admin_pagar_repasses_frete(worker_id):
    """Marca como pagos todos os fretes liberados (recebimento confirmado) do entregador."""
    if not _is_admin():
        abort(403)
    from services.repasses import congelar_frete

    entregas = (
        DeliveryRequest.query
        .join(Order, DeliveryRequest.order_id == Order.id)
        .filter(
            DeliveryRequest.worker_id == worker_id,
            DeliveryRequest.status == 'concluida',
            DeliveryRequest.tipo_entrega != 'propria',
            DeliveryRequest.frete_pago_em.is_(None),
            Order.received_at.isnot(None),
        )
        .all()
    )
    if not entregas:
        flash('Nenhum frete liberado para este entregador.', 'info')
        return redirect(url_for('admin_repasses_frete'))

    agora = now_in_brazil()
    for entrega in entregas:
        congelar_frete(entrega)
        entrega.frete_pago_em = agora
        entrega.frete_pago_por_id = current_user.id
    db.session.commit()
    flash(f'{len(entregas)} frete(s) marcados como pagos.', 'success')
    return redirect(url_for('admin_repasses_frete'))


@bp.route('/servicos')
def servicos():
    """Central de Serviços: agendamentos e solicitações em um só lugar.

    Separa os serviços (que têm fluxo de *agendamento*) da Loja (que é só
    compra). Reúne o que antes ficava solto na home — vacina PMO e banho &
    tosa — junto de consultas, exames e pet sitter.
    """
    track_event('services_viewed', city=request.args.get('cidade'))
    from services.vaccine_service_paid import list_cidades as list_vaccine_service_cities
    from admin import _is_admin

    audience = _current_professional_service_audience()
    vets = _public_veterinarians_query().all()
    professional_services_all = _professional_service_query(active_only=True)
    vet_cities = {
        city
        for vet in vets
        for city in _vet_all_public_cities(vet)
    }
    service_cities = {
        city
        for service in professional_services_all
        for city in _vet_all_public_cities(service.veterinario)
    }
    if any(_is_robson_santos_public_profile(vet) for vet in vets):
        vet_cities.update({'Belo Horizonte', 'Contagem'})
    if any(_is_bh_consulta_extra_public_profile(vet) for vet in vets):
        vet_cities.add('Belo Horizonte')
    vaccine_cities = set(list_vaccine_service_cities())
    cities_by_key = {
        _normalize_public_text(city): city
        for city in vet_cities | service_cities | vaccine_cities | {'Orlândia'}
        if city
    }
    cities = sorted(cities_by_key.values(), key=_normalize_public_text)

    requested_city = (request.args.get('cidade') or '').strip()
    user_city = None
    if getattr(current_user, 'endereco', None):
        user_city = (current_user.endereco.cidade or '').strip() or None

    if requested_city:
        selected_city = cities_by_key.get(
            _normalize_public_text(requested_city),
            requested_city,
        )
    elif user_city and _normalize_public_text(user_city) in cities_by_key:
        selected_city = cities_by_key[_normalize_public_text(user_city)]
    else:
        selected_city = cities_by_key.get('belo horizonte') or (cities[0] if cities else '')

    selected_city_key = _normalize_public_text(selected_city)
    city_services = _professional_service_query(audience=audience, city=selected_city)
    consulta_services = [service for service in city_services if service.service_type == 'consulta']
    exam_services = [
        service for service in city_services
        if service.service_type in {'ultrassom', 'exame'}
    ]
    ultrasound_services = [
        service for service in exam_services
        if service.service_type == 'ultrassom'
        or _is_ultrasound_vet(service.veterinario)
        or _is_robson_santos_public_profile(service.veterinario)
    ]
    vaccine_city_keys = {_normalize_public_text(city) for city in vaccine_cities}
    has_paid_vaccines = selected_city_key in vaccine_city_keys
    has_consultas = bool(consulta_services)
    has_exames = bool(ultrasound_services)
    consulta_names = ', '.join(
        getattr(getattr(service.veterinario, 'user', None), 'name', '') for service in consulta_services[:3]
        if getattr(getattr(service.veterinario, 'user', None), 'name', '')
    )
    exame_names = ', '.join(
        getattr(getattr(service.veterinario, 'user', None), 'name', '') for service in ultrasound_services[:3]
        if getattr(getattr(service.veterinario, 'user', None), 'name', '')
    )
    consulta_lowest_price = _format_reais(_service_lowest_public_price(consulta_services, audience))
    exame_lowest_price = _format_reais(_service_lowest_public_price(ultrasound_services, audience))
    is_orlandia = selected_city_key == _normalize_public_text('Orlândia')

    pmo_services = []
    if is_orlandia:
        pmo_services.append({
            'icon': 'fa-hand-holding-medical',
            'color': 'primary',
            'title': 'Castração (PMO)',
            'description': 'Cadastro de interesse para castração gratuita pela Prefeitura de Orlândia.',
            'badge': 'Gratuito',
            'url': url_for('castracao_pmo_solicitar'),
            'cta': 'Solicitar',
        })
        pmo_services.append({
            'icon': 'fa-syringe',
            'color': 'danger',
            'title': 'Vacina Antirrábica (PMO)',
            'description': 'Vacina antirrábica gratuita da Prefeitura de Orlândia para o seu pet.',
            'badge': 'Gratuito',
            'url': url_for('vacina_pmo_solicitar'),
            'cta': 'Solicitar',
        })

    is_bh = selected_city_key == _normalize_public_text('Belo Horizonte')
    bh_services = []
    if is_bh:
        bh_services.append({
            'icon': 'fa-hand-holding-medical',
            'color': 'primary',
            'title': 'Castração (BH)',
            'description': 'Cadastro de interesse para castração gratuita de cães e gatos pela Prefeitura de Belo Horizonte.',
            'badge': 'Gratuito',
            'url': (
                'https://acesso.pbh.gov.br/auth/realms/PBH/protocol/openid-connect/auth'
                '?client_id=SIEAWEB2'
                '&redirect_uri=https%3A%2F%2Fsieaweb2.pbh.gov.br%2FloginPrincipal'
                '&state=5c1d70d0-0daf-4643-8513-4f016f1eb1de'
                '&response_mode=fragment&response_type=code&scope=openid'
                '&nonce=90ca4408-4d52-412a-8e3b-4ae9fc291aae'
                '&code_challenge=OSofSXemOqrKAWyNRPCXiX1ou0USm8Zj5RSfFZYCXLg'
                '&code_challenge_method=S256'
            ),
            'cta': 'Solicitar',
            'external': True,
        })

    localized_services = []
    localized_services.extend([
        {
            'icon': 'fa-shield-dog',
            'color': 'success',
            'title': 'Vacinas em domicílio',
            'description': (
                f'Escolha as vacinas disponíveis em {selected_city}, informe os pets e conclua '
                'o pagamento online.'
                if has_paid_vaccines
                else f'O catálogo de vacinas em domicílio para {selected_city} está em preparação.'
            ),
            'url': url_for('servicos_vacinas', cidade=selected_city),
            'cta': 'Escolher vacina',
            'soon': not has_paid_vaccines,
        },
        {
            'icon': 'fa-stethoscope',
            'color': 'info',
            'title': 'Consultas',
            'description': (
                f'Agende consultas veterinárias em {selected_city}'
                + (f' com {consulta_names}.' if consulta_names else '.')
                + (f' A partir de {consulta_lowest_price}.' if consulta_lowest_price else '')
                if has_consultas
                else f'Agendamento de consultas veterinárias em {selected_city} em breve.'
            ),
            'url': url_for('veterinarios', cidade=selected_city),
            'cta': 'Ver profissionais',
            'soon': not has_consultas,
            'highlight': consulta_names if has_consultas else None,
        },
        {
            'icon': 'fa-microscope',
            'color': 'primary',
            'title': 'Exames',
            'description': (
                f'Solicite exames em {selected_city}'
                + (f' com {exame_names}. Ultrassonografia disponível.' if exame_names else '.')
                + (f' A partir de {exame_lowest_price}.' if exame_lowest_price else '')
                if has_exames
                else f'Solicitação de exames com profissionais de {selected_city} em breve.'
            ),
            'url': (
                url_for('servicos_ultrassom', cidade=selected_city)
                if audience == 'clinic'
                else url_for('servicos_exames', cidade=selected_city)
            ),
            'cta': 'Ver profissionais' if audience == 'clinic' else 'Escolher pet',
            'soon': not has_exames,
            'highlight': (
                'Ultrassonografia com Robson Santos'
                if any(_is_robson_santos_public_profile(service.veterinario) for service in ultrasound_services)
                else exame_names
            ),
        },
    ])

    # Ultrassom só aparece quando há ultrassonografista atendendo a cidade.
    if ultrasound_services:
        localized_services.append({
            'icon': 'fa-wave-square',
            'color': 'info',
            'title': 'Ultrassom a domicílio',
            'description': (
                f'Ultrassonografia para o seu pet em {selected_city}, na clínica ou em '
                'casa, com laudo digital.'
            ),
            'url': url_for('servicos_ultrassom', cidade=selected_city),
            'cta': 'Ver e contratar',
        })

    other_services = [
        {
            'icon': 'fa-scissors',
            'color': 'warning',
            'title': 'Banho & Tosa',
            'description': 'Planos mensais de banho e tosa nas clínicas e casas parceiras. Em breve disponível.',
            'url': url_for('grooming_planos_publicos'),
            'cta': 'Ver planos',
            'soon': True,
        },
        {
            'icon': 'fa-dog',
            'color': 'secondary',
            'title': 'Pet sitter',
            'description': 'Cuidador aprovado para o seu pet enquanto você viaja, em casa ou hospedagem.',
            'url': url_for('petsitter_routes.petsitter_home'),
            'cta': 'Conhecer',
            'soon': False,
        },
    ]

    return render_template(
        'servicos.html',
        cities=cities,
        selected_city=selected_city,
        pmo_services=pmo_services,
        bh_services=bh_services,
        localized_services=localized_services,
        other_services=other_services,
        is_admin=_is_admin(),
        # Sem cidade no pedido nem no cadastro → oferecer geolocalização automática.
        auto_locate=(not requested_city and not user_city),
    )


@bp.route('/servicos/recomendar', methods=['POST'])
@login_required
def servicos_recomendar():
    """Admin: gera mensagem de WhatsApp recomendando serviços a um tutor."""
    from admin import _is_admin
    if not _is_admin():
        abort(403)

    data = request.get_json(silent=True) or request.form
    try:
        tutor_id = int(data.get('tutor_id'))
    except (TypeError, ValueError):
        tutor_id = None
    if not tutor_id:
        return jsonify(success=False, message='Selecione um tutor.'), 400

    tutor = get_user_or_404(tutor_id)

    if hasattr(data, 'getlist'):
        raw_services = data.getlist('services') or data.getlist('services[]')
        raw_animal_ids = data.getlist('animal_ids') or data.getlist('animal_ids[]')
    else:
        raw_services = data.get('services') or []
        raw_animal_ids = data.get('animal_ids') or []
        if not isinstance(raw_services, (list, tuple)):
            raw_services = [raw_services]
        if not isinstance(raw_animal_ids, (list, tuple)):
            raw_animal_ids = [raw_animal_ids]

    services = [s for s in raw_services if s in SERVICE_RECOMMENDATION_CATALOG]
    if not services:
        return jsonify(success=False, message='Escolha ao menos um serviço.'), 400

    animal_id_set = set()
    for aid in raw_animal_ids:
        try:
            animal_id_set.add(int(aid))
        except (TypeError, ValueError):
            continue
    animais = [
        a for a in Animal.query.filter_by(user_id=tutor.id).all()
        if a.id in animal_id_set
    ]

    city = (data.get('cidade') or '').strip() or None
    free_text = data.get('texto_livre') or ''

    result = _build_service_recommendation(tutor, animais, services, city, free_text)
    return jsonify(success=True, **result)


@bp.route('/servicos/ultrassom')
@login_required
def servicos_ultrassom():
    """Contratação de ultrassonografia volante (na clínica ou a domicílio).

    Lista os profissionais públicos com especialidade de imagem, filtrados pela
    cidade, com CTA de WhatsApp (tutor e clínica) e de solicitação interna de
    exame. Pensado para tutores e donos de clínica contratarem o serviço.
    """
    audience = _current_professional_service_audience()
    services = _professional_service_query(audience=audience, service_type='ultrassom')

    cities = sorted(
        {c for service in services for c in _vet_all_public_cities(service.veterinario)},
        key=_normalize_public_text,
    )

    requested_city = (request.args.get('cidade') or '').strip()
    user_city = None
    if getattr(current_user, 'endereco', None):
        user_city = (current_user.endereco.cidade or '').strip() or None

    selected_city = ''
    if requested_city:
        selected_city = requested_city
    elif user_city and any(_vet_matches_public_city(service.veterinario, user_city, kind='exame') for service in services):
        selected_city = user_city

    if selected_city:
        providers_source = [
            service for service in services
            if _vet_matches_public_city(service.veterinario, selected_city, kind='exame')
        ]
    else:
        providers_source = services

    providers = []
    for service in providers_source:
        vet = service.veterinario
        phone = getattr(vet.user, 'phone', None)
        local = f' em {selected_city}' if selected_city else ''
        tutor_msg = (
            f'Olá {vet.user.name}, vim pela PetOrlândia e gostaria de agendar um '
            f'ultrassom para o meu pet{local}.'
        )
        clinica_msg = (
            f'Olá {vet.user.name}, sou de uma clínica e gostaria de combinar '
            f'ultrassonografias para os nossos pacientes{local}.'
        )
        providers.append({
            'vet': vet,
            'service': service,
            'cidades': _vet_all_public_cities(vet),
            'whatsapp_tutor_url': _web_whatsapp_url(phone, tutor_msg),
            'whatsapp_clinica_url': _web_whatsapp_url(phone, clinica_msg),
            'solicitar_url': url_for('solicitar_agendamento', veterinario_id=vet.id),
            'price_options': _service_public_price_options(service, audience),
        })

    return render_template(
        'servicos_ultrassom.html',
        providers=providers,
        cities=cities,
        selected_city=selected_city,
        audience=audience,
        format_reais=_format_reais,
    )


@bp.route('/api/geo/cidade')
@login_required
def api_geo_cidade():
    """Reverse geocode da localização do navegador (lat/lon) → cidade.

    Alimenta o botão 'usar minha localização' nas páginas de serviços.
    """
    cidade = reverse_geocode_city(request.args.get('lat'), request.args.get('lon'))
    if not cidade:
        return jsonify({'cidade': None}), 404
    return jsonify({'cidade': cidade})


@bp.route('/servicos/vacinas', methods=['GET', 'POST'])
@login_required
def servicos_vacinas():
    from models import VaccineServiceRequest
    from services.vaccine_service_paid import create_vaccine_request, list_active_items, list_cidades

    cidades = list_cidades()
    # Prioridade: query param > cidade do endereço do usuário > primeira cidade disponível
    cidade_param = (request.args.get('cidade') or request.form.get('cidade') or '').strip()
    explicit_city = bool(cidade_param)
    if not cidade_param and current_user.endereco and current_user.endereco.cidade:
        cidade_param = current_user.endereco.cidade.strip()
    if not cidade_param and cidades:
        cidade_param = cidades[0]
    cidade_selecionada = cidade_param if explicit_city or cidade_param in cidades else (cidades[0] if cidades else None)
    items = list_active_items(cidade=cidade_selecionada)
    animals = (
        Animal.query.filter_by(user_id=current_user.id)
        .filter(Animal.removido_em.is_(None))
        .order_by(Animal.name)
        .all()
    )

    if request.method == 'POST':
        selected_ids = {
            int(value)
            for value in request.form.getlist('item_ids')
            if value.isdigit()
        }
        selected_items = [item for item in items if item.id in selected_ids]
        selected_animal_ids = {
            int(v) for v in request.form.getlist('animal_ids') if v.isdigit()
        }
        selected_animals = [a for a in animals if a.id in selected_animal_ids]
        phone = (request.form.get('phone') or '').strip()
        street = (request.form.get('address_street') or '').strip()

        if not selected_items:
            flash('Escolha pelo menos uma vacina.', 'danger')
        elif not selected_animals:
            flash('Escolha pelo menos um pet.', 'danger')
        elif not phone:
            flash('Informe um telefone para contato.', 'danger')
        elif not street:
            flash('Informe o endereço para a aplicação.', 'danger')
        else:
            preferred_date = None
            raw_date = (request.form.get('preferred_date') or '').strip()
            if raw_date:
                try:
                    preferred_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
                except ValueError:
                    preferred_date = None
            payload = {
                'phone': phone,
                'address_street': street,
                'address_number': request.form.get('address_number'),
                'address_complement': request.form.get('address_complement'),
                'address_neighborhood': request.form.get('address_neighborhood'),
                'preferred_date': preferred_date,
                'preferred_shift': request.form.get('preferred_shift'),
                'note': request.form.get('note'),
            }
            first_payment_url = None
            try:
                for animal in selected_animals:
                    _tok = None
                    req, payment_url = create_vaccine_request(
                        user=current_user,
                        animal=animal,
                        items=selected_items,
                        payload=payload,
                        criar_preferencia=_criar_preferencia_pagamento,
                        back_url_builder=lambda tok: url_for(
                            'servicos_vacinas_pedido', token=tok, _external=True
                        ),
                    )
                    if first_payment_url is None:
                        first_payment_url = payment_url
                return redirect(first_payment_url)
            except PaymentPreferenceError as exc:
                db.session.rollback()
                flash(str(exc), 'danger')
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), 'warning')
            except Exception:
                db.session.rollback()
                current_app.logger.exception('Falha ao criar pedido de vacina paga')
                flash('Não foi possível iniciar o pedido agora. Tente novamente.', 'danger')

    meus_pedidos = (
        VaccineServiceRequest.query
        .filter_by(user_id=current_user.id)
        .order_by(VaccineServiceRequest.created_at.desc())
        .limit(20)
        .all()
    )

    prof_phone = current_user.phone or ''
    prof = {'street': '', 'number': '', 'complement': '', 'neighborhood': ''}
    if current_user.endereco:
        prof = {
            'street': current_user.endereco.rua or '',
            'number': current_user.endereco.numero or '',
            'complement': current_user.endereco.complemento or '',
            'neighborhood': current_user.endereco.bairro or '',
        }

    featured_provider = next(
        (item.provider_vet for item in items if item.provider_vet),
        None,
    )
    featured_clinic = featured_provider.clinica if featured_provider else None

    return render_template(
        'vacinas_servico/catalogo.html',
        items=items,
        animals=animals,
        meus_pedidos=meus_pedidos,
        prof_phone=prof_phone,
        prof_address=prof,
        featured_provider=featured_provider,
        featured_clinic=featured_clinic,
        cidades=cidades,
        cidade_selecionada=cidade_selecionada,
    )


@bp.route('/servicos/vacinas/cidade-por-local')
@login_required
def servicos_vacinas_cidade_por_local():
    """Reverse-geocode da localização do visitante -> cidade do catálogo.

    Recebe lat/lng (geolocalização do navegador), descobre a cidade via Nominatim e,
    se ela tiver vacinas cadastradas, devolve o nome exato usado no catálogo.
    """
    from services.vaccine_service_paid import list_cidades

    try:
        lat = float(request.args.get('lat', ''))
        lng = float(request.args.get('lng', ''))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Coordenadas inválidas.'}), 400

    def _norm(value):
        import unicodedata
        text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode()
        return text.strip().lower()

    cidade_detectada = None
    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={'lat': lat, 'lon': lng, 'format': 'json', 'addressdetails': 1, 'zoom': 10},
            headers={'User-Agent': 'PetOrlandia/1.0 (+https://petorlandia.com)'},
            timeout=6,
        )
        resp.raise_for_status()
        address = (resp.json() or {}).get('address', {})
        cidade_detectada = (
            address.get('city') or address.get('town') or address.get('municipality')
            or address.get('village') or address.get('county')
        )
    except (requests.RequestException, ValueError):
        cidade_detectada = None

    cidades = list_cidades()
    match = None
    if cidade_detectada:
        alvo = _norm(cidade_detectada)
        match = next((c for c in cidades if _norm(c) == alvo), None)
    return jsonify({
        'success': True,
        'cidade_detectada': cidade_detectada,
        'cidade': match,            # nome exato do catálogo, ou null se não atendida
        'atendida': bool(match),
        'cidades': cidades,
    })


@bp.route('/servicos/vacinas/pedido/<token>')
def servicos_vacinas_pedido(token):
    from models import VaccineServiceRequest
    from services.vaccine_service_paid import timeline_for

    req = VaccineServiceRequest.query.filter_by(public_token=token).first_or_404()
    is_owner = current_user.is_authenticated and current_user.id == req.user_id
    is_admin = current_user.is_authenticated and current_user.role == 'admin'
    return render_template(
        'vacinas_servico/pedido.html',
        req=req,
        timeline=timeline_for(req),
        is_owner=is_owner,
        is_admin=is_admin,
    )


@bp.route('/servicos/vacinas/pedido/<token>/cancelar', methods=['POST'])
@login_required
def servicos_vacinas_cancelar(token):
    from models import VaccineServiceRequest
    from services.vaccine_service_paid import cancel_request

    req = VaccineServiceRequest.query.filter_by(public_token=token).first_or_404()
    if current_user.id != req.user_id and current_user.role != 'admin':
        abort(403)
    try:
        outcome = cancel_request(
            req,
            reason=(request.form.get('reason') or '').strip(),
            actor_user_id=current_user.id,
            refund_payment=_vacserv_refund_payment,
        )
        db.session.commit()
        if outcome == 'reembolsado':
            flash('Pedido cancelado e reembolso concluído. O valor volta pelo mesmo meio de pagamento.', 'success')
        elif outcome == 'reembolso_pendente':
            flash('Pedido cancelado. O reembolso foi solicitado e será processado em breve.', 'success')
        else:
            flash('Pedido cancelado.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
    return redirect(url_for('servicos_vacinas_pedido', token=token))


@bp.route('/servicos/vacinas/pedido/<token>/reagendar', methods=['POST'])
@login_required
def servicos_vacinas_reagendar(token):
    from models import VaccineServiceRequest
    from services.vaccine_service_paid import request_reschedule

    req = VaccineServiceRequest.query.filter_by(public_token=token).first_or_404()
    if current_user.id != req.user_id and current_user.role != 'admin':
        abort(403)
    preferred_date = None
    raw_date = (request.form.get('preferred_date') or '').strip()
    if raw_date:
        try:
            preferred_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            preferred_date = None
    try:
        request_reschedule(req, preferred_date, (request.form.get('note') or '').strip(), current_user.id)
        db.session.commit()
        flash('Pedido de nova data enviado. A equipe confirmará o novo agendamento.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
    return redirect(url_for('servicos_vacinas_pedido', token=token))


@bp.route('/servicos/vacinas/admin', methods=['GET'])
@login_required
def servicos_vacinas_admin():
    if current_user.role != 'admin':
        abort(403)
    from models import VaccineServiceItem, VaccineServiceRequest, Veterinario

    pedidos = (
        VaccineServiceRequest.query
        .order_by(VaccineServiceRequest.created_at.desc())
        .limit(200)
        .all()
    )
    items = VaccineServiceItem.query.order_by(VaccineServiceItem.position, VaccineServiceItem.nome).all()
    vets = Veterinario.query.all()
    return render_template('vacinas_servico/admin.html', pedidos=pedidos, items=items, vets=vets)


@bp.route('/servicos/vacinas/admin/<int:req_id>/acao', methods=['POST'])
@login_required
def servicos_vacinas_admin_acao(req_id):
    if current_user.role != 'admin':
        abort(403)
    from models import VaccineServiceRequest, Veterinario
    from services.vaccine_service_paid import (
        assign_vet,
        cancel_request,
        complete_request,
        schedule_request,
    )

    req = VaccineServiceRequest.query.get_or_404(req_id)
    acao = request.form.get('acao') or ''
    try:
        if acao == 'atribuir':
            vet = Veterinario.query.get_or_404(request.form.get('vet_id', type=int))
            assign_vet(req, vet, current_user.id)
        elif acao == 'agendar':
            raw_date = (request.form.get('scheduled_date') or '').strip()
            scheduled = datetime.strptime(raw_date, '%Y-%m-%d').date()
            schedule_request(req, scheduled, (request.form.get('scheduled_shift') or '').strip(), current_user.id)
        elif acao == 'concluir':
            complete_request(req, current_user.id, (request.form.get('lote') or '').strip())
        elif acao == 'cancelar':
            cancel_request(
                req,
                reason=(request.form.get('reason') or '').strip(),
                actor_user_id=current_user.id,
                refund_payment=_vacserv_refund_payment,
            )
        else:
            flash('Ação inválida.', 'warning')
            return redirect(url_for('servicos_vacinas_admin'))
        db.session.commit()
        flash('Pedido atualizado.', 'success')
    except (ValueError, KeyError) as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha em ação admin vacina paga')
        flash('Não foi possível executar a ação.', 'danger')
    return redirect(url_for('servicos_vacinas_admin'))


@bp.route('/servicos/vacinas/admin/item', methods=['POST'])
@login_required
def servicos_vacinas_admin_item():
    if current_user.role != 'admin':
        abort(403)
    from decimal import Decimal as _Dec
    from models import VaccineServiceItem

    item_id = request.form.get('item_id', type=int)
    item = VaccineServiceItem.query.get(item_id) if item_id else None
    if request.form.get('acao') == 'desativar' and item:
        item.ativo = not item.ativo
        db.session.commit()
        flash(f'"{item.nome}" {"reativada" if item.ativo else "desativada"}.', 'success')
        return redirect(url_for('servicos_vacinas_admin'))

    from services.vaccine_service_paid import public_price_from_vet_price

    nome = (request.form.get('nome') or '').strip()
    # Preferimos o "preço do veterinário": o público sai com a margem aplicada.
    preco_vet_raw = (request.form.get('preco_vet') or '').replace(',', '.').strip()
    preco_raw = (request.form.get('preco') or '').replace(',', '.').strip()
    if not nome or (not preco_vet_raw and not preco_raw):
        flash('Informe o nome e o preço do veterinário.', 'warning')
        return redirect(url_for('servicos_vacinas_admin'))

    if preco_vet_raw:
        # Fluxo novo: o vet informa o que recebe; a plataforma calcula o público.
        try:
            valor_repasse = _Dec(preco_vet_raw)
        except Exception:
            flash('Preço do veterinário inválido.', 'warning')
            return redirect(url_for('servicos_vacinas_admin'))
        if valor_repasse < 0:
            flash('O preço do veterinário não pode ser negativo.', 'warning')
            return redirect(url_for('servicos_vacinas_admin'))
        preco = public_price_from_vet_price(valor_repasse)
    else:
        # Fluxo manual (retrocompatível): admin informa preço público e repasse.
        try:
            preco = _Dec(preco_raw)
        except Exception:
            flash('Preço inválido.', 'warning')
            return redirect(url_for('servicos_vacinas_admin'))
        repasse_raw = (request.form.get('valor_repasse') or '').replace(',', '.').strip()
        try:
            valor_repasse = _Dec(repasse_raw) if repasse_raw else None
        except Exception:
            flash('Valor de repasse inválido.', 'warning')
            return redirect(url_for('servicos_vacinas_admin'))
        if valor_repasse is not None and (valor_repasse < 0 or valor_repasse > preco):
            flash('O repasse deve ficar entre zero e o preço cobrado.', 'warning')
            return redirect(url_for('servicos_vacinas_admin'))

    especies = ','.join(request.form.getlist('especies')) or 'cao,gato'
    if item is None:
        item = VaccineServiceItem(nome=nome, preco=preco, especies=especies)
        db.session.add(item)
    else:
        item.nome = nome
        item.preco = preco
        item.especies = especies
    item.descricao = (request.form.get('descricao') or '').strip() or None
    item.fabricante = (request.form.get('fabricante') or '').strip() or None
    item.valor_repasse = valor_repasse
    item.doses_info = (request.form.get('doses_info') or '').strip() or None
    item.cidade = (request.form.get('cidade') or '').strip() or None
    provider_vet_id = request.form.get('provider_vet_id', type=int)
    item.provider_vet_id = provider_vet_id or None
    db.session.commit()
    flash(f'Vacina "{nome}" salva.', 'success')
    return redirect(url_for('servicos_vacinas_admin'))


@bp.route('/parceiro/vacinas/<token>', methods=['GET', 'POST'])
def parceiro_vacinas_precos(token):
    """Página tokenizada (sem login) para o veterinário definir só os preços dele."""
    from decimal import Decimal as _Dec
    from models import VaccineServiceItem
    from models.base import Veterinario
    from services.vaccine_service_paid import public_price_from_vet_price

    try:
        vet_id = _vacinas_parceiro_serializer().loads(token)
    except Exception:
        abort(404)
    vet = Veterinario.query.get_or_404(vet_id)
    items = (
        VaccineServiceItem.query
        .filter_by(provider_vet_id=vet_id)
        .order_by(VaccineServiceItem.position, VaccineServiceItem.nome)
        .all()
    )

    if request.method == 'POST':
        updated = 0
        for item in items:
            raw = (request.form.get(f'preco_vet_{item.id}') or '').replace(',', '.').strip()
            if not raw:
                continue
            try:
                vet_price = _Dec(raw)
            except Exception:
                continue
            if vet_price < 0:
                continue
            item.valor_repasse = vet_price
            item.preco = public_price_from_vet_price(vet_price)
            item.ativo = vet_price > 0
            updated += 1
        if updated:
            db.session.commit()
            flash('Preços salvos! Suas vacinas já estão no ar para os tutores da sua cidade.', 'success')
        return redirect(url_for('parceiro_vacinas_precos', token=token))

    vet_name = getattr(getattr(vet, 'user', None), 'name', None) or 'Veterinário(a)'
    return render_template(
        'vacinas_servico/parceiro_precos.html',
        vet=vet, vet_name=vet_name, items=items, token=token,
    )


@bp.route('/servicos/exames')
@login_required
def servicos_exames():
    """Escolha de pet para servicos de exames, restrita ao tutor logado."""
    animals = (
        Animal.query
        .options(
            selectinload(Animal.species),
            selectinload(Animal.breed),
        )
        .filter(Animal.user_id == current_user.id)
        .order_by(Animal.date_added.desc(), Animal.name.asc())
        .all()
    )
    selected_animal_id = request.args.get('animal_id', type=int)
    selected_animal = None
    exames = []
    especialistas = []
    # Presença do parâmetro = escolha explícita do usuário. Vazio ("Todas as
    # cidades") mostra todos os profissionais; ausente deixa auto-detectar.
    city_param_present = 'cidade' in request.args
    selected_city = (request.args.get('cidade') or '').strip() or None

    audience = _current_professional_service_audience()
    service_candidates = _professional_service_query(
        audience=audience,
        service_type=('ultrassom', 'exame'),
    )
    public_vets = []
    seen_vets = set()
    for service in service_candidates:
        if service.veterinario_id not in seen_vets:
            seen_vets.add(service.veterinario_id)
            public_vets.append(service.veterinario)
    cities_set = {c for vet in public_vets for c in _vet_all_public_cities(vet)}
    if any(_is_robson_santos_public_profile(vet) for vet in public_vets):
        cities_set.update({'Belo Horizonte', 'Contagem'})
    if any(_is_bh_consulta_extra_public_profile(vet) for vet in public_vets):
        cities_set.add('Belo Horizonte')
    cities = sorted(cities_set, key=_normalize_public_text)

    if selected_animal_id:
        selected_animal = next((animal for animal in animals if animal.id == selected_animal_id), None)
        if not selected_animal:
            abort(404)

    if selected_animal:
        exames = ExameModelo.query.order_by(ExameModelo.nome).limit(80).all()
        try:
            from services.species_ranking import resolver_species_scope_do_animal, ordenar_por_species_scope

            scope_alvo = resolver_species_scope_do_animal(selected_animal.id)
            if scope_alvo:
                exames = ordenar_por_species_scope(exames, scope_alvo)
        except Exception:
            current_app.logger.exception("Erro ao ordenar exames por especie para servicos/exames")
        if not selected_city and not city_param_present:
            if getattr(selected_animal, 'owner', None) and getattr(selected_animal.owner, 'endereco', None):
                selected_city = (selected_animal.owner.endereco.cidade or '').strip() or None
            if not selected_city and getattr(current_user, 'endereco', None):
                selected_city = (current_user.endereco.cidade or '').strip() or None

        selected_services = service_candidates
        if selected_city:
            selected_services = [
                service for service in selected_services
                if _vet_matches_public_city(service.veterinario, selected_city, kind='exame')
            ]
        especialistas = []
        seen_vets = set()
        for service in selected_services:
            vet = service.veterinario
            if vet.id in seen_vets:
                continue
            seen_vets.add(vet.id)
            especialistas.append(vet)

    return render_template(
        'servicos_exames.html',
        animals=animals,
        selected_animal=selected_animal,
        exames=exames,
        especialistas=especialistas,
        selected_city=selected_city,
        cities=cities,
        vet_service_notes=_vet_public_service_notes,
    )

