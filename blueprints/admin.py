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

    data = request.get_json(silent=True) or {}
    key = (data.get('key') or '').strip()
    ALLOWED_KEYS = {
        'loja_em_breve': 'Loja PetOrlândia — Em breve',
        'plano_saude_em_breve': 'Plano de Saúde — Em breve',
    }
    if key not in ALLOWED_KEYS:
        return jsonify({'error': f'Flag desconhecida: {key}'}), 400

    new_value = bool(data.get('value', not SiteFlag.get(key)))
    SiteFlag.set(key, new_value, label=ALLOWED_KEYS[key])
    return jsonify({'key': key, 'value': new_value})


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

