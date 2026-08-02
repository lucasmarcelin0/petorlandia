"""Administração da plataforma — views reais do domínio.

Migrado do app.py monolítico. ``_is_admin`` é resolvido em tempo de request
via módulo app (late-binding) porque dezenas de testes fazem monkeypatch de
``app._is_admin`` — mesmo contrato do antigo lazy_view.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required
from flask_mail import Message as MailMessage
from sqlalchemy import case, func

from context_processors import _invalidate_admin_action_cache
from document_utils import only_digits
from extensions import db, mail
from forms import (
    DeliveryDemotionForm,
    DeliveryPromotionForm,
    ParceiroDemotionForm,
    ParceiroPromotionForm,
    VeterinarianPromotionForm,
)
from helpers import ensure_veterinarian_membership, grant_veterinarian_role
from models import (
    AdminActionNotification,
    CasaDeRacao,
    Clinica,
    PartnerInvite,
    PropostaProtocoloClinico,
    ProductEvent,
    User,
    Veterinario,
)
from services.health_plan import build_usage_history, summarize_plan_metrics
from template_filters import normalize_email
from time_utils import now_in_brazil

bp = Blueprint("admin_routes", __name__)


def get_blueprint():
    return bp


def _is_admin():
    import app as app_module

    return app_module._is_admin()


def _partner_invite_url(token):
    return url_for('partner_invite_onboarding', token=token, _external=True)


def _partner_invite_whatsapp_url(invite, link):
    saudacao = f'Olá{", " + invite.nome.split()[0] if invite.nome else ""}!'
    texto = (
        f'{saudacao} Aqui é da PetOrlândia. '
        f'Preparamos seu acesso de {invite.tipo_label.lower()} na plataforma. '
        f'É só concluir o cadastro neste link: {link}'
    )
    numero = only_digits(invite.telefone or '')
    base = f'https://wa.me/55{numero}' if len(numero) in (10, 11) else 'https://wa.me/'
    return f'{base}?text={quote_plus(texto)}'


@bp.route("/admin/analytics-produto", methods=["GET"])
@login_required
def product_analytics_dashboard():
    if not _is_admin():
        abort(403)

    period_days = request.args.get('days', 30, type=int)
    if period_days not in {7, 30, 90}:
        period_days = 30
    since = now_in_brazil() - timedelta(days=period_days)

    event_names = (
        'landing_viewed',
        'signup_completed',
        'onboarding_viewed',
        'onboarding_progress_viewed',
        'pricing_viewed',
        'catalog_viewed',
        'add_to_cart',
        'checkout_started',
        'checkout_abandoned',
        'purchase_completed',
        'payment_failed',
        'subscription_started',
        'trial_converted',
        'service_requested',
    )
    rows = (
        db.session.query(ProductEvent.event_name, func.count(ProductEvent.id))
        .filter(ProductEvent.created_at >= since)
        .filter(ProductEvent.event_name.in_(event_names))
        .group_by(ProductEvent.event_name)
        .all()
    )
    counts = dict(rows)

    def rate(outcome, base):
        denominator = counts.get(base, 0)
        if not denominator:
            return None
        return round(counts.get(outcome, 0) * 100 / denominator, 1)

    acquisition_funnel = (
        ('Visitas à página inicial', counts.get('landing_viewed', 0), None),
        (
            'Cadastros concluídos',
            counts.get('signup_completed', 0),
            rate('signup_completed', 'landing_viewed'),
        ),
        (
            'Onboardings iniciados',
            counts.get('onboarding_viewed', 0),
            rate('onboarding_viewed', 'signup_completed'),
        ),
        (
            'Trials convertidos',
            counts.get('trial_converted', 0),
            rate('trial_converted', 'signup_completed'),
        ),
    )
    commerce_funnel = (
        ('Visitas à loja', counts.get('catalog_viewed', 0), None),
        (
            'Adições ao carrinho',
            counts.get('add_to_cart', 0),
            rate('add_to_cart', 'catalog_viewed'),
        ),
        (
            'Checkouts iniciados',
            counts.get('checkout_started', 0),
            rate('checkout_started', 'add_to_cart'),
        ),
        (
            'Compras aprovadas',
            counts.get('purchase_completed', 0),
            rate('purchase_completed', 'checkout_started'),
        ),
    )

    revenue_events = (
        ProductEvent.query
        .filter(ProductEvent.created_at >= since)
        .filter(ProductEvent.event_name.in_(('purchase_completed', 'payment_failed')))
        .all()
    )

    def amount_for(event_name):
        total = 0.0
        for event in revenue_events:
            if event.event_name != event_name:
                continue
            try:
                total += float((event.properties or {}).get('amount') or 0)
            except (TypeError, ValueError):
                continue
        return total

    revenue_summary = {
        'approved_amount': amount_for('purchase_completed'),
        'failed_amount': amount_for('payment_failed'),
        'abandoned': counts.get('checkout_abandoned', 0),
        'subscriptions_started': counts.get('subscription_started', 0),
        'services_requested': counts.get('service_requested', 0),
    }
    sources = (
        db.session.query(
            func.coalesce(ProductEvent.utm_source, 'direto'),
            func.count(func.distinct(ProductEvent.anonymous_id)),
        )
        .filter(ProductEvent.created_at >= since)
        .group_by(func.coalesce(ProductEvent.utm_source, 'direto'))
        .order_by(func.count(func.distinct(ProductEvent.anonymous_id)).desc())
        .limit(12)
        .all()
    )
    recent = (
        ProductEvent.query
        .order_by(ProductEvent.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        'admin/product_analytics.html',
        acquisition_funnel=acquisition_funnel,
        commerce_funnel=commerce_funnel,
        revenue_summary=revenue_summary,
        counts=counts,
        sources=sources,
        recent=recent,
        since=since,
        period_days=period_days,
    )


@bp.route("/admin/notificacoes", methods=["GET"])
@login_required
def admin_notifications():
    if (getattr(current_user, 'role', '') or '').lower() != 'admin':
        abort(403)

    status = (request.args.get('status') or 'open').strip().lower()
    event_type = (request.args.get('event_type') or '').strip()
    priority = (request.args.get('priority') or '').strip()
    page = request.args.get('page', 1, type=int)

    query = AdminActionNotification.query.filter_by(recipient_user_id=current_user.id)
    if status == 'open':
        query = query.filter(AdminActionNotification.status.in_(['unread', 'read']))
    elif status in {'unread', 'read', 'resolved', 'archived'}:
        query = query.filter(AdminActionNotification.status == status)
    elif status != 'all':
        status = 'open'
        query = query.filter(AdminActionNotification.status.in_(['unread', 'read']))
    if event_type:
        query = query.filter(AdminActionNotification.event_type == event_type)
    if priority:
        query = query.filter(AdminActionNotification.priority == priority)

    pagination = (
        query
        .order_by(
            case(
                (AdminActionNotification.priority == 'critical', 0),
                (AdminActionNotification.priority == 'high', 1),
                (AdminActionNotification.priority == 'normal', 2),
                else_=3,
            ),
            AdminActionNotification.created_at.desc(),
        )
        .paginate(page=page, per_page=25, error_out=False)
    )
    event_types = [
        row[0]
        for row in db.session.query(AdminActionNotification.event_type)
        .filter_by(recipient_user_id=current_user.id)
        .distinct()
        .order_by(AdminActionNotification.event_type.asc())
        .all()
    ]
    return render_template(
        'admin/notifications.html',
        notifications=pagination.items,
        pagination=pagination,
        status=status,
        event_type=event_type,
        priority=priority,
        event_types=event_types,
    )


@bp.route("/admin/notificacoes/<int:notification_id>/ler", methods=["POST"])
@login_required
def admin_notification_mark_read(notification_id):
    if (getattr(current_user, 'role', '') or '').lower() != 'admin':
        abort(403)
    note = AdminActionNotification.query.filter_by(
        id=notification_id,
        recipient_user_id=current_user.id,
    ).first_or_404()
    if note.status == 'unread':
        note.status = 'read'
        note.read_at = now_in_brazil()
        db.session.commit()
        _invalidate_admin_action_cache(current_user.id)
    return redirect(request.referrer or url_for('admin_notifications'))


@bp.route("/admin/notificacoes/<int:notification_id>/resolver", methods=["POST"])
@login_required
def admin_notification_resolve(notification_id):
    if (getattr(current_user, 'role', '') or '').lower() != 'admin':
        abort(403)
    note = AdminActionNotification.query.filter_by(
        id=notification_id,
        recipient_user_id=current_user.id,
    ).first_or_404()
    if note.status != 'resolved':
        note.status = 'resolved'
        note.read_at = note.read_at or now_in_brazil()
        note.resolved_at = now_in_brazil()
        note.resolved_by_id = current_user.id
        db.session.commit()
        _invalidate_admin_action_cache(current_user.id)
    return redirect(request.referrer or url_for('admin_notifications'))


@bp.route("/admin/propostas-protocolos", methods=["GET"])
@login_required
def admin_protocol_proposals():
    if (getattr(current_user, 'role', '') or '').lower() != 'admin':
        abort(403)

    status = (request.args.get('status') or 'pending_review').strip().lower()
    allowed_statuses = {'pending_review', 'in_review', 'converted', 'archived', 'all'}
    if status not in allowed_statuses:
        status = 'pending_review'

    query = PropostaProtocoloClinico.query
    if status != 'all':
        query = query.filter(PropostaProtocoloClinico.status == status)
    proposals = (
        query
        .order_by(PropostaProtocoloClinico.created_at.desc())
        .limit(200)
        .all()
    )
    counts = dict(
        db.session.query(
            PropostaProtocoloClinico.status,
            func.count(PropostaProtocoloClinico.id),
        )
        .group_by(PropostaProtocoloClinico.status)
        .all()
    )
    return render_template(
        'admin/protocol_proposals.html',
        proposals=proposals,
        counts=counts,
        status=status,
    )


@bp.route("/admin/propostas-protocolos/<int:proposal_id>/iniciar-revisao", methods=["POST"])
@login_required
def admin_start_protocol_proposal_review(proposal_id):
    if (getattr(current_user, 'role', '') or '').lower() != 'admin':
        abort(403)

    proposal = PropostaProtocoloClinico.query.get_or_404(proposal_id)
    if proposal.status == 'pending_review':
        proposal.status = 'in_review'
        proposal.reviewed_by = current_user.id
        proposal.reviewed_at = now_in_brazil()
        affected_admin_ids = [
            row[0]
            for row in db.session.query(AdminActionNotification.recipient_user_id)
            .filter(
                AdminActionNotification.entity_type == 'protocol_proposal',
                AdminActionNotification.entity_id == proposal.id,
                AdminActionNotification.status.in_(['unread', 'read']),
            )
            .distinct()
            .all()
        ]
        AdminActionNotification.query.filter(
            AdminActionNotification.entity_type == 'protocol_proposal',
            AdminActionNotification.entity_id == proposal.id,
            AdminActionNotification.status.in_(['unread', 'read']),
        ).update({
            AdminActionNotification.status: 'resolved',
            AdminActionNotification.read_at: now_in_brazil(),
            AdminActionNotification.resolved_at: now_in_brazil(),
            AdminActionNotification.resolved_by_id: current_user.id,
        }, synchronize_session=False)
        db.session.commit()
        for admin_id in affected_admin_ids:
            _invalidate_admin_action_cache(admin_id)
        flash('Sugestão marcada como em revisão.', 'success')
    elif proposal.status == 'in_review':
        flash('Esta sugestão já está em revisão.', 'info')
    else:
        flash('Esta sugestão não está mais aguardando revisão.', 'warning')
    return redirect(url_for('admin_protocol_proposals', status='in_review', _anchor=f'proposal-{proposal.id}'))


@bp.route("/admin/users/<int:user_id>/promover_veterinario", methods=["POST"])
@login_required
def admin_promote_veterinarian(user_id):
    if not (current_user.is_authenticated and (current_user.role or '').lower() == 'admin'):
        abort(403)

    user = User.query.get_or_404(user_id)
    form = VeterinarianPromotionForm()

    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    crmv = form.crmv.data
    existing = (
        Veterinario.query.filter(
            func.lower(Veterinario.crmv) == crmv.lower(),
            Veterinario.user_id != user.id,
        ).first()
    )
    if existing:
        flash('Este CRMV já está associado a outro profissional.', 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    vet_profile = grant_veterinarian_role(
        user,
        crmv=crmv,
        phone=form.phone.data or None,
    )
    membership = ensure_veterinarian_membership(vet_profile)
    if membership:
        membership.ensure_trial_dates(current_app.config.get('VETERINARIAN_TRIAL_DAYS', 30))

    db.session.commit()
    flash('Usuário promovido a veterinário. Período de avaliação iniciado.', 'success')
    return redirect(url_for('conversa_admin', user_id=user.id))


@bp.route("/admin/users/<int:user_id>/promover_entregador", methods=["POST"])
@login_required
def admin_promote_delivery(user_id):
    if not (current_user.is_authenticated and (current_user.role or '').lower() == 'admin'):
        abort(403)

    user = User.query.get_or_404(user_id)
    form = DeliveryPromotionForm()

    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    if (user.worker or '').lower() == 'delivery':
        flash('Usuário já está registrado como entregador.', 'info')
        current_app.logger.info(
            'Admin %s tentou promover usuário %s que já é entregador.',
            current_user.id,
            user.id,
        )
        return redirect(url_for('conversa_admin', user_id=user.id))

    previous_worker_status = user.worker
    user.worker = 'delivery'
    db.session.commit()

    current_app.logger.info(
        'Admin %s alterou worker de %s para delivery para o usuário %s.',
        current_user.id,
        previous_worker_status,
        user.id,
    )
    flash('Usuário promovido a entregador.', 'success')
    return redirect(url_for('conversa_admin', user_id=user.id))


@bp.route("/admin/users/<int:user_id>/remover_entregador", methods=["POST"])
@login_required
def admin_remove_delivery(user_id):
    if not (current_user.is_authenticated and (current_user.role or '').lower() == 'admin'):
        abort(403)

    user = User.query.get_or_404(user_id)
    form = DeliveryDemotionForm()

    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    if (user.worker or '').lower() != 'delivery':
        flash('Usuário não está registrado como entregador.', 'info')
        current_app.logger.info(
            'Admin %s tentou remover status de entregador do usuário %s que não possui este status.',
            current_user.id,
            user.id,
        )
        return redirect(url_for('conversa_admin', user_id=user.id))

    previous_worker_status = user.worker
    user.worker = None
    db.session.commit()

    current_app.logger.info(
        'Admin %s alterou worker de %s para None para o usuário %s.',
        current_user.id,
        previous_worker_status,
        user.id,
    )
    flash('Status de entregador removido com sucesso.', 'success')
    return redirect(url_for('conversa_admin', user_id=user.id))


@bp.route("/admin/users/<int:user_id>/promover_parceiro", methods=["POST"])
@login_required
def admin_promote_parceiro(user_id):
    if not (current_user.is_authenticated and (current_user.role or '').lower() == 'admin'):
        abort(403)

    user = User.query.get_or_404(user_id)
    form = ParceiroPromotionForm()

    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    if (user.role or '').lower() == 'parceiro':
        flash('Usuário já é um parceiro de cadastro.', 'info')
        return redirect(url_for('conversa_admin', user_id=user.id))

    if (user.role or '').lower() == 'admin':
        flash('Administradores já possuem acesso total; promoção desnecessária.', 'info')
        return redirect(url_for('conversa_admin', user_id=user.id))

    previous_role = user.role
    user.role = 'parceiro'
    db.session.commit()

    current_app.logger.info(
        'Admin %s alterou role de %s para parceiro para o usuário %s.',
        current_user.id,
        previous_role,
        user.id,
    )
    flash('Usuário promovido a parceiro de cadastro.', 'success')
    return redirect(url_for('conversa_admin', user_id=user.id))


@bp.route("/admin/users/<int:user_id>/remover_parceiro", methods=["POST"])
@login_required
def admin_remove_parceiro(user_id):
    if not (current_user.is_authenticated and (current_user.role or '').lower() == 'admin'):
        abort(403)

    user = User.query.get_or_404(user_id)
    form = ParceiroDemotionForm()

    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
        return redirect(url_for('conversa_admin', user_id=user.id))

    if (user.role or '').lower() != 'parceiro':
        flash('Usuário não é um parceiro de cadastro.', 'info')
        return redirect(url_for('conversa_admin', user_id=user.id))

    user.role = 'adotante'
    db.session.commit()

    current_app.logger.info(
        'Admin %s removeu o status de parceiro do usuário %s.',
        current_user.id,
        user.id,
    )
    flash('Status de parceiro removido com sucesso.', 'success')
    return redirect(url_for('conversa_admin', user_id=user.id))


@bp.route("/admin/planos/dashboard", methods=["GET"])
@login_required
def planos_dashboard():
    from admin import _is_admin
    if not _is_admin():
        abort(403)
    metrics = summarize_plan_metrics()
    history = build_usage_history(limit=25, include_display=True)
    return render_template('planos/dashboard.html', metrics=metrics, history=history)


@bp.route("/admin/site-flags/toggle", methods=["POST"])
@login_required
def admin_toggle_site_flag():
    """Toggle de feature flags (loja_em_breve, plano_saude_em_breve).

    Aceita POST JSON: {"key": "loja_em_breve", "value": true}
    Retorna JSON: {"key": "loja_em_breve", "value": true}
    Só admin pode usar.
    """
    from admin import _is_admin
    from models.base import SiteFlag

    if not _is_admin():
        return jsonify({'error': 'Acesso negado'}), 403

    data = request.get_json(silent=True) or request.form
    key = (data.get('key') or '').strip()
    ALLOWED_KEYS = {
        'loja_em_breve': 'Loja PetOrlândia — Em breve',
        'plano_saude_em_breve': 'Plano de Saúde — Em breve',
        'home_shortcut_service': 'Atalho inicial — Agendar serviço',
        'home_shortcut_store': 'Atalho inicial — Loja Pet',
        'home_shortcut_health_plan': 'Atalho inicial — Plano de Saúde Pet',
        'home_shortcut_animals': 'Atalho inicial — Todos os animais',
        'home_section_shortcuts': 'Bloco inicial — Atalhos',
        'home_section_pets': 'Bloco inicial — Meus pets',
        'home_section_work_areas': 'Bloco inicial — Áreas de trabalho',
    }
    if key not in ALLOWED_KEYS:
        return jsonify({'error': f'Flag desconhecida: {key}'}), 400

    raw_value = data.get('value')
    new_value = (not SiteFlag.get(key, True)) if raw_value is None else str(raw_value).lower() in ('1', 'true', 'on', 'yes')
    SiteFlag.set(key, new_value, label=ALLOWED_KEYS[key])
    if not request.is_json:
        flash(f'Atalho {"ativado" if new_value else "inativado"} na página inicial.', 'success')
        if request.form.get('return_to') == 'home_editor':
            return redirect(url_for('admin_home_editor'))
        return redirect(url_for('index'))
    return jsonify({'key': key, 'value': new_value})


@bp.route('/admin/home-editor', methods=['GET'])
@login_required
def admin_home_editor():
    if not _is_admin():
        abort(403)
    flags = [
        ('home_section_work_areas', 'Áreas de trabalho', 'Bloco com os módulos profissionais e operacionais.'),
        ('home_section_shortcuts', 'Atalhos principais', 'Agendar serviço, Loja, Plano de Saúde e Animais.'),
        ('home_section_pets', 'Meus pets', 'Resumo dos pets cadastrados e próximos cuidados.'),
        ('home_shortcut_service', 'Botão: Agendar um serviço', 'Atalho dentro do bloco principal.'),
        ('home_shortcut_store', 'Botão: Loja Pet', 'Atalho dentro do bloco principal.'),
        ('home_shortcut_health_plan', 'Botão: Plano de Saúde Pet', 'Atalho dentro do bloco principal.'),
        ('home_shortcut_animals', 'Botão: Ver todos os animais', 'Atalho dentro do bloco principal.'),
    ]
    return render_template('admin/home_editor.html', flags=[
        {'key': key, 'label': label, 'description': description, 'enabled': SiteFlag.get(key, True)}
        for key, label, description in flags
    ])


@bp.route("/admin/parcerias", methods=["GET"])
@login_required
def admin_parcerias():
    if not _is_admin():
        abort(403)
    from models import CareerApplication

    clinicas_pendentes = (
        Clinica.query.filter_by(status='pendente').order_by(Clinica.id.desc()).all()
    )
    casas_pendentes = (
        CasaDeRacao.query.filter_by(status='pendente').order_by(CasaDeRacao.created_at).all()
    )
    candidaturas = (
        CareerApplication.query.filter_by(status='pendente')
        .order_by(CareerApplication.created_at.asc())
        .all()
    )
    convites = PartnerInvite.query.order_by(PartnerInvite.created_at.desc()).limit(20).all()

    novo_convite_link = session.pop('partner_invite_link', None)
    novo_convite_id = session.pop('partner_invite_id', None)
    novo_convite = db.session.get(PartnerInvite, novo_convite_id) if novo_convite_id else None
    novo_convite_whatsapp = (
        _partner_invite_whatsapp_url(novo_convite, novo_convite_link)
        if novo_convite and novo_convite_link
        else None
    )

    return render_template(
        'admin/parcerias.html',
        clinicas_pendentes=clinicas_pendentes,
        casas_pendentes=casas_pendentes,
        candidaturas=candidaturas,
        convites=convites,
        tipos_convite=PartnerInvite.TIPOS,
        novo_convite=novo_convite,
        novo_convite_link=novo_convite_link,
        novo_convite_whatsapp=novo_convite_whatsapp,
    )


@bp.route("/admin/clinica/<int:clinica_id>/aprovar", methods=["POST"])
@login_required
def admin_aprovar_clinica(clinica_id):
    if not _is_admin():
        abort(403)
    clinica = Clinica.query.get_or_404(clinica_id)
    clinica.status = 'ativa'
    db.session.commit()
    from services.notifications import notify_user
    notify_user(
        clinica.owner,
        'Sua clínica foi aprovada no PetOrlândia! 🎉',
        (
            f'Boa notícia: a clínica "{clinica.nome}" foi aprovada e já está ativa na plataforma.\n\n'
            f'Acesse o painel da clínica para completar equipe, horários e serviços:\n'
            f'{url_for("clinic_detail", clinica_id=clinica.id, _external=True)}\n\n'
            'Abraços,\nEquipe PetOrlândia'
        ),
        kind='clinica_aprovada',
    )
    flash(f'Clínica "{clinica.nome}" aprovada. O responsável foi avisado por e-mail.', 'success')
    return redirect(request.referrer or url_for('admin_parcerias'))


@bp.route("/admin/clinica/<int:clinica_id>/rejeitar", methods=["POST"])
@login_required
def admin_rejeitar_clinica(clinica_id):
    if not _is_admin():
        abort(403)
    clinica = Clinica.query.get_or_404(clinica_id)
    clinica.status = 'rejeitada'
    db.session.commit()
    from services.notifications import notify_user
    notify_user(
        clinica.owner,
        'Sobre o cadastro da sua clínica no PetOrlândia',
        (
            f'O cadastro da clínica "{clinica.nome}" não foi aprovado neste momento.\n\n'
            'Se acredita que houve um engano ou quer entender os critérios, '
            'responda este e-mail que a gente conversa.\n\n'
            'Equipe PetOrlândia'
        ),
        kind='clinica_rejeitada',
    )
    flash(f'Clínica "{clinica.nome}" rejeitada.', 'warning')
    return redirect(request.referrer or url_for('admin_parcerias'))


@bp.route("/admin/parcerias/convite", methods=["POST"])
@login_required
def admin_criar_convite():
    if not _is_admin():
        abort(403)

    tipo = (request.form.get('tipo') or '').strip()
    if tipo not in PartnerInvite.TIPOS:
        flash('Escolha um tipo de convite válido.', 'warning')
        return redirect(url_for('admin_parcerias'))

    nome = (request.form.get('nome') or '').strip() or None
    email = normalize_email(request.form.get('email')) or None
    telefone = (request.form.get('telefone') or '').strip() or None
    cidade = (request.form.get('cidade') or '').strip() or None
    try:
        validade_dias = max(1, min(90, int(request.form.get('validade_dias') or 30)))
    except ValueError:
        validade_dias = 30

    token = secrets.token_urlsafe(24)
    invite = PartnerInvite(
        tipo=tipo,
        nome=nome,
        email=email,
        telefone=telefone,
        cidade=cidade,
        token_hash=hashlib.sha256(token.encode('utf-8')).hexdigest(),
        created_by_id=current_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=validade_dias),
    )
    db.session.add(invite)
    db.session.commit()

    link = _partner_invite_url(token)
    session['partner_invite_link'] = link
    session['partner_invite_id'] = invite.id

    if email:
        from services.notifications import notify_user
        try:
            mail.send(MailMessage(
                subject='Seu convite para o PetOrlândia',
                recipients=[email],
                body=(
                    f'Olá{", " + nome.split()[0] if nome else ""}!\n\n'
                    f'Você foi convidado(a) a fazer parte do PetOrlândia como {invite.tipo_label.lower()}.\n'
                    f'Conclua seu cadastro neste link (válido por {validade_dias} dias):\n{link}\n\n'
                    'Abraços,\nEquipe PetOrlândia'
                ),
            ))
            flash('Convite criado e enviado por e-mail.', 'success')
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning('Falha ao enviar convite por e-mail: %s', exc)
            flash('Convite criado. Não foi possível enviar o e-mail — use o link ou o WhatsApp abaixo.', 'warning')
    else:
        flash('Convite criado. Envie o link pelo WhatsApp ou copie e compartilhe.', 'success')
    return redirect(url_for('admin_parcerias'))
