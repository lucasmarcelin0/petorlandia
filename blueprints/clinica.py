"""Views do domínio clinica_routes (migrado do app.py)."""
from flask import Blueprint
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from extensions import db, mail
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_mail import Message as MailMessage
from forms import APPOINTMENT_KIND_CHOICES, ClinicAddSpecialistForm, ClinicAddStaffForm, ClinicForm, ClinicHoursForm, ClinicInviteCancelForm, ClinicInviteResendForm, ClinicInviteResponseForm, ClinicInviteVeterinarianForm, ClinicProductEditForm, ClinicProductForm, ClinicStaffPermissionForm, InventoryItemForm, OrcamentoForm, VetProfileForm, VetScheduleForm, VeterinarianProfileForm
from helpers import _user_can_access_accounting, appointments_to_events, clinicas_do_usuario, ensure_veterinarian_membership, group_appointments_by_day, group_vet_schedules_by_day, has_veterinarian_profile, unique_items_by_id
from models import (
    Animal,
    Appointment,
    BlocoPrescricao,
    ClinicHours,
    ClinicInventoryItem,
    ClinicInventoryMovement,
    ClinicStaff,
    Clinica,
    Consulta,
    ExternalOnboardingInvite,
    NfseIssue,
    NfseXml,
    Orcamento,
    OrcamentoItem,
    Product,
    StorePaymentAccount,
    User,
    VetClinicInvite,
    VetSchedule,
    Veterinario,
)
from repositories import AppointmentRepository
from services.fiscal.nfse_service import create_nfse_draft_from_orcamento
from services.mercadopago_oauth import MercadoPagoOAuthError, build_authorization_start
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload, selectinload
from template_filters import normalize_phone
from time_utils import BR_TZ, utcnow
from werkzeug.exceptions import NotFound
from werkzeug.routing import BuildError
from werkzeug.utils import secure_filename

# Helpers ainda hospedados no app.py (realocação em fases futuras).
from app import (  # noqa: E402
    APPOINTMENT_KIND_LABELS,
    APPOINTMENT_STATUS_LABELS,
    ORCAMENTO_PAYMENT_STATUS_LABELS,
    ORCAMENTO_PAYMENT_STATUS_STYLES,
    ORCAMENTO_STATUS_LABELS,
    ORCAMENTO_STATUS_STYLES,
    _build_clinic_subtitle,
    _build_clinic_theme,
    _build_orcamento_nfse_snapshot,
    _build_user_avatar_map,
    _clinic_initials,
    _clinic_loja_access,
    _coerce_int,
    _collect_clinic_ids,
    _ensure_external_onboarding_invite_table,
    _ensure_inventory_movement_columns,
    _ensure_inventory_movement_table,
    _ensure_inventory_threshold_columns,
    _ensure_veterinarian_profile,
    _external_invite_document_url,
    _external_invite_exame_imagem,
    _extract_orcamento_item_payloads,
    _first_access_url_for_user,
    _format_vet_coverage_cities,
    _orcamento_form_item_rows_from_model,
    _orcamento_form_item_rows_from_request,
    _orcamento_submitted_item_fields_present,
    _parse_month_parameter,
    _public_pricing_config,
    _render_messages_page,
    _render_orcamento_form,
    _send_clinic_invite_email,
    _user_can_manage_clinic,
    current_user_clinic_id,
    enviar_mensagem_whatsapp,
    find_users_by_phone,
    formatar_telefone,
    local_date_range_to_utc,
)

bp = Blueprint("clinica_routes", __name__)


def get_blueprint():
    return bp


def _is_admin(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app._is_admin.
    import app as app_module
    return app_module._is_admin(*args, **kwargs)


def ensure_clinic_access(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.ensure_clinic_access.
    import app as app_module
    return app_module.ensure_clinic_access(*args, **kwargs)


def is_veterinarian(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.is_veterinarian.
    import app as app_module
    return app_module.is_veterinarian(*args, **kwargs)


def upload_to_s3(*args, **kwargs):
    # Late-binding: testes fazem monkeypatch de app.upload_to_s3.
    import app as app_module
    return app_module.upload_to_s3(*args, **kwargs)



@bp.route("/clinicas", methods=["GET"])
def clinicas():
    clinicas = clinicas_do_usuario().all()
    return render_template('clinica/clinicas.html', clinicas=clinicas)


@bp.route("/parceiros/clinica", methods=["GET"])
def parceiro_clinica_landing():
    if current_user.is_authenticated:
        clinicas = clinicas_do_usuario().all()
        if clinicas:
            preferred_id = (
                getattr(getattr(current_user, 'veterinario', None), 'clinica_id', None)
                or getattr(current_user, 'clinica_id', None)
            )
            target = next((c for c in clinicas if c.id == preferred_id), clinicas[0])
            return redirect(url_for('clinic_detail', clinica_id=target.id) + '#clinica')
        return redirect(url_for('minha_clinica'))
    return render_template('clinica/parceiro_landing.html')


@bp.route("/acesso-laudo/<string:token>", methods=["GET"])
def external_onboarding_invite(token):
    _ensure_external_onboarding_invite_table()
    invite = ExternalOnboardingInvite.query.filter_by(token=token).first_or_404()
    expired = bool(invite.expires_at and invite.expires_at < datetime.now(BR_TZ))
    referrer = invite.referrer_vet.user if invite.referrer_vet and invite.referrer_vet.user else invite.created_by
    register_url = (
        url_for('first_access', token=invite.token, next=request.path)
        if invite.invite_type == 'tutor'
        else url_for('register', next=request.path)
    )
    login_url = url_for('login_view', next=request.path)
    exame_imagem = _external_invite_exame_imagem(invite)
    document_url = _external_invite_document_url(invite, exame_imagem)
    tutor_can_view = bool(
        invite.invite_type == 'tutor'
        and not expired
        and document_url
        and (
            (exame_imagem and exame_imagem.liberado_para_tutor)
            or not exame_imagem
        )
    )
    clinic_can_view = bool(invite.invite_type == 'clinic' and not expired and document_url)
    pricing = _public_pricing_config() if invite.invite_type == 'clinic' else None
    if current_user.is_authenticated and not invite.used_at:
        invite.used_at = datetime.now(BR_TZ)
        db.session.commit()
    return render_template(
        'clinica/external_onboarding_invite.html',
        invite=invite,
        exame_imagem=exame_imagem,
        document_url=document_url,
        tutor_can_view=tutor_can_view,
        clinic_can_view=clinic_can_view,
        pricing=pricing,
        expired=expired,
        referrer=referrer,
        register_url=register_url,
        login_url=login_url,
    )


@bp.route("/primeiro-acesso-clinica/<string:token>", methods=["GET"])
def external_clinic_first_access_invite(token):
    _ensure_external_onboarding_invite_table()
    invite = ExternalOnboardingInvite.query.filter_by(token=token).first_or_404()
    if invite.invite_type != 'clinic':
        abort(404)
    return external_onboarding_invite(token)


@bp.route("/minha-clinica", methods=["GET", "POST"])
def minha_clinica():
    clinicas = clinicas_do_usuario().all()
    if not clinicas:
        form = ClinicForm()
        if form.validate_on_submit():
            clinica = Clinica(
                nome=form.nome.data,
                cnpj=form.cnpj.data,
                endereco=form.endereco.data,
                telefone=form.telefone.data,
                email=form.email.data,
                modo_entrega=form.modo_entrega.data or 'plataforma',
                valor_frete=form.valor_frete.data or Decimal('0'),
                pedido_minimo_entrega=form.pedido_minimo_entrega.data or None,
                prazo_entrega_min=form.prazo_entrega_min.data or None,
                prazo_entrega_max=form.prazo_entrega_max.data or None,
                owner_id=current_user.id,
                status='pendente',
            )
            file = form.logotipo.data
            if file and getattr(file, "filename", ""):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                image_url = upload_to_s3(file, filename, folder="clinicas")
                if image_url:
                    clinica.logotipo = image_url
                    clinica.photo_rotation = form.photo_rotation.data
                    clinica.photo_zoom = form.photo_zoom.data
                    clinica.photo_offset_x = form.photo_offset_x.data
                    clinica.photo_offset_y = form.photo_offset_y.data
            db.session.add(clinica)
            db.session.commit()
            if current_user.veterinario:
                current_user.veterinario.clinica_id = clinica.id
            current_user.clinica_id = clinica.id
            db.session.commit()
            from services.notifications import notify_admins
            notify_admins(
                f'Nova clínica aguardando aprovação: {clinica.nome} (responsável: {current_user.name}).',
                kind='clinica_pendente',
                url=url_for('admin_parcerias', _external=True),
            )
            flash(
                'Cadastro enviado! Sua clínica está em análise — você será avisado assim que for aprovada. '
                'Enquanto isso, já pode completar horários, equipe e demais informações.',
                'success',
            )
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#clinica')
        return render_template('clinica/create_clinic.html', form=form)

    preferred_clinic_id = None
    if getattr(current_user, 'veterinario', None) and current_user.veterinario.clinica_id:
        preferred_clinic_id = current_user.veterinario.clinica_id
    elif current_user.clinica_id:
        preferred_clinic_id = current_user.clinica_id

    if preferred_clinic_id:
        preferred_clinic = next((c for c in clinicas if c.id == preferred_clinic_id), None)
        if preferred_clinic:
            return redirect(url_for('clinic_detail', clinica_id=preferred_clinic.id) + '#clinica')

    if len(clinicas) == 1:
        return redirect(url_for('clinic_detail', clinica_id=clinicas[0].id) + '#clinica')
    overview = []
    for c in clinicas:
        staff = c.veterinarios
        upcoming = (
            Appointment.query.filter_by(clinica_id=c.id)
            .filter(Appointment.scheduled_at >= utcnow())
            .order_by(Appointment.scheduled_at)
            .limit(5)
            .all()
        )
        overview.append({'clinic': c, 'staff': staff, 'appointments': upcoming})
    return render_template('clinica/multi_clinic_dashboard.html', clinics=overview)


@bp.route("/clinica/<int:clinica_id>/mercado-pago/conectar", methods=["POST"])
@login_required
def clinic_mercadopago_oauth_start(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)
    try:
        oauth_start = build_authorization_start()
    except MercadoPagoOAuthError as exc:
        current_app.logger.error('clinic_mercadopago_oauth_start failed for clinica %s: %s', clinica.id, exc)
        flash('Não foi possível iniciar a conexão com o Mercado Pago. Tente novamente ou entre em contato com o suporte.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#clinica')

    account = (
        StorePaymentAccount.query
        .filter_by(clinica_id=clinica.id, provider='mercado_pago')
        .first()
    )
    if not account:
        account = StorePaymentAccount(clinica_id=clinica.id, provider='mercado_pago')
        db.session.add(account)

    account.oauth_state = oauth_start.state
    account.code_verifier = oauth_start.code_verifier
    account.status = 'pending'
    account.error_message = None
    db.session.commit()
    return redirect(oauth_start.authorization_url)


@bp.route("/clinica/<int:clinica_id>/mercado-pago/desconectar", methods=["POST"])
@login_required
def clinic_mercadopago_oauth_disconnect(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)
    account = (
        StorePaymentAccount.query
        .filter_by(clinica_id=clinica.id, provider='mercado_pago')
        .first()
    )
    if account:
        account.status = 'revoked'
        account.access_token = None
        account.refresh_token = None
        account.oauth_state = None
        account.code_verifier = None
        db.session.commit()
    flash('Conexão com o Mercado Pago desativada para esta clínica.', 'info')
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#clinica')


@bp.route("/clinica/<int:clinica_id>/mercado-pago/credenciais", methods=["POST"])
@login_required
def clinic_mercadopago_direct_save(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)
    access_token = (request.form.get('access_token') or '').strip()
    public_key = (request.form.get('public_key') or '').strip()

    if not access_token:
        flash('Informe o Access Token do Mercado Pago.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#clinica')

    if not (access_token.startswith('APP_USR-') or access_token.startswith('TEST-')):
        flash('Access Token inválido. Deve começar com APP_USR- (produção) ou TEST- (teste).', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#clinica')

    account = (
        StorePaymentAccount.query
        .filter_by(clinica_id=clinica.id, provider='mercado_pago')
        .first()
    )
    if not account:
        account = StorePaymentAccount(clinica_id=clinica.id, provider='mercado_pago')
        db.session.add(account)

    account.access_token = access_token
    account.public_key = public_key or None
    account.refresh_token = None
    account.oauth_state = None
    account.code_verifier = None
    account.status = 'connected'
    account.error_message = None
    account.connected_at = utcnow()
    account.last_refreshed_at = utcnow()
    db.session.commit()
    flash('Credenciais do Mercado Pago salvas. A clínica já pode receber pagamentos.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#clinica')


@bp.route("/clinica/<int:clinica_id>", methods=["GET", "POST"])
@login_required
def clinic_detail(clinica_id):
    appointment_repo = AppointmentRepository()
    if _is_admin():
        clinica = Clinica.query.get_or_404(clinica_id)
    else:
        # Para usuários não administradores, garantimos que a clínica
        # consultada pertence ao conjunto de clínicas acessíveis ao
        # usuário atual. O uso de ``filter`` com ``Clinica.id`` evita
        # possíveis ambiguidades de ``filter_by`` e assegura que o
        # ``clinica_id`` da URL seja respeitado corretamente.
        clinica = (
            clinicas_do_usuario()
            .filter(Clinica.id == clinica_id)
            .first_or_404()
        )
    from models import VetClinicInvite, Specialty

    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    if not _is_admin() and not is_owner:
        abort(403)
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_inventory_perm = staff.can_manage_inventory if staff else False
    show_inventory = _is_admin() or is_owner or has_inventory_perm
    inventory_form = InventoryItemForm() if show_inventory else None
    inventory_items = []
    inventory_movements = []
    critical_items_count = 0
    overstock_items_count = 0
    total_stock_quantity = 0
    if show_inventory:
        _ensure_inventory_threshold_columns()
        _ensure_inventory_movement_table()
        _ensure_inventory_movement_columns()
        inventory_items = (
            ClinicInventoryItem.query
            .filter_by(clinica_id=clinica.id)
            .order_by(ClinicInventoryItem.name)
            .all()
        )
        for item in inventory_items:
            qty = item.quantity or 0
            total_stock_quantity += qty
            if item.min_quantity is not None and qty < item.min_quantity:
                critical_items_count += 1
            if item.max_quantity is not None and qty > item.max_quantity:
                overstock_items_count += 1
        inventory_movements = (
            ClinicInventoryMovement.query
            .filter_by(clinica_id=clinica.id)
            .order_by(ClinicInventoryMovement.created_at.desc())
            .limit(10)
            .all()
        )
    hours_form = ClinicHoursForm()
    clinic_form = ClinicForm(obj=clinica)
    invite_form = ClinicInviteVeterinarianForm()
    invite_cancel_form = ClinicInviteCancelForm(prefix='cancel_invite')
    invite_resend_form = ClinicInviteResendForm(prefix='resend_invite')
    staff_form = ClinicAddStaffForm()
    specialist_form = ClinicAddSpecialistForm(prefix='specialist')
    if request.method == 'GET':
        hours_form.clinica_id.data = clinica.id
    pode_editar = _user_can_manage_clinic(clinica)
    can_view_metrics = _is_admin() or pode_editar
    if not can_view_metrics and staff:
        can_view_metrics = any(
            [
                staff.can_manage_clients,
                staff.can_manage_animals,
                staff.can_manage_schedule,
                staff.can_manage_inventory,
            ]
        )
    if staff_form.submit.data and staff_form.validate_on_submit():
        if not (_is_admin() or current_user.id == clinica.owner_id):
            abort(403)
        user = User.query.filter_by(email=staff_form.email.data).first()
        if not user:
            flash('Usuário não encontrado', 'danger')
        else:
            staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=user.id).first()
            if staff:
                flash('Funcionário já está na clínica', 'warning')
            else:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=user.id)
                db.session.add(staff)
                user.clinica_id = clinica.id
                if getattr(user, 'veterinario', None):
                    user.veterinario.clinica_id = clinica.id
                    db.session.add(user.veterinario)
                db.session.add(user)
                db.session.commit()
                flash('Funcionário adicionado. Defina as permissões.', 'success')
                return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if specialist_form.submit.data and specialist_form.validate_on_submit():
        if not (_is_admin() or current_user.id == clinica.owner_id):
            abort(403)
        email = specialist_form.email.data.strip().lower()
        user = (
            User.query
            .filter(func.lower(User.email) == email)
            .first()
        )
        vet_profile = getattr(user, 'veterinario', None) if user else None
        if not vet_profile:
            flash('Especialista não encontrado.', 'danger')
        elif vet_profile in clinica.veterinarios_associados or vet_profile.clinica_id == clinica.id:
            flash('Especialista já associado à clínica.', 'warning')
        else:
            clinica.veterinarios_associados.append(vet_profile)
            staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=user.id).first()
            if not staff:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=user.id)
                db.session.add(staff)
            db.session.commit()
            flash('Especialista associado com sucesso. Defina as permissões.', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#especialistas')

    if clinic_form.submit.data and clinic_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        original_logo = clinica.logotipo
        clinic_form.populate_obj(clinica)
        file = clinic_form.logotipo.data
        if file and getattr(file, 'filename', ''):
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            image_url = upload_to_s3(file, filename, folder="clinicas")
            if image_url:
                clinica.logotipo = image_url
        else:
            clinica.logotipo = original_logo
        db.session.commit()
        flash('Clínica atualizada com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    if invite_form.submit.data and invite_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        email = invite_form.email.data.strip().lower()
        user = (
            User.query
            .filter(func.lower(User.email) == email)
            .first()
        )
        if not user or getattr(user, 'worker', '') != 'veterinario' or not getattr(user, 'veterinario', None):
            flash('Veterinário não encontrado.', 'danger')
        else:
            existing = VetClinicInvite.query.filter_by(
                clinica_id=clinica.id,
                veterinario_id=user.veterinario.id,
                status='pending',
            ).first()
            if user.veterinario.clinica_id == clinica.id:
                flash('Veterinário já associado à clínica.', 'warning')
            elif existing:
                flash('Convite já enviado.', 'warning')
            else:
                invite = VetClinicInvite(
                    clinica_id=clinica.id,
                    veterinario_id=user.veterinario.id,
                )
                db.session.add(invite)
                db.session.commit()
                if _send_clinic_invite_email(clinica, user, current_user):
                    flash('Convite enviado.', 'success')
                else:
                    flash(
                        'Convite criado, mas houve um problema ao enviar o e-mail para o veterinário.',
                        'warning',
                    )
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')
    if hours_form.submit.data and hours_form.validate_on_submit():
        if not pode_editar:
            abort(403)
        for dia in hours_form.dias_semana.data:
            existentes = ClinicHours.query.filter_by(
                clinica_id=hours_form.clinica_id.data, dia_semana=dia
            ).all()
            if existentes:
                existentes[0].hora_abertura = hours_form.hora_abertura.data
                existentes[0].hora_fechamento = hours_form.hora_fechamento.data
                for extra in existentes[1:]:
                    db.session.delete(extra)
            else:
                db.session.add(
                    ClinicHours(
                        clinica_id=hours_form.clinica_id.data,
                        dia_semana=dia,
                        hora_abertura=hours_form.hora_abertura.data,
                        hora_fechamento=hours_form.hora_fechamento.data,
                    )
                )
        db.session.commit()
        flash('Horário salvo com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    horarios = ClinicHours.query.filter_by(clinica_id=clinica_id).all()
    veterinarios = Veterinario.query.filter_by(clinica_id=clinica_id).all()
    # Inclui o vet dono da clínica mesmo que clinica_id do seu perfil seja diferente
    owner_vet = getattr(getattr(clinica, 'owner', None), 'veterinario', None)
    if owner_vet and owner_vet.id not in {v.id for v in veterinarios}:
        veterinarios = [owner_vet] + list(veterinarios)
    associated_vets = list(clinica.veterinarios_associados)
    veterinarios_ids = {v.id for v in veterinarios}
    specialists = [
        v for v in associated_vets if v.id not in veterinarios_ids
    ]
    specialists.sort(key=lambda vet: (vet.user.name or '').lower())
    all_veterinarios = Veterinario.query.all()
    staff_members = ClinicStaff.query.filter(
        ClinicStaff.clinic_id == clinica.id,
        ClinicStaff.user.has(User.veterinario == None),
    ).all()

    team_users = []
    for staff_member in staff_members:
        user = getattr(staff_member, "user", None)
        if user:
            team_users.append(user)
    for vet_profile in veterinarios + specialists:
        user = getattr(vet_profile, "user", None)
        if user:
            team_users.append(user)
    team_user_avatars = _build_user_avatar_map(team_users)

    clinic_invites = (
        VetClinicInvite.query
        .filter_by(clinica_id=clinica.id)
        .order_by(VetClinicInvite.created_at.desc())
        .all()
    )
    invites_by_status = defaultdict(list)
    for invite in clinic_invites:
        invites_by_status[invite.status].append(invite)
    invites_by_status = dict(invites_by_status)
    invite_status_order = ['pending', 'declined', 'accepted', 'cancelled']

    staff_permission_forms = {}
    for s in staff_members:
        form = ClinicStaffPermissionForm(prefix=f"perm_{s.user.id}", obj=s)
        if request.method == 'GET':
            form.appointments_view.data = s.user.worker or ''
        staff_permission_forms[s.user.id] = form

    vets_for_forms = unique_items_by_id(veterinarios + specialists)

    vet_permission_forms = {}
    for v in vets_for_forms:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=v.user.id).first()
        if not staff:
            staff = ClinicStaff(clinic_id=clinica.id, user_id=v.user.id)
        form = ClinicStaffPermissionForm(prefix=f"vet_perm_{v.user.id}", obj=staff)
        if request.method == 'GET':
            form.appointments_view.data = v.user.worker or ''
        vet_permission_forms[v.user.id] = form

    all_specialties = Specialty.query.order_by(Specialty.nome).all()
    vet_profile_forms = {}
    for v in vets_for_forms:
        form = VetProfileForm(
            prefix=f"vetprofile_{v.id}",
            formdata=request.form if request.method == 'POST' else None,
        )
        form.specialties.choices = [(s.id, s.nome) for s in all_specialties]
        if request.method == 'GET':
            form.name.data = v.user.name or ''
            form.phone.data = v.user.phone or ''
            form.email.data = v.user.email or ''
            form.crmv.data = v.crmv or ''
            form.crmv_estado.data = v.crmv_estado or ''
            form.specialties.data = [s.id for s in v.specialties]
            form.cidades_atendidas.data = _format_vet_coverage_cities(v)
        vet_profile_forms[v.id] = form

    for s in staff_members:
        form = staff_permission_forms[s.user.id]
        if form.submit.data and form.validate_on_submit():
            if not (_is_admin() or current_user.id == clinica.owner_id):
                abort(403)
            form.populate_obj(s)
            s.user_id = s.user.id
            db.session.add(s)
            # Atualiza visão de agenda do colaborador
            new_view = form.appointments_view.data or None
            # Colaboradores não têm perfil de veterinário — impede atribuição indevida
            if new_view == 'veterinario' and not getattr(s.user, 'veterinario', None):
                new_view = 'colaborador'
            s.user.worker = new_view
            db.session.add(s.user)
            db.session.commit()
            flash('Permissões atualizadas', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    for v in vets_for_forms:
        form = vet_permission_forms[v.user.id]
        if form.submit.data and form.validate_on_submit():
            if not (_is_admin() or current_user.id == clinica.owner_id):
                abort(403)
            staff = ClinicStaff.query.filter_by(
                clinic_id=clinica.id, user_id=v.user.id
            ).first()
            if not staff:
                staff = ClinicStaff(clinic_id=clinica.id, user_id=v.user.id)
            form.populate_obj(staff)
            staff.user_id = v.user.id
            db.session.add(staff)
            # Atualiza visão de agenda do veterinário
            new_view = form.appointments_view.data or None
            if new_view in ('veterinario', 'colaborador'):
                v.user.worker = new_view
                db.session.add(v.user)
            db.session.commit()
            flash('Permissões atualizadas', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    vet_schedule_forms = {}
    for v in vets_for_forms:
        form = VetScheduleForm(prefix=f"schedule_{v.id}")
        form.veterinario_id.choices = [(v.id, v.user.name)]
        if request.method == 'GET':
            form.veterinario_id.data = v.id
        vet_schedule_forms[v.id] = form

    for v in vets_for_forms:
        form = vet_schedule_forms[v.id]
        if form.submit.data and form.validate_on_submit():
            if not pode_editar:
                abort(403)
            for dia in form.dias_semana.data:
                db.session.add(
                    VetSchedule(
                        veterinario_id=form.veterinario_id.data,
                        dia_semana=dia,
                        hora_inicio=form.hora_inicio.data,
                        hora_fim=form.hora_fim.data,
                        intervalo_inicio=form.intervalo_inicio.data,
                        intervalo_fim=form.intervalo_fim.data,
                    )
                )
            db.session.commit()
            flash('Horário do funcionário salvo com sucesso.', 'success')
            return redirect(url_for('clinic_detail', clinica_id=clinica.id))
    animais_adicionados = (
        Animal.query
        .filter_by(clinica_id=clinica_id)
        .filter(Animal.removido_em.is_(None))
        .all()
    )
    tutores_adicionados = (
        User.query
        .filter_by(clinica_id=clinica_id)
        .filter(or_(User.worker != 'veterinario', User.worker == None))
        .all()
    )

    clinic_metrics = {
        'animals': db.session.query(func.count(Animal.id))
        .filter(Animal.clinica_id == clinica_id, Animal.removido_em.is_(None))
        .scalar()
        or 0,
        'tutors': db.session.query(func.count(User.id))
        .filter(
            User.clinica_id == clinica_id,
            or_(User.worker != 'veterinario', User.worker == None),
        )
        .scalar()
        or 0,
        'future_appointments': db.session.query(func.count(Appointment.id))
        .filter(
            Appointment.clinica_id == clinica_id,
            Appointment.scheduled_at >= utcnow(),
            Appointment.status == 'scheduled',
        )
        .scalar()
        or 0,
        'open_prescriptions': db.session.query(func.count(BlocoPrescricao.id))
        .filter(BlocoPrescricao.clinica_id == clinica_id)
        .scalar()
        or 0,
    }

    valid_vet_ids = {getattr(v, 'id', None) for v in vets_for_forms if getattr(v, 'id', None)}
    appointment_vet_options = [
        {
            'id': v.id,
            'name': getattr(getattr(v, 'user', None), 'name', '') or f'Veterinário #{v.id}',
        }
        for v in sorted(vets_for_forms, key=lambda vet: (getattr(getattr(vet, 'user', None), 'name', '') or '').lower())
        if getattr(v, 'id', None)
    ]

    status_labels = dict(APPOINTMENT_STATUS_LABELS)
    kind_labels = dict(APPOINTMENT_KIND_LABELS)

    for value, label in APPOINTMENT_KIND_CHOICES:
        if value:
            kind_labels.setdefault(value, label)

    clinic_status_values = appointment_repo.get_distinct_statuses(clinica_id)
    clinic_kind_values = appointment_repo.get_distinct_kinds(clinica_id)

    for status in clinic_status_values:
        status_labels.setdefault(status, status.replace('_', ' ').title())

    for kind in clinic_kind_values:
        kind_labels.setdefault(kind, kind.replace('_', ' ').title())

    appointment_view = (request.args.get('view') or '').strip().lower()
    if appointment_view not in ('list', 'calendar'):
        appointment_view = 'list'

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    vet_filter_id = request.args.get('vet_id', type=int)
    status_filter = (request.args.get('status') or '').strip()
    type_filter = (request.args.get('type') or '').strip()

    if vet_filter_id and vet_filter_id not in valid_vet_ids:
        vet_filter_id = None
    if status_filter and status_filter not in status_labels:
        status_filter = ''
    if type_filter and type_filter not in kind_labels:
        type_filter = ''
    start_dt = None
    end_dt = None
    if start_str:
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        except ValueError:
            start_dt = None
    if end_str:
        try:
            end_dt = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            end_dt = None

    start_dt_utc, end_dt_utc = local_date_range_to_utc(start_dt, end_dt)

    appointments = appointment_repo.list_filtered(
        clinic_id=clinica_id,
        start_dt_utc=start_dt_utc,
        end_dt_utc=end_dt_utc,
        vet_id=vet_filter_id,
        status=status_filter or None,
        kind=type_filter or None,
    )
    appointments_grouped = group_appointments_by_day(appointments)
    appointments_events = []
    if appointment_view == 'calendar':
        appointments_events = appointments_to_events(appointments)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template(
            "partials/appointments_table.html",
            appointments_grouped=appointments_grouped,
        )

    grouped_vet_schedules = {
        v.id: group_vet_schedules_by_day(v.horarios)
        for v in vets_for_forms
    }

    orcamento_search = (request.args.get('orcamento_search') or '').strip()
    orcamento_status_filter = request.args.get('orcamento_status') or 'all'
    orcamento_from_str = request.args.get('orcamento_from') or ''
    orcamento_to_str = request.args.get('orcamento_to') or ''
    orcamento_page = request.args.get('orcamento_page', type=int) or 1
    orcamento_page = max(1, orcamento_page)

    orcamentos_query = (
        Orcamento.query.options(
            joinedload(Orcamento.consulta)
            .joinedload(Consulta.animal)
            .joinedload(Animal.owner),
            selectinload(Orcamento.items),
        )
        .filter(Orcamento.clinica_id == clinica_id)
    )

    if orcamento_status_filter and orcamento_status_filter != 'all':
        orcamentos_query = orcamentos_query.filter(Orcamento.status == orcamento_status_filter)

    if orcamento_search:
        like_term = f"%{orcamento_search}%"
        orcamentos_query = (
            orcamentos_query.outerjoin(Consulta, Orcamento.consulta)
            .outerjoin(Animal, Consulta.animal)
            .outerjoin(User, Animal.owner)
            .filter(
                or_(
                    Orcamento.descricao.ilike(like_term),
                    Animal.name.ilike(like_term),
                    User.name.ilike(like_term),
                )
            )
        )

    def _parse_date(date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return None

    date_from = _parse_date(orcamento_from_str)
    date_to = _parse_date(orcamento_to_str)
    if date_to:
        date_to = date_to + timedelta(days=1)

    if date_from:
        orcamentos_query = orcamentos_query.filter(Orcamento.updated_at >= date_from)
    if date_to:
        orcamentos_query = orcamentos_query.filter(Orcamento.updated_at < date_to)

    if orcamento_search:
        orcamentos_query = orcamentos_query.distinct()

    summary_orcamentos = list(orcamentos_query.options(selectinload(Orcamento.items)).all())
    unique_summary_orcamentos = {}
    for budget in summary_orcamentos:
        unique_summary_orcamentos[budget.id] = budget
    summary_orcamentos = list(unique_summary_orcamentos.values())

    orcamento_status_counts = {
        status or 'draft': count
        for status, count in (
            db.session.query(Orcamento.status, func.count(Orcamento.id))
            .filter(Orcamento.clinica_id == clinica_id)
            .group_by(Orcamento.status)
            .all()
        )
    }
    orcamento_status_counts['all'] = sum(orcamento_status_counts.values())

    orcamento_summary = {
        'filtered_total': len(summary_orcamentos),
        'total_amount': sum((budget.total or Decimal('0.00') for budget in summary_orcamentos), Decimal('0.00')),
        'approved_count': sum(1 for budget in summary_orcamentos if budget.status == 'approved'),
        'sent_count': sum(1 for budget in summary_orcamentos if budget.status == 'sent'),
        'draft_count': sum(1 for budget in summary_orcamentos if budget.status == 'draft'),
        'paid_count': sum(1 for budget in summary_orcamentos if budget.payment_status == 'paid'),
        'payment_pending_count': sum(1 for budget in summary_orcamentos if budget.payment_status == 'pending'),
        'without_items_count': sum(1 for budget in summary_orcamentos if not budget.items),
    }

    budget_issue_identifiers = [
        f"consulta:{budget.consulta_id}"
        for budget in summary_orcamentos
        if budget.consulta_id
    ]
    latest_nfse_issue_by_identifier = {}
    pdf_issue_ids = set()
    if budget_issue_identifiers:
        nfse_issues = (
            NfseIssue.query
            .filter(NfseIssue.clinica_id == clinica_id)
            .filter(NfseIssue.internal_identifier.in_(budget_issue_identifiers))
            .order_by(NfseIssue.created_at.desc())
            .all()
        )
        for issue in nfse_issues:
            if issue.internal_identifier and issue.internal_identifier not in latest_nfse_issue_by_identifier:
                latest_nfse_issue_by_identifier[issue.internal_identifier] = issue
        issue_ids = [issue.id for issue in latest_nfse_issue_by_identifier.values()]
        if issue_ids:
            pdf_issue_ids = {
                row.nfse_issue_id
                for row in (
                    NfseXml.query
                    .filter(NfseXml.nfse_issue_id.in_(issue_ids))
                    .filter(NfseXml.tipo.ilike("%pdf%"))
                    .all()
                )
            }

    orcamento_nfse_snapshots = {}
    for budget in summary_orcamentos:
        issue = latest_nfse_issue_by_identifier.get(f"consulta:{budget.consulta_id}") if budget.consulta_id else None
        orcamento_nfse_snapshots[budget.id] = _build_orcamento_nfse_snapshot(
            budget,
            clinica,
            issue=issue,
            pdf_available=bool(issue and issue.id in pdf_issue_ids),
        )

    fiscal_applicable = [snapshot for snapshot in orcamento_nfse_snapshots.values() if snapshot["applicable"]]
    orcamento_fiscal_summary = {
        "applicable_count": len(fiscal_applicable),
        "ready_count": sum(1 for snapshot in fiscal_applicable if snapshot["kind"] == "ready"),
        "emitted_count": sum(1 for snapshot in fiscal_applicable if snapshot["kind"] == "emitted"),
        "processing_count": sum(1 for snapshot in fiscal_applicable if snapshot["kind"] == "processing"),
        "attention_count": sum(1 for snapshot in fiscal_applicable if snapshot["kind"] in {"config", "issue"}),
    }

    per_page = current_app.config.get('ORCAMENTOS_PER_PAGE', 10)
    orcamentos_pagination = (
        orcamentos_query
        .order_by(Orcamento.updated_at.desc())
        .paginate(page=orcamento_page, per_page=per_page, error_out=False)
    )

    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    next7_str = (today + timedelta(days=7)).strftime('%Y-%m-%d')
    now_dt = utcnow()

    try:
        clinic_new_animal_url = url_for('criar_animal', clinica_id=clinica.id)
    except BuildError:
        clinic_new_animal_url = url_for('novo_animal')

    appointment_filters = {
        'start': start_str or '',
        'end': end_str or '',
        'vet_id': str(vet_filter_id) if vet_filter_id else '',
        'status': status_filter,
        'type': type_filter,
        'view': appointment_view,
    }

    def _normalize_filter_value(value):
        if value in (None, ''):
            return ''
        return str(value)

    def _is_active_for_query(query):
        for key, value in query.items():
            normalized = _normalize_filter_value(value)
            current = appointment_filters.get(key) or ''
            if normalized == '':
                if current not in ('', None):
                    return False
            elif current != normalized:
                return False
        return True

    def _build_filter_url(**overrides):
        params = {k: v for k, v in appointment_filters.items() if v not in ('', None)}
        for key, value in overrides.items():
            normalized_value = _normalize_filter_value(value)
            if normalized_value == '':
                params.pop(key, None)
            else:
                params[key] = normalized_value
        return url_for('clinic_detail', clinica_id=clinica.id, **params)

    def _build_quick_entry(label, query, icon=None):
        normalized_query = {k: _normalize_filter_value(v) for k, v in query.items()}
        return {
            'label': label,
            'icon': icon,
            'query': normalized_query,
            'url': _build_filter_url(**query),
            'active': _is_active_for_query(query),
        }

    appointment_status_options = [
        {'value': '', 'label': 'Todos os status'},
        *[
            {'value': key, 'label': label}
            for key, label in sorted(status_labels.items(), key=lambda item: item[1])
        ],
    ]

    appointment_type_options = [
        {'value': '', 'label': 'Todos os tipos'},
        *[
            {'value': key, 'label': label}
            for key, label in sorted(kind_labels.items(), key=lambda item: item[1])
        ],
    ]

    appointment_quick_ranges = [
        _build_quick_entry(
            'Hoje',
            {'start': today_str, 'end': today_str},
            icon='fa-solid fa-calendar-day',
        ),
        _build_quick_entry(
            'Próximos 7 dias',
            {'start': today_str, 'end': next7_str},
            icon='fa-solid fa-calendar-week',
        ),
        _build_quick_entry(
            'Todos os períodos',
            {'start': '', 'end': ''},
            icon='fa-solid fa-infinity',
        ),
    ]

    appointment_status_quick_filters = [
        _build_quick_entry('Todos os status', {'status': ''}),
        *[
            _build_quick_entry(label, {'status': key})
            for key, label in sorted(status_labels.items(), key=lambda item: item[1])
        ],
    ]

    appointment_type_quick_filters = [
        _build_quick_entry('Todos os tipos', {'type': ''}),
        *[
            _build_quick_entry(label, {'type': key})
            for key, label in sorted(kind_labels.items(), key=lambda item: item[1])
        ],
    ]

    clinic_theme = _build_clinic_theme(clinica)
    clinic_subtitle = _build_clinic_subtitle(clinica)
    clinic_initials = _clinic_initials(clinica)
    payment_account = (
        StorePaymentAccount.query
        .filter_by(clinica_id=clinica.id, provider='mercado_pago')
        .first()
    )
    mp_oauth_available = bool((current_app.config.get("MERCADOPAGO_CLIENT_ID") or "").strip())
    mp_platform_configured = bool((current_app.config.get("MERCADOPAGO_ACCESS_TOKEN") or "").strip())

    return render_template(
        'clinica/clinic_detail.html',
        clinica=clinica,
        clinic_theme=clinic_theme,
        clinic_subtitle=clinic_subtitle,
        clinic_initials=clinic_initials,
        payment_account=payment_account,
        mp_oauth_available=mp_oauth_available,
        mp_platform_configured=mp_platform_configured,
        horarios=horarios,
        form=hours_form,
        clinic_form=clinic_form,
        invite_form=invite_form,
        invite_cancel_form=invite_cancel_form,
        invite_resend_form=invite_resend_form,
        veterinarios=veterinarios,
        all_veterinarios=all_veterinarios,
        vet_schedule_forms=vet_schedule_forms,
        staff_members=staff_members,
        staff_form=staff_form,
        specialists=specialists,
        specialist_form=specialist_form,
        staff_permission_forms=staff_permission_forms,
        vet_permission_forms=vet_permission_forms,
        vet_profile_forms=vet_profile_forms,
        all_specialties=all_specialties,
        appointments=appointments,
        appointments_grouped=appointments_grouped,
        grouped_vet_schedules=grouped_vet_schedules,
        orcamentos=orcamentos_pagination.items,
        orcamentos_pagination=orcamentos_pagination,
        orcamento_filters={
            'search': orcamento_search,
            'status': orcamento_status_filter,
            'from': orcamento_from_str,
            'to': orcamento_to_str,
        },
        orcamento_status_labels=ORCAMENTO_STATUS_LABELS,
        orcamento_status_styles=ORCAMENTO_STATUS_STYLES,
        orcamento_payment_status_labels=ORCAMENTO_PAYMENT_STATUS_LABELS,
        orcamento_payment_status_styles=ORCAMENTO_PAYMENT_STATUS_STYLES,
        orcamento_status_counts=orcamento_status_counts,
        orcamento_summary=orcamento_summary,
        orcamento_nfse_snapshots=orcamento_nfse_snapshots,
        orcamento_fiscal_summary=orcamento_fiscal_summary,
        pode_editar=pode_editar,
        animais_adicionados=animais_adicionados,
        tutores_adicionados=tutores_adicionados,
        pagination=None,
        start=start_str,
        end=end_str,
        appointment_filters=appointment_filters,
        appointment_vet_options=appointment_vet_options,
        appointment_status_options=appointment_status_options,
        appointment_type_options=appointment_type_options,
        appointment_quick_ranges=appointment_quick_ranges,
        appointment_status_quick_filters=appointment_status_quick_filters,
        appointment_type_quick_filters=appointment_type_quick_filters,
        appointment_view=appointment_view,
        appointments_events=appointments_events,
        today_str=today_str,
        next7_str=next7_str,
        now=now_dt,
        inventory_items=inventory_items,
        inventory_movements=inventory_movements,
        inventory_form=inventory_form,
        critical_items_count=critical_items_count,
        overstock_items_count=overstock_items_count,
        total_stock_quantity=total_stock_quantity,
        show_inventory=show_inventory,
        clinic_metrics=clinic_metrics,
        show_clinic_metrics=can_view_metrics,
        invites_by_status=invites_by_status,
        invite_status_order=invite_status_order,
        clinic_new_animal_url=clinic_new_animal_url,
        team_user_avatars=team_user_avatars,
    )


@bp.route("/clinica/<int:clinica_id>/convites/<int:invite_id>/cancel", methods=["POST"])
@login_required
def cancel_clinic_invite(clinica_id, invite_id):
    """Cancel a pending clinic invite."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.clinica_id != clinica.id:
        abort(404)

    form = ClinicInviteCancelForm()
    if not form.validate_on_submit():
        abort(400)

    if invite.status != 'pending':
        flash('Somente convites pendentes podem ser cancelados.', 'warning')
    else:
        invite.status = 'cancelled'
        db.session.commit()
        flash('Convite cancelado.', 'success')

    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@bp.route("/clinica/<int:clinica_id>/convites/<int:invite_id>/resend", methods=["POST"])
@login_required
def resend_clinic_invite(clinica_id, invite_id):
    """Resend a declined clinic invite."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not _user_can_manage_clinic(clinica):
        abort(403)

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.clinica_id != clinica.id:
        abort(404)

    form = ClinicInviteResendForm()
    if not form.validate_on_submit():
        abort(400)

    if invite.status != 'declined':
        flash('Apenas convites recusados podem ser reenviados.', 'warning')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    invite.status = 'pending'
    invite.created_at = utcnow()
    db.session.commit()

    vet_user = invite.veterinario.user if invite.veterinario else None
    if _send_clinic_invite_email(clinica, vet_user, current_user):
        flash('Convite reenviado.', 'success')
    else:
        flash('Convite reativado, mas houve um problema ao reenviar o e-mail.', 'warning')

    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@bp.route("/clinica/<int:clinica_id>/veterinario", methods=["POST"])
@login_required
def create_clinic_veterinario(clinica_id):
    """Create a new veterinarian linked to a clinic."""
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    crmv = request.form.get('crmv', '').strip()
    phone = normalize_phone(request.form.get('phone'))

    if not name or not email or not crmv or not phone:
        flash('Nome, e-mail, celular e CRMV são obrigatórios.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if User.query.filter_by(email=email).first():
        flash('E-mail já cadastrado.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if find_users_by_phone(phone):
        flash('Celular já cadastrado em outra conta.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    if Veterinario.query.filter_by(crmv=crmv).first():
        flash('CRMV já cadastrado.', 'danger')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')

    user = User(
        name=name,
        email=email,
        phone=phone,
        worker='veterinario',
        is_private=True,
        added_by=current_user,
    )
    # Senha provisória inacessível: o acesso real é criado pelo próprio vet
    # através do link de primeiro acesso enviado abaixo.
    user.set_password(uuid.uuid4().hex)
    user.clinica_id = clinica.id
    db.session.add(user)

    veterinario = Veterinario(user=user, crmv=crmv, clinica=clinica)
    db.session.add(veterinario)

    db.session.add(ClinicStaff(clinic_id=clinica.id, user=user))
    db.session.commit()

    first_access_link = _first_access_url_for_user(user, _external=True)
    email_enviado = False
    try:
        mail.send(MailMessage(
            subject=f'Seu acesso à {clinica.nome} no PetOrlândia',
            recipients=[email],
            body=(
                f'Olá, {name.split()[0]}!\n\n'
                f'Você foi cadastrado(a) como veterinário(a) da clínica {clinica.nome} no PetOrlândia.\n'
                f'Para criar sua senha e acessar a plataforma, use este link:\n{first_access_link}\n\n'
                'Abraços,\nEquipe PetOrlândia'
            ),
        ))
        email_enviado = True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning('Falha ao enviar primeiro acesso do veterinário %s: %s', email, exc)

    if email_enviado:
        flash('Veterinário cadastrado. Enviamos por e-mail o link para ele criar a senha.', 'success')
    else:
        flash(
            'Veterinário cadastrado, mas o e-mail não pôde ser enviado. '
            f'Envie a ele este link de primeiro acesso: {first_access_link}',
            'warning',
        )
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#veterinarios')


@bp.route("/convites/clinica", methods=["GET", "POST"])
@login_required
def clinic_invites():
    """List pending clinic invitations for the logged veterinarian."""
    from models import Veterinario

    if getattr(current_user, "worker", None) != "veterinario":
        abort(403)

    response_form = ClinicInviteResponseForm()
    profile_form = VeterinarianProfileForm()

    vet_profile = getattr(current_user, "veterinario", None)
    anchor_redirect = redirect(url_for('mensagens', _anchor='convites-clinica'))

    if request.method == 'GET':
        return anchor_redirect

    if vet_profile is None:
        if profile_form.validate_on_submit():
            crmv = profile_form.crmv.data
            existing = (
                Veterinario.query.filter(
                    func.lower(Veterinario.crmv) == crmv.lower(),
                    Veterinario.user_id != current_user.id,
                ).first()
            )
            if existing:
                profile_form.crmv.errors.append('Este CRMV já está cadastrado.')
            else:
                vet = Veterinario(user=current_user, crmv=crmv)
                phone = profile_form.phone.data
                if phone:
                    current_user.phone = phone
                db.session.add(vet)
                db.session.commit()
                flash('Cadastro de veterinário concluído com sucesso!', 'success')
                return anchor_redirect
        return _render_messages_page(
            clinic_invite_form=response_form,
            vet_profile_form=profile_form,
            missing_vet_profile=True,
        )

    return anchor_redirect


@bp.route("/convites/<int:invite_id>/<string:action>", methods=["POST"])
@login_required
def respond_clinic_invite(invite_id, action):
    """Accept or decline a clinic invitation."""
    from models import VetClinicInvite

    vet_profile, response = _ensure_veterinarian_profile()
    if response is not None:
        return response

    invite = VetClinicInvite.query.get_or_404(invite_id)
    if invite.veterinario_id != vet_profile.id:
        abort(403)
    if action == 'accept':
        invite.status = 'accepted'
        vet = invite.veterinario
        vet.clinica_id = invite.clinica_id
        if vet.user:
            vet.user.clinica_id = invite.clinica_id
            staff = ClinicStaff.query.filter_by(
                clinic_id=invite.clinica_id, user_id=vet.user.id
            ).first()
            if not staff:
                db.session.add(ClinicStaff(clinic_id=invite.clinica_id, user_id=vet.user.id))
        flash('Convite aceito.', 'success')
    else:
        invite.status = 'declined'
        flash('Convite recusado.', 'info')
    db.session.commit()
    return redirect(url_for('clinic_invites'))


@bp.route("/clinica/<int:clinica_id>/estoque", methods=["GET", "POST"])
@login_required
def clinic_stock(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_perm = staff.can_manage_inventory if staff else False
    if not (_is_admin() or is_owner or has_perm):
        abort(403)

    inventory_form = InventoryItemForm()
    _ensure_inventory_threshold_columns()
    _ensure_inventory_movement_table()
    _ensure_inventory_movement_columns()
    if inventory_form.validate_on_submit():
        min_qty = inventory_form.min_quantity.data
        max_qty = inventory_form.max_quantity.data
        item = ClinicInventoryItem(
            clinica_id=clinica.id,
            name=inventory_form.name.data,
            quantity=inventory_form.quantity.data,
            unit=inventory_form.unit.data,
            min_quantity=min_qty,
            max_quantity=max_qty,
        )
        db.session.add(item)
        if item.quantity:
            db.session.add(
                ClinicInventoryMovement(
                    clinica_id=clinica.id,
                    item=item,
                    quantity_change=item.quantity,
                    quantity_before=0,
                    quantity_after=item.quantity,
                )
            )
        db.session.commit()
        flash('Item adicionado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')

    inventory_items = (
        ClinicInventoryItem.query
        .filter_by(clinica_id=clinica.id)
        .order_by(ClinicInventoryItem.name)
        .all()
    )

    critical_items_count = 0
    overstock_items_count = 0
    total_stock_quantity = 0
    for item in inventory_items:
        qty = item.quantity or 0
        total_stock_quantity += qty
        if item.min_quantity is not None and qty < item.min_quantity:
            critical_items_count += 1
        if item.max_quantity is not None and qty > item.max_quantity:
            overstock_items_count += 1
    inventory_movements = (
        ClinicInventoryMovement.query
        .filter_by(clinica_id=clinica.id)
        .order_by(ClinicInventoryMovement.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        'clinica/clinic_stock.html',
        clinica=clinica,
        inventory_items=inventory_items,
        inventory_movements=inventory_movements,
        inventory_form=inventory_form,
        critical_items_count=critical_items_count,
        overstock_items_count=overstock_items_count,
        total_stock_quantity=total_stock_quantity,
    )


@bp.route("/estoque/item/<int:item_id>/atualizar", methods=["POST"])
@login_required
def update_inventory_item(item_id):
    item = ClinicInventoryItem.query.get_or_404(item_id)
    clinica = item.clinica
    is_owner = current_user.id == clinica.owner_id if current_user.is_authenticated else False
    staff = None
    if current_user.is_authenticated:
        staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=current_user.id).first()
    has_perm = staff.can_manage_inventory if staff else False
    if not (_is_admin() or is_owner or has_perm):
        abort(403)
    def _optional_nonnegative_int(value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None

    wants_json = 'application/json' in request.headers.get('Accept', '')

    old_quantity = item.quantity
    qty = _optional_nonnegative_int(request.form.get('quantity'))
    if qty is None:
        qty = old_quantity
    item.quantity = qty

    new_min = _optional_nonnegative_int(request.form.get('min_quantity'))
    new_max = _optional_nonnegative_int(request.form.get('max_quantity'))

    if new_min is not None and new_max is not None and new_min > new_max:
        message = 'O máximo deve ser maior ou igual ao mínimo.'
        category = 'warning'
        flash(message, category)
        if wants_json:
            return jsonify(success=False, message=message, category=category), 400
        return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')

    item.min_quantity = new_min
    item.max_quantity = new_max

    if item.quantity != old_quantity:
        db.session.add(
            ClinicInventoryMovement(
                clinica_id=clinica.id,
                item=item,
                quantity_change=item.quantity - old_quantity,
                quantity_before=old_quantity,
                quantity_after=item.quantity,
            )
        )

    db.session.commit()
    message = 'Item atualizado.'
    flash(message, 'success')
    if wants_json:
        return jsonify(success=True, message=message, category='success', quantity=item.quantity)
    return redirect(url_for('clinic_detail', clinica_id=clinica.id) + '#estoque')


@bp.route("/clinica/<int:clinica_id>/loja/produtos", methods=["GET", "POST"])
@login_required
def clinic_loja_produtos(clinica_id):
    clinica, _ = _clinic_loja_access(clinica_id)

    inventory_items = (
        ClinicInventoryItem.query
        .filter_by(clinica_id=clinica.id)
        .order_by(ClinicInventoryItem.name)
        .all()
    )

    form = ClinicProductForm()
    choices = [(0, '— Criar novo item de estoque —')] + [
        (it.id, f"{it.name} ({it.quantity} {it.unit or 'un.'})") for it in inventory_items
    ]
    form.inventory_item_id.choices = choices

    if form.validate_on_submit():
        inv_item_id = form.inventory_item_id.data or 0

        if inv_item_id == 0:
            # Cria item de estoque junto com o produto
            qty = form.quantity.data or 0
            inv_item = ClinicInventoryItem(
                clinica_id=clinica.id,
                name=form.name.data,
                quantity=qty,
                unit=form.unit.data or None,
            )
            db.session.add(inv_item)
            db.session.flush()
            if qty > 0:
                db.session.add(ClinicInventoryMovement(
                    clinica_id=clinica.id,
                    item=inv_item,
                    quantity_change=qty,
                    quantity_before=0,
                    quantity_after=qty,
                ))
        else:
            inv_item = ClinicInventoryItem.query.get_or_404(inv_item_id)
            if inv_item.clinica_id != clinica.id:
                abort(403)

        image_url = None
        if form.image_upload.data:
            file = form.image_upload.data
            image_url = upload_to_s3(file, secure_filename(file.filename), folder='products')

        product = Product(
            clinica_id=clinica.id,
            clinic_inventory_item_id=inv_item.id,
            name=form.name.data,
            description=form.description.data or None,
            price=float(form.price.data),
            stock=inv_item.quantity,
            image_url=image_url,
            category=(form.category.data or None),
            mp_category_id=(form.mp_category_id.data or 'others').strip(),
            status='active',
        )
        db.session.add(product)
        db.session.commit()
        flash('Produto publicado na loja com sucesso!', 'success')
        return redirect(url_for('clinic_loja_produtos', clinica_id=clinica.id))

    produtos = Product.query.filter_by(clinica_id=clinica.id).order_by(Product.name).all()
    return render_template(
        'clinica/clinic_loja.html',
        clinica=clinica,
        produtos=produtos,
        form=form,
    )


@bp.route("/clinica/<int:clinica_id>/loja/produto/<int:product_id>/editar", methods=["GET", "POST"])
@login_required
def clinic_produto_editar(clinica_id, product_id):
    clinica, _ = _clinic_loja_access(clinica_id)
    product = Product.query.filter_by(id=product_id, clinica_id=clinica.id).first_or_404()

    form = ClinicProductEditForm(obj=product)
    if form.validate_on_submit():
        product.name = form.name.data
        product.description = form.description.data or None
        product.price = float(form.price.data)
        product.category = form.category.data or None
        product.mp_category_id = (form.mp_category_id.data or 'others').strip()
        if form.image_upload.data:
            file = form.image_upload.data
            url = upload_to_s3(file, secure_filename(file.filename), folder='products')
            if url:
                product.image_url = url
        db.session.commit()
        flash('Produto atualizado.', 'success')
        return redirect(url_for('clinic_loja_produtos', clinica_id=clinica.id))

    return render_template(
        'clinica/clinic_produto_editar.html',
        clinica=clinica,
        product=product,
        form=form,
    )


@bp.route("/clinica/<int:clinica_id>/loja/produto/<int:product_id>/toggle", methods=["POST"])
@login_required
def clinic_produto_toggle(clinica_id, product_id):
    clinica, _ = _clinic_loja_access(clinica_id)
    product = Product.query.filter_by(id=product_id, clinica_id=clinica.id).first_or_404()
    product.status = 'inactive' if product.status == 'active' else 'active'
    db.session.commit()
    state = 'ativado' if product.status == 'active' else 'desativado'
    flash(f'Produto {state} na loja.', 'success')
    return redirect(url_for('clinic_loja_produtos', clinica_id=clinica.id))


@bp.route("/estoque/item/<int:item_id>/publicar", methods=["POST"])
@login_required
def publish_inventory_to_loja(item_id):
    """Publica um item de estoque existente como produto na loja."""
    item = ClinicInventoryItem.query.get_or_404(item_id)
    clinica = item.clinica
    _, _ = _clinic_loja_access(clinica.id)

    if item.produto_loja:
        flash('Este item já está publicado na loja.', 'warning')
        return redirect(url_for('clinic_loja_produtos', clinica_id=clinica.id))

    price_raw = request.form.get('price', '0').replace(',', '.')
    try:
        price = float(price_raw)
    except ValueError:
        price = 0.0

    if price <= 0:
        flash('Informe um preço válido para publicar na loja.', 'danger')
        return redirect(url_for('clinic_stock', clinica_id=clinica.id))

    product = Product(
        clinica_id=clinica.id,
        clinic_inventory_item_id=item.id,
        name=item.name,
        price=price,
        stock=item.quantity,
        mp_category_id='others',
        status='active',
    )
    db.session.add(product)
    db.session.commit()
    flash(f'"{item.name}" publicado na loja com sucesso!', 'success')
    return redirect(url_for('clinic_loja_produtos', clinica_id=clinica.id))


@bp.route("/clinica/<int:clinica_id>/novo_orcamento", methods=["GET", "POST"])
@login_required
def novo_orcamento(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    ensure_clinic_access(clinica.id)
    form = OrcamentoForm()
    if request.method == 'GET':
        form.clinica_id.data = str(clinica_id)
    if form.validate_on_submit():
        form_clinic_id = _coerce_int(form.clinica_id.data)
        if form_clinic_id is None:
            abort(400)
        ensure_clinic_access(form_clinic_id)
        if form_clinic_id != clinica.id:
            abort(400)
        item_payloads, item_rows, item_errors = _extract_orcamento_item_payloads(form_clinic_id)
        selected_status = (request.form.get('status') or 'draft').strip()
        if selected_status not in ORCAMENTO_STATUS_LABELS:
            selected_status = 'draft'
        if item_errors:
            for error in item_errors:
                flash(error, 'warning')
            return _render_orcamento_form(
                form,
                clinica,
                item_rows=item_rows,
                selected_status=selected_status,
                errors=item_errors,
            )
        o = Orcamento(
            clinica_id=form_clinic_id,
            descricao=form.descricao.data,
            status=selected_status,
        )
        db.session.add(o)
        db.session.flush()
        for payload in item_payloads:
            db.session.add(
                OrcamentoItem(
                    orcamento_id=o.id,
                    clinica_id=form_clinic_id,
                    **payload,
                )
            )
        db.session.commit()
        flash('Orçamento criado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=form_clinic_id) + '#orcamento')
    if request.method == 'POST':
        return _render_orcamento_form(
            form,
            clinica,
            item_rows=_orcamento_form_item_rows_from_request(),
            selected_status=request.form.get('status') or 'draft',
        )
    return _render_orcamento_form(form, clinica)


@bp.route("/orcamento/<int:orcamento_id>/editar", methods=["GET", "POST"])
@login_required
def editar_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    ensure_clinic_access(orcamento.clinica_id)
    form = OrcamentoForm(obj=orcamento)
    if request.method == 'GET':
        form.clinica_id.data = str(orcamento.clinica_id)
    if form.validate_on_submit():
        form_clinic_id = _coerce_int(form.clinica_id.data)
        if form_clinic_id is None:
            abort(400)
        ensure_clinic_access(form_clinic_id)
        if form_clinic_id != orcamento.clinica_id:
            abort(400)
        item_rows = _orcamento_form_item_rows_from_model(orcamento)
        can_edit_items = not any(row.get('locked') for row in item_rows)
        item_payloads = []
        submitted_items = _orcamento_submitted_item_fields_present()
        if can_edit_items and submitted_items:
            item_payloads, submitted_rows, item_errors = _extract_orcamento_item_payloads(form_clinic_id)
            item_rows = submitted_rows
            if item_errors:
                for error in item_errors:
                    flash(error, 'warning')
                return _render_orcamento_form(
                    form,
                    orcamento.clinica,
                    orcamento=orcamento,
                    item_rows=item_rows,
                    selected_status=request.form.get('status') or orcamento.status,
                    errors=item_errors,
                )
        orcamento.descricao = form.descricao.data
        selected_status = (request.form.get('status') or orcamento.status or 'draft').strip()
        if selected_status in ORCAMENTO_STATUS_LABELS:
            orcamento.status = selected_status
        if can_edit_items and submitted_items:
            for item in list(orcamento.items):
                db.session.delete(item)
            db.session.flush()
            for payload in item_payloads:
                db.session.add(
                    OrcamentoItem(
                        orcamento_id=orcamento.id,
                        consulta_id=orcamento.consulta_id,
                        clinica_id=form_clinic_id,
                        **payload,
                    )
                )
        db.session.commit()
        flash('Orçamento atualizado com sucesso.', 'success')
        return redirect(url_for('clinic_detail', clinica_id=orcamento.clinica_id) + '#orcamento')
    if request.method == 'POST':
        return _render_orcamento_form(
            form,
            orcamento.clinica,
            orcamento=orcamento,
            item_rows=_orcamento_form_item_rows_from_request(),
            selected_status=request.form.get('status') or orcamento.status,
        )
    return _render_orcamento_form(form, orcamento.clinica, orcamento=orcamento)


@bp.route("/orcamento/<int:orcamento_id>/enviar", methods=["POST"])
@login_required
def enviar_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    ensure_clinic_access(orcamento.clinica_id)

    channel = (request.form.get('channel') or '').lower()
    if channel not in {'email', 'whatsapp'}:
        abort(400)

    redirect_url = request.referrer or url_for('clinic_detail', clinica_id=orcamento.clinica_id) + '#orcamento'
    consulta = orcamento.consulta
    tutor = consulta.animal.owner if consulta else None
    if not tutor:
        flash('O orçamento precisa estar vinculado a uma consulta para envio automático.', 'warning')
        return redirect(redirect_url)

    link = url_for('imprimir_orcamento', consulta_id=consulta.id, _external=True)
    animal = consulta.animal
    tutor_nome = getattr(tutor, 'name', 'tutor')
    animal_nome = getattr(animal, 'name', 'pet')
    mensagem = f"Olá {tutor_nome}! Segue o orçamento para {animal_nome}: {link}"
    if orcamento.payment_link:
        mensagem += f"\n\nPagamento online: {orcamento.payment_link}"

    if channel == 'email':
        if not tutor.email:
            flash('O tutor não possui e-mail cadastrado.', 'warning')
            return redirect(redirect_url)
        msg = MailMessage(
            subject=f'Orçamento para {animal_nome}',
            sender=current_app.config['MAIL_DEFAULT_SENDER'],
            recipients=[tutor.email],
            body=mensagem,
        )
        try:
            mail.send(msg)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception('Falha ao enviar orçamento por e-mail: %s', exc)
            flash('Não foi possível enviar o e-mail. Tente novamente.', 'danger')
            return redirect(redirect_url)
        orcamento.email_sent_count = (orcamento.email_sent_count or 0) + 1
    else:
        if not tutor.phone:
            flash('O tutor não possui telefone cadastrado.', 'warning')
            return redirect(redirect_url)
        numero = f"whatsapp:{formatar_telefone(tutor.phone)}"
        try:
            enviar_mensagem_whatsapp(mensagem, numero)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception('Falha ao enviar orçamento por WhatsApp: %s', exc)
            flash('Não foi possível enviar via WhatsApp. Verifique as credenciais do Twilio.', 'danger')
            return redirect(redirect_url)
        orcamento.whatsapp_sent_count = (orcamento.whatsapp_sent_count or 0) + 1

    if orcamento.status == 'draft':
        orcamento.status = 'sent'
    db.session.add(orcamento)
    db.session.commit()
    flash('Orçamento enviado com sucesso!', 'success')
    return redirect(redirect_url)


@bp.route("/orcamento/<int:orcamento_id>/status", methods=["PATCH"])
@login_required
def atualizar_status_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    try:
        ensure_clinic_access(orcamento.clinica_id)
    except NotFound:
        abort(403)

    payload = request.get_json(silent=True) or {}
    new_status = payload.get('status')
    if new_status is None:
        new_status = request.form.get('status')
    new_status = (new_status or '').strip()
    wants_json = 'application/json' in request.headers.get('Accept', '')

    if new_status not in ORCAMENTO_STATUS_LABELS:
        message = 'Status inválido.'
        if wants_json:
            return jsonify(success=False, message=message), 400
        flash(message, 'danger')
        return redirect(request.referrer or url_for('clinic_detail', clinica_id=orcamento.clinica_id) + '#orcamento')

    previous_status = orcamento.status
    draft_message = None
    if orcamento.status != new_status:
        orcamento.status = new_status
        orcamento.updated_at = utcnow()
        db.session.add(orcamento)
        db.session.commit()
        if new_status == "approved" and previous_status != "approved":
            try:
                create_nfse_draft_from_orcamento(orcamento.id)
                draft_message = "Documento fiscal em rascunho criado."
            except ValueError as exc:
                current_app.logger.warning(
                    "Não foi possível criar documento fiscal para orçamento %s: %s",
                    orcamento.id,
                    exc,
                )
                draft_message = str(exc)
    else:
        db.session.commit()

    message = 'Status atualizado com sucesso.'
    if draft_message:
        message = f"{message} {draft_message}"
    response_payload = {
        'success': True,
        'message': message,
        'status': orcamento.status,
        'status_label': ORCAMENTO_STATUS_LABELS.get(orcamento.status, orcamento.status),
        'status_style': ORCAMENTO_STATUS_STYLES.get(orcamento.status, 'secondary'),
        'updated_at': (orcamento.updated_at or utcnow()).isoformat() + 'Z',
    }

    if wants_json:
        return jsonify(response_payload)

    flash(message, 'success')
    return redirect(request.referrer or url_for('clinic_detail', clinica_id=orcamento.clinica_id) + '#orcamento')


@bp.route("/clinica/<int:clinica_id>/orcamentos", methods=["GET"])
@login_required
def orcamentos(clinica_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if current_user.clinica_id != clinica_id and not _is_admin():
        abort(403)
    lista = Orcamento.query.filter_by(clinica_id=clinica_id).all()
    selected_month = _parse_month_parameter(request.args.get('mes'))
    month_value = selected_month.strftime('%Y-%m')
    contabilidade_url = None
    if _user_can_access_accounting():
        contabilidade_url = url_for(
            'contabilidade_pagamentos',
            clinica_id=clinica_id,
            mes=month_value,
        )
    return render_template(
        'orcamentos/orcamentos.html',
        clinica=clinica,
        orcamentos=lista,
        contabilidade_pagamentos_url=contabilidade_url,
    )


@bp.route("/dashboard/orcamentos", methods=["GET"])
@login_required
def dashboard_orcamentos():
    from collections import defaultdict
    from admin import _is_admin
    from models import (
        Animal,
        Clinica,
        Consulta,
        Orcamento,
        Payment,
        PaymentStatus,
    )

    is_admin = _is_admin()
    requested_scope = request.args.get('scope', 'clinic')
    requested_clinic_id = request.args.get('clinica_id', type=int)

    if requested_scope == 'all' and not is_admin:
        abort(403)

    accessible_clinic_ids = _collect_clinic_ids()
    default_clinic_id = current_user_clinic_id()

    selected_clinic_id = None
    is_global_scope = False

    if is_admin:
        if requested_scope == 'all':
            is_global_scope = True
        elif requested_clinic_id:
            selected_clinic_id = requested_clinic_id
        elif default_clinic_id:
            selected_clinic_id = default_clinic_id
        else:
            is_global_scope = True
    else:
        if requested_clinic_id and requested_clinic_id not in accessible_clinic_ids:
            abort(403)
        selected_clinic_id = requested_clinic_id or default_clinic_id
        if not selected_clinic_id and accessible_clinic_ids:
            selected_clinic_id = sorted(accessible_clinic_ids)[0]
        if not selected_clinic_id:
            abort(403)

    consulta_query = (
        Consulta.query.options(
            joinedload(Consulta.animal).joinedload(Animal.owner),
        )
        .filter(Consulta.orcamento_items.any())
    )
    if not is_global_scope:
        consulta_query = consulta_query.filter(Consulta.clinica_id == selected_clinic_id)
    consultas = consulta_query.all()

    consulta_refs = {f'consulta-{consulta.id}' for consulta in consultas}
    pagamentos_concluidos = {}
    if consulta_refs:
        pagamentos_concluidos = {
            pagamento.external_reference: pagamento
            for pagamento in Payment.query.filter(
                Payment.external_reference.in_(consulta_refs),
                Payment.status == PaymentStatus.COMPLETED,
            )
        }

    dados_consultas = []
    total_por_cliente = defaultdict(lambda: {'total': 0.0, 'pagos': 0.0, 'pendentes': 0.0})
    total_por_animal = defaultdict(lambda: {'total': 0.0, 'pagos': 0.0, 'pendentes': 0.0})

    for consulta in consultas:
        cliente_nome = (
            consulta.animal.owner.name
            if consulta.animal and consulta.animal.owner
            else 'N/A'
        )
        animal_nome = consulta.animal.name if consulta.animal else 'N/A'
        total = float(consulta.total_orcamento or 0)
        pago = pagamentos_concluidos.get(f'consulta-{consulta.id}') is not None
        status = 'Pago' if pago else 'Pendente'

        dados_consultas.append(
            {
                'cliente': cliente_nome,
                'animal': animal_nome,
                'total': total,
                'status': status,
            }
        )

        total_por_cliente[cliente_nome]['total'] += total
        total_por_animal[animal_nome]['total'] += total
        if pago:
            total_por_cliente[cliente_nome]['pagos'] += total
            total_por_animal[animal_nome]['pagos'] += total
        else:
            total_por_cliente[cliente_nome]['pendentes'] += total
            total_por_animal[animal_nome]['pendentes'] += total

    orcamento_query = Orcamento.query.options(joinedload(Orcamento.clinica))
    if not is_global_scope:
        orcamento_query = orcamento_query.filter(Orcamento.clinica_id == selected_clinic_id)
    dados_orcamentos = [
        {
            'descricao': o.descricao,
            'total': float(o.total or 0),
            'clinica': o.clinica.nome if o.clinica else 'N/A',
        }
        for o in orcamento_query.all()
    ]

    total_emitido = sum(orcamento['total'] for orcamento in dados_orcamentos)
    total_aprovado = sum(
        consulta['total'] for consulta in dados_consultas if consulta['status'] == 'Pago'
    )
    total_pendente = sum(
        consulta['total'] for consulta in dados_consultas if consulta['status'] != 'Pago'
    )

    clinic_options = []
    if is_admin:
        clinic_options = Clinica.query.order_by(Clinica.nome).all()
    elif accessible_clinic_ids:
        clinic_options = (
            Clinica.query.filter(Clinica.id.in_(accessible_clinic_ids))
            .order_by(Clinica.nome)
            .all()
        )

    selected_clinic = (
        Clinica.query.get(selected_clinic_id) if selected_clinic_id else None
    )

    reference_month = _parse_month_parameter(request.args.get('mes'))
    reference_month_value = reference_month.strftime('%Y-%m')
    contabilidade_url = None
    if selected_clinic_id and _user_can_access_accounting():
        contabilidade_url = url_for(
            'contabilidade_pagamentos',
            clinica_id=selected_clinic_id,
            mes=reference_month_value,
        )

    return render_template(
        'orcamentos/dashboard_orcamentos.html',
        consultas=dados_consultas,
        clientes=total_por_cliente,
        animais=total_por_animal,
        orcamentos=dados_orcamentos,
        is_admin=is_admin,
        clinic_options=clinic_options,
        selected_clinic=selected_clinic,
        selected_clinic_id=selected_clinic_id,
        selected_scope='all' if is_global_scope else 'clinic',
        is_global_scope=is_global_scope,
        total_emitido=total_emitido,
        total_aprovado=total_aprovado,
        total_pendente=total_pendente,
        contabilidade_pagamentos_url=contabilidade_url,
    )


@bp.route("/clinica/<int:clinica_id>/dashboard", methods=["GET"])
@login_required
def clinic_dashboard(clinica_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id == clinic.owner_id:
        staff = ClinicStaff(
            clinic_id=clinic.id,
            user_id=current_user.id,
            can_manage_clients=True,
            can_manage_animals=True,
            can_manage_staff=True,
            can_manage_schedule=True,
            can_manage_inventory=True,
        )
    else:
        staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=current_user.id).first()
        if not staff:
            abort(403)
    return render_template('clinica/clinic_dashboard.html', clinic=clinic, staff=staff)


@bp.route("/clinica/<int:clinica_id>/funcionarios", methods=["GET", "POST"])
@login_required
def clinic_staff(clinica_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id != clinic.owner_id:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Sem permissão'), 403
        abort(403)
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if not user:
            if request.accept_mimetypes.accept_json:
                return jsonify(success=False, message='Usuário não encontrado'), 404
            flash('Usuário não encontrado', 'danger')
        else:
            staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=user.id).first()
            if staff:
                if request.accept_mimetypes.accept_json:
                    return jsonify(success=False, message='Funcionário já está na clínica'), 400
                flash('Funcionário já está na clínica', 'warning')
            else:
                staff = ClinicStaff(clinic_id=clinic.id, user_id=user.id)
                db.session.add(staff)
                user.clinica_id = clinic.id
                if has_veterinarian_profile(user):
                    vet_profile = user.veterinario
                    vet_profile.clinica_id = clinic.id
                    # Garanta que o veterinário tenha uma assinatura ou período
                    # de testes ativo para acessar as agendas da clínica.
                    ensure_veterinarian_membership(vet_profile)
                    db.session.add(vet_profile)
                elif getattr(user, "worker", None) is None:
                    # Garanta que colaboradores recém-adicionados apareçam nas visões
                    # de agenda que dependem do papel ``colaborador``.
                    user.worker = "colaborador"
                db.session.add(user)
                db.session.commit()
                if request.accept_mimetypes.accept_json:
                    staff_members = ClinicStaff.query.filter_by(clinic_id=clinic.id).all()
                    staff_permission_forms = {}
                    for staff_member in staff_members:
                        staff_permission_forms[staff_member.user.id] = ClinicStaffPermissionForm(
                            prefix=f"perm_{staff_member.user.id}", obj=staff_member
                        )
                    html = render_template(
                        'partials/clinic_staff_rows.html',
                        clinic=clinic,
                        staff_members=staff_members,
                        staff_permission_forms=staff_permission_forms,
                    )
                    return jsonify(success=True, html=html, message='Funcionário adicionado', category='success')
                flash('Funcionário adicionado. Defina as permissões.', 'success')
                return redirect(url_for('clinic_staff_permissions', clinica_id=clinic.id, user_id=user.id))
    staff_members = ClinicStaff.query.filter_by(clinic_id=clinic.id).all()
    staff_permission_forms = {}
    for s in staff_members:
        staff_permission_forms[s.user.id] = ClinicStaffPermissionForm(
            prefix=f"perm_{s.user.id}", obj=s
        )
    if request.accept_mimetypes.accept_json:
        html = render_template(
            'partials/clinic_staff_rows.html',
            clinic=clinic,
            staff_members=staff_members,
            staff_permission_forms=staff_permission_forms,
        )
        return jsonify(success=True, html=html)
    return render_template(
        'clinica/clinic_staff_list.html',
        clinic=clinic,
        staff_members=staff_members,
        staff_permission_forms=staff_permission_forms,
    )


@bp.route("/clinica/<int:clinica_id>/funcionario/<int:user_id>/permissoes", methods=["GET", "POST"])
@login_required
def clinic_staff_permissions(clinica_id, user_id):
    clinic = Clinica.query.get_or_404(clinica_id)
    if current_user.id != clinic.owner_id:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Sem permissão'), 403
        abort(403)
    user = User.query.get(user_id)
    if not user:
        if request.accept_mimetypes.accept_json:
            return jsonify(success=False, message='Usuário não encontrado'), 404
        abort(404)
    staff = ClinicStaff.query.filter_by(clinic_id=clinic.id, user_id=user_id).first()
    if not staff:
        staff = ClinicStaff(clinic_id=clinic.id, user_id=user_id)
    form = ClinicStaffPermissionForm(obj=staff)
    if form.validate_on_submit():
        form.populate_obj(staff)
        staff.user_id = user_id
        db.session.add(staff)
        user.clinica_id = clinic.id
        db.session.add(user)
        db.session.commit()
        if request.accept_mimetypes.accept_json:
            html = render_template('partials/clinic_staff_permissions_form.html', form=form, clinic=clinic)
            return jsonify(success=True, html=html, message='Permissões atualizadas', category='success')
        flash('Permissões atualizadas', 'success')
        return redirect(url_for('clinic_dashboard', clinica_id=clinic.id))
    if request.accept_mimetypes.accept_json:
        html = render_template('partials/clinic_staff_permissions_form.html', form=form, clinic=clinic)
        return jsonify(success=True, html=html)
    return render_template('clinica/clinic_staff_permissions.html', form=form, clinic=clinic)


@bp.route("/clinica/<int:clinica_id>/funcionario/<int:user_id>/remove", methods=["POST"])
@login_required
def remove_funcionario(clinica_id, user_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    staff = ClinicStaff.query.filter_by(clinic_id=clinica_id, user_id=user_id).first_or_404()
    db.session.delete(staff)
    user = User.query.get(user_id)
    if user and user.clinica_id == clinica_id:
        user.clinica_id = None
        if has_veterinarian_profile(user):
            user.veterinario.clinica_id = None
            db.session.add(user.veterinario)
        db.session.add(user)
    db.session.commit()
    flash('Funcionário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@bp.route("/clinica/<int:clinica_id>/horario/<int:horario_id>/delete", methods=["POST"])
@login_required
def delete_clinic_hour(clinica_id, horario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    pode_editar = _is_admin() or (
        is_veterinarian(current_user)
        and current_user.veterinario.clinica_id == clinica_id
    ) or current_user.id == clinica.owner_id
    if not pode_editar:
        abort(403)
    horario = ClinicHours.query.filter_by(id=horario_id, clinica_id=clinica_id).first_or_404()
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@bp.route("/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/remove", methods=["POST"])
@login_required
def remove_veterinario(clinica_id, veterinario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    vet = Veterinario.query.filter_by(id=veterinario_id, clinica_id=clinica_id).first_or_404()
    vet.clinica_id = None
    if vet.user:
        # Remove clinic association and staff permissions for this user
        vet.user.clinica_id = None
        ClinicStaff.query.filter_by(
            clinic_id=clinica_id, user_id=vet.user.id
        ).delete()
    db.session.commit()
    flash('Funcionário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))


@bp.route("/clinica/<int:clinica_id>/especialista/<int:veterinario_id>/remove", methods=["POST"])
@login_required
def remove_specialist(clinica_id, veterinario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    vet = Veterinario.query.get_or_404(veterinario_id)
    if vet not in clinica.veterinarios_associados:
        abort(404)
    clinica.veterinarios_associados.remove(vet)
    staff = ClinicStaff.query.filter_by(clinic_id=clinica.id, user_id=vet.user_id).first()
    if staff and vet.clinica_id != clinica.id:
        db.session.delete(staff)
    db.session.commit()
    flash('Especialista removido da clínica.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id) + '#especialistas')


@bp.route("/clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/schedule/<int:horario_id>/delete", methods=["POST"])
@login_required
def delete_vet_schedule_clinic(clinica_id, veterinario_id, horario_id):
    clinica = Clinica.query.get_or_404(clinica_id)
    if not (_is_admin() or current_user.id == clinica.owner_id):
        abort(403)
    horario = VetSchedule.query.get_or_404(horario_id)
    vet = horario.veterinario
    if vet.id != veterinario_id:
        abort(404)
    if vet.clinica_id != clinica_id and vet not in clinica.veterinarios_associados:
        abort(404)
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('clinic_detail', clinica_id=clinica_id))

