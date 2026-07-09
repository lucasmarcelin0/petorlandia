"""Agendamentos, agenda de veterinários e exames — views do domínio.

``_is_admin`` e ``is_veterinarian`` são late-bound via módulo app (testes
fazem monkeypatch desses nomes — contrato do antigo lazy_view).
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import case, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from context_processors import _invalidate_cached_context
from extensions import db
from forms import AppointmentDeleteForm, AppointmentForm, VetScheduleForm, VetSpecialtyForm
from helpers import (
    get_appointment_duration,
    get_available_times,
    group_appointments_by_day,
    has_conflict_for_slot,
    has_schedule_conflict,
    is_slot_available,
    to_timezone_aware,
    unique_items_by_id,
)
from models import (
    Animal,
    Appointment,
    Consulta,
    FiscalDocument,
    Specialty,
    Vacina,
    VetSchedule,
    Veterinario,
)
from repositories import AppointmentRepository, ClinicRepository
from services import get_calendar_access_scope
from services.fiscal.nfse_service import (
    build_nfse_payload_from_appointment,
    create_nfse_document,
    queue_emit_nfse,
)
from template_filters import format_datetime_brazil, format_timedelta
from time_utils import BR_TZ, coerce_to_brazil_tz, normalize_to_utc, utcnow

from app import (
    _build_veterinarian_activity_report,
    _can_view_veterinarian_activity_report,
    _export_veterinarian_activity_csv,
    _export_veterinarian_activity_pdf,
    _get_recent_animais,
    _get_recent_tutores,
    _is_bh_consulta_extra_public_profile,
    _is_public_veterinarian,
    _is_robson_santos_public_profile,
    _is_specialist_veterinarian,
    _public_city_key,
    _public_veterinarians_query,
    _render_vet_public_profile,
    _user_is_clinic_professional,
    _vet_all_public_cities,
    _vet_matches_public_city,
    _vet_public_city,
    _vet_public_service_notes,
    _vet_serves_city,
    _veterinarian_accessible_clinic_ids,
    current_user_clinic_id,
    get_animal_or_404,
    list_breeds,
    list_species,
    local_date_range_to_utc,
)

bp = Blueprint("agendamentos_routes", __name__)


def get_blueprint():
    return bp


def _is_admin():
    import app as app_module

    return app_module._is_admin()


def is_veterinarian(*args, **kwargs):
    import app as app_module

    return app_module.is_veterinarian(*args, **kwargs)


@bp.route("/veterinarios", methods=["GET"])
def veterinarios():
    vets = _public_veterinarians_query().all()

    def vet_city(v):
        return _vet_public_city(v)

    cidades_set = {c for v in vets for c in _vet_all_public_cities(v)}
    if any(_is_robson_santos_public_profile(v) for v in vets):
        cidades_set.update({'Belo Horizonte', 'Contagem'})
    if any(_is_bh_consulta_extra_public_profile(v) for v in vets):
        cidades_set.add('Belo Horizonte')
    cidades = sorted(cidades_set)

    user_cidade = None
    if current_user.is_authenticated and getattr(current_user, 'endereco', None):
        user_cidade = (current_user.endereco.cidade or '').strip() or None

    selected = request.args.get('cidade')
    if selected is None:
        # Sem filtro explícito: prioriza a cidade do usuário logado, se houver vets nela.
        matching_user_city = next(
            (city for city in cidades if _public_city_key(city) == _public_city_key(user_cidade)),
            None,
        )
        selected = matching_user_city or ''
    selected = (selected or '').strip()

    if selected:
        filtrados = [v for v in vets if _vet_matches_public_city(v, selected, kind='consulta')]
    else:
        # "Todas as cidades": profissionais que atendem a cidade do usuário primeiro.
        filtrados = sorted(
            vets,
            key=lambda v: (not _vet_serves_city(v, user_cidade), (v.user.name or '').lower()),
        )

    return render_template(
        'veterinarios/veterinarios.html',
        veterinarios=filtrados,
        cidades=cidades,
        selected_cidade=selected,
        user_cidade=user_cidade,
        vet_city=vet_city,
        vet_service_notes=_vet_public_service_notes,
    )


@bp.route("/veterinario/<int:veterinario_id>", methods=["GET"])
def vet_detail(veterinario_id):
    from models import Animal, User  # import local para evitar ciclos

    veterinario = Veterinario.query.get_or_404(veterinario_id)
    has_internal_access = _user_is_clinic_professional(veterinario_id)

    if not _is_public_veterinarian(veterinario) and not has_internal_access:
        abort(404)

    # Privacidade: tutores/visitantes nunca veem a agenda nem dados internos.
    if not has_internal_access:
        return _render_vet_public_profile(veterinario)

    calendar_access_scope = get_calendar_access_scope(current_user)
    horarios = (
        VetSchedule.query.filter_by(veterinario_id=veterinario_id)
        .order_by(VetSchedule.dia_semana, VetSchedule.hora_inicio)
        .all()
    )

    schedule_form = VetScheduleForm(prefix='schedule')
    appointment_form = AppointmentForm(
        is_veterinario=True,
        clinic_ids=[veterinario.clinica_id] if veterinario.clinica_id else None,
        prefix='appointment',
    )
    admin_default_selection_value = ''

    if current_user.is_authenticated and current_user.role == 'admin':
        agenda_veterinarios = (
            Veterinario.query.join(User).order_by(User.name).all()
        )
        agenda_colaboradores = (
            User.query.filter(User.worker == 'colaborador')
            .order_by(User.name)
            .all()
        )
        vet_choices = [(v.id, v.user.name) for v in agenda_veterinarios]
        admin_selected_view = 'veterinario'
        admin_selected_veterinario_id = veterinario.id
        admin_selected_colaborador_id = None
        default_vet = getattr(current_user, 'veterinario', None)
        if default_vet and getattr(default_vet, 'id', None):
            admin_default_selection_value = f'veterinario:{default_vet.id}'
        else:
            admin_default_selection_value = f'veterinario:{veterinario.id}'
    else:
        agenda_veterinarios = []
        agenda_colaboradores = []
        vet_choices = [(veterinario.id, veterinario.user.name)]
        admin_selected_view = None
        admin_selected_veterinario_id = None
        admin_selected_colaborador_id = None

    schedule_form.veterinario_id.choices = vet_choices
    schedule_form.veterinario_id.data = veterinario.id

    appointment_form.veterinario_id.choices = [
        (veterinario.id, veterinario.user.name)
    ]
    appointment_form.veterinario_id.data = veterinario.id

    weekday_order = {
        'Segunda': 0,
        'Terça': 1,
        'Quarta': 2,
        'Quinta': 3,
        'Sexta': 4,
        'Sábado': 5,
        'Domingo': 6,
    }
    horarios.sort(key=lambda h: weekday_order.get(h.dia_semana, 7))
    horarios_grouped = []
    for horario in horarios:
        if not horarios_grouped or horarios_grouped[-1]['dia'] != horario.dia_semana:
            horarios_grouped.append({'dia': horario.dia_semana, 'itens': []})
        horarios_grouped[-1]['itens'].append(horario)

    calendar_redirect_url = url_for(
        'appointments', view_as='veterinario', veterinario_id=veterinario.id
    )
    calendar_summary_vets = []
    calendar_summary_clinic_ids = []

    def build_calendar_summary_entry(vet, *, label=None, is_specialist=None):
        """Return a serializable mapping with vet summary metadata."""
        if not vet:
            return None
        vet_id = getattr(vet, 'id', None)
        if not vet_id:
            return None
        clinic_ids = calendar_access_scope.get_veterinarian_clinic_ids(vet)
        vet_user = getattr(vet, 'user', None)
        vet_name = getattr(vet_user, 'name', None)
        specialty_list = getattr(vet, 'specialty_list', None)
        entry = {
            'id': vet_id,
            'name': label if label is not None else vet_name,
            'full_name': vet_name,
            'specialty_list': specialty_list,
            'clinic_ids': clinic_ids,
        }
        if label is not None:
            entry['label'] = label
        if is_specialist is None:
            is_specialist = bool(specialty_list)
        entry['is_specialist'] = bool(is_specialist)
        return entry

    def add_summary_vet(vet, *, label=None, is_specialist=None):
        if not vet:
            return
        vet_id = getattr(vet, 'id', None)
        if not vet_id:
            return
        if any(entry.get('id') == vet_id for entry in calendar_summary_vets):
            return
        if not calendar_access_scope.allows_veterinarian(vet):
            return
        entry = build_calendar_summary_entry(vet, label=label, is_specialist=is_specialist)
        if entry:
            calendar_summary_vets.append(entry)

    add_summary_vet(veterinario)

    clinic_ids = set()

    primary_clinic_id = getattr(veterinario, 'clinica_id', None)
    if primary_clinic_id:
        clinic_ids.add(primary_clinic_id)

    related_clinics = []
    main_clinic = getattr(veterinario, 'clinica', None)
    if main_clinic is not None:
        related_clinics.append(main_clinic)
    associated_clinics = getattr(veterinario, 'clinicas', None) or []
    related_clinics.extend(clinic for clinic in associated_clinics if clinic)

    for clinic in related_clinics:
        clinic_id = getattr(clinic, 'id', None)
        if clinic_id:
            clinic_ids.add(clinic_id)
        for colleague in getattr(clinic, 'veterinarios', []) or []:
            add_summary_vet(colleague)
        for colleague in getattr(clinic, 'veterinarios_associados', []) or []:
            add_summary_vet(colleague, is_specialist=True)

    if clinic_ids and len(calendar_summary_vets) == 1:
        colleagues = (
            Veterinario.query.filter(Veterinario.clinica_id.in_(clinic_ids)).all()
        )
        for colleague in colleagues:
            add_summary_vet(colleague)

    calendar_summary_clinic_ids = calendar_access_scope.filter_clinic_ids(clinic_ids)
    calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)
    if not calendar_summary_vets:
        add_summary_vet(veterinario)
        calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)

    return render_template(
        'veterinarios/vet_detail.html',
        veterinario=veterinario,
        horarios=horarios,
        horarios_grouped=horarios_grouped,
        calendar_redirect_url=calendar_redirect_url,
        schedule_form=schedule_form,
        appointment_form=appointment_form,
        agenda_veterinarios=agenda_veterinarios,
        agenda_colaboradores=agenda_colaboradores,
        admin_selected_view=admin_selected_view,
        admin_selected_veterinario_id=admin_selected_veterinario_id,
        admin_selected_colaborador_id=admin_selected_colaborador_id,
        admin_default_selection_value=admin_default_selection_value,
        calendar_summary_vets=calendar_summary_vets,
        calendar_summary_clinic_ids=calendar_summary_clinic_ids,
    )


@bp.route("/veterinario/<int:veterinario_id>/relatorio-atividades", methods=["GET"])
@login_required
def veterinarian_activity_report(veterinario_id):
    veterinario = Veterinario.query.options(
        joinedload(Veterinario.user),
        joinedload(Veterinario.clinica),
    ).get_or_404(veterinario_id)

    if not _can_view_veterinarian_activity_report(veterinario):
        abort(403)

    today_local = datetime.now(BR_TZ).date()
    default_start = today_local.replace(day=1)

    try:
        start_date = date.fromisoformat(request.args.get('start_date', default_start.isoformat()))
    except ValueError:
        start_date = default_start
    try:
        end_date = date.fromisoformat(request.args.get('end_date', today_local.isoformat()))
    except ValueError:
        end_date = today_local

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    activities, summary = _build_veterinarian_activity_report(veterinario, start_date, end_date)

    export_format = (request.args.get('format') or '').strip().lower()
    if export_format == 'csv':
        return _export_veterinarian_activity_csv(veterinario, activities, start_date, end_date)
    if export_format == 'pdf':
        return _export_veterinarian_activity_pdf(veterinario, activities, summary, start_date, end_date)

    query_args = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    }
    csv_args = dict(query_args, format='csv')
    pdf_args = dict(query_args, format='pdf')

    return render_template(
        'veterinarios/activity_report.html',
        veterinario=veterinario,
        activities=activities,
        summary=summary,
        filters=query_args,
        csv_args=csv_args,
        pdf_args=pdf_args,
    )


@bp.route("/admin/veterinario/<int:veterinario_id>/especialidades", methods=["GET", "POST"])
@login_required
def edit_vet_specialties(veterinario_id):
    # Apenas o próprio veterinário ou um administrador pode alterar especialidades
    is_owner = (
        is_veterinarian(current_user)
        and current_user.veterinario
        and current_user.veterinario.id == veterinario_id
    )
    if not (_is_admin() or is_owner):
        flash('Apenas o próprio veterinário ou um administrador pode acessar esta página.', 'danger')
        return redirect(url_for('index'))

    veterinario = Veterinario.query.get_or_404(veterinario_id)
    form = VetSpecialtyForm()
    form.specialties.choices = [
        (s.id, s.nome) for s in Specialty.query.order_by(Specialty.nome).all()
    ]
    if form.validate_on_submit():
        veterinario.specialties = Specialty.query.filter(
            Specialty.id.in_(form.specialties.data)
        ).all()
        db.session.commit()
        flash('Especialidades atualizadas com sucesso.', 'success')
        return redirect(url_for('ficha_tutor', tutor_id=veterinario.user_id))
    form.specialties.data = [s.id for s in veterinario.specialties]
    return render_template('agendamentos/edit_vet_specialties.html', form=form, veterinario=veterinario)


@bp.route("/appointments/<int:appointment_id>/confirmation", methods=["GET"])
@login_required
def appointment_confirmation(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.tutor_id != current_user.id:
        abort(403)
    return render_template('agendamentos/appointment_confirmation.html', appointment=appointment)


@bp.route("/appointments", methods=["GET", "POST"])
@login_required
def appointments():
    from models import ExamAppointment, Veterinario, Clinica, User

    view_as = request.args.get('view_as')
    worker = getattr(current_user, 'worker', None)
    is_vet = is_veterinarian(current_user)
    if worker == 'veterinario' and not is_vet:
        worker = 'tutor'
    clinic_repo = ClinicRepository()
    calendar_access_scope = get_calendar_access_scope(current_user, clinic_repo)

    def _redirect_to_current_appointments():
        query_args = request.args.to_dict(flat=False)
        if query_args:
            return redirect(url_for('appointments', **query_args))
        return redirect(url_for('appointments'))
    if view_as:
        allowed_views = {'veterinario', 'colaborador', 'tutor'}
        if current_user.role == 'admin' and view_as in allowed_views:
            worker = view_as
        elif current_user.role != 'admin':
            # Non-admin users can only request the view matching their own role.
            user_view = worker if worker in allowed_views else 'tutor'
            if view_as not in allowed_views or view_as != user_view:
                flash('Você não tem permissão para acessar essa visão de agenda.', 'warning')
                return redirect(url_for('appointments'))

    agenda_users = []
    agenda_veterinarios = []
    agenda_colaboradores = []
    admin_selected_veterinario_id = None
    admin_selected_colaborador_id = None
    admin_default_selection_value = ''
    selected_colaborador = None
    calendar_summary_vets = []
    calendar_summary_clinic_ids = []
    calendar_redirect_url = None

    def _vet_clinic_ids(vet):
        return calendar_access_scope.get_veterinarian_clinic_ids(vet)

    if current_user.role == 'admin':
        agenda_users = User.query.order_by(User.name).all()
        agenda_veterinarios = (
            Veterinario.query.join(User).order_by(User.name).all()
        )
        agenda_colaboradores = (
            User.query.filter(User.worker == 'colaborador')
            .order_by(User.name)
            .all()
        )
        default_vet = getattr(current_user, 'veterinario', None)
        if default_vet and getattr(default_vet, 'id', None):
            admin_default_selection_value = f'veterinario:{default_vet.id}'

    admin_selected_view = (
        worker
        if current_user.role == 'admin' and worker in {'veterinario', 'colaborador'}
        else None
    )

    if request.method == 'POST' and worker not in ['veterinario', 'colaborador', 'admin']:
        message = 'Para solicitar um agendamento, escolha um veterinário disponível.'
        wants_json = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.accept_mimetypes.accept_json
        )
        if wants_json:
            return jsonify({'success': False, 'message': message}), 403
        flash(message, 'warning')
        return redirect(url_for('veterinarios'))
    if worker == 'veterinario' and is_vet:
        if current_user.role == 'admin':
            veterinario_id_arg = request.args.get(
                'veterinario_id', type=int
            )
            if veterinario_id_arg:
                veterinario = next(
                    (v for v in agenda_veterinarios if v.id == veterinario_id_arg),
                    None,
                )
                if not veterinario:
                    veterinario = Veterinario.query.get_or_404(
                        veterinario_id_arg
                    )
            elif agenda_veterinarios:
                veterinario = agenda_veterinarios[0]
            else:
                abort(404)
            admin_selected_veterinario_id = veterinario.id
        else:
            veterinario = current_user.veterinario
        if not veterinario:
            abort(404)
        vet_user_id = getattr(veterinario, "user_id", None)
        clinic_ids = _veterinarian_accessible_clinic_ids(veterinario)
        clinic_ids = calendar_access_scope.filter_clinic_ids(clinic_ids)
        associated_clinics = clinic_repo.list_by_ids(clinic_ids) if clinic_ids else []
        calendar_summary_clinic_ids = clinic_ids
        if getattr(veterinario, "id", None) is not None:
            calendar_summary_vets = [
                {
                    'id': veterinario.id,
                    'name': veterinario.user.name
                    if getattr(veterinario, "user", None)
                    else None,
                    'full_name': getattr(getattr(veterinario, 'user', None), 'name', None),
                    'specialty_list': getattr(veterinario, 'specialty_list', None),
                    'is_specialist': bool(getattr(veterinario, 'specialty_list', None)),
                    'clinic_ids': _vet_clinic_ids(veterinario),
                }
            ]
        include_colleagues = bool(clinic_ids)
        if include_colleagues:
            colleagues_source = []
            if current_user.role == 'admin' and agenda_veterinarios:
                colleagues_source.extend(
                    v
                    for v in agenda_veterinarios
                    if getattr(v, 'clinica_id', None) in clinic_ids
                )
            elif clinic_ids:
                colleagues_source.extend(
                    Veterinario.query.filter(
                        Veterinario.clinica_id.in_(clinic_ids)
                    ).all()
                )
            for clinica in associated_clinics:
                owner_vet = getattr(getattr(clinica, 'owner', None), 'veterinario', None)
                if owner_vet and getattr(owner_vet, 'id', None) is not None:
                    colleagues_source.append(owner_vet)
                colleagues_source.extend(
                    vet
                    for vet in (getattr(clinica, 'veterinarios_associados', []) or [])
                    if getattr(vet, 'id', None) is not None
                )
            known_ids = {entry['id'] for entry in calendar_summary_vets}
            for colleague in unique_items_by_id(colleagues_source):
                colleague_id = getattr(colleague, 'id', None)
                if (
                    not colleague_id
                    or colleague_id in known_ids
                    or not calendar_access_scope.allows_veterinarian(colleague)
                ):
                    continue
                calendar_summary_vets.append(
                    {
                        'id': colleague_id,
                        'name': colleague.user.name
                        if getattr(colleague, 'user', None)
                        else None,
                        'full_name': getattr(getattr(colleague, 'user', None), 'name', None),
                        'specialty_list': getattr(colleague, 'specialty_list', None),
                        'is_specialist': bool(getattr(colleague, 'specialty_list', None)),
                        'clinic_ids': _vet_clinic_ids(colleague),
                    }
                )
                known_ids.add(colleague_id)
        calendar_redirect_url = url_for(
            'appointments', view_as='veterinario', veterinario_id=veterinario.id
        )
        query_args = request.args.to_dict()
        if current_user.role == 'admin':
            query_args['view_as'] = 'veterinario'
            query_args['veterinario_id'] = veterinario.id
        appointments_url = url_for('appointments', **query_args)
        schedule_form = VetScheduleForm(prefix='schedule')
        if _is_admin():
            vets_for_choices = agenda_veterinarios or Veterinario.query.all()
        else:
            vets_for_choices = [veterinario]
        schedule_form.veterinario_id.choices = [
            (v.id, v.user.name) for v in vets_for_choices
        ]
        appointment_form = None
        combined_vets = []
        clinic_vet_ids = set()
        specialist_ids = set()
        if not clinic_ids:
            flash(
                'Você precisa estar vinculado a uma clínica para agendar novas consultas.',
                'warning',
            )
            if request.method == 'POST' and 'appointment-submit' in request.form:
                return redirect(appointments_url)
        else:
            appointment_form = AppointmentForm(
                is_veterinario=True,
                clinic_ids=clinic_ids,
                prefix='appointment',
                require_clinic_scope=True,
            )
            clinic_vets = (
                Veterinario.query.filter(
                    Veterinario.clinica_id.in_(clinic_ids)
                ).all()
            ) if clinic_ids else []
            for clinica in associated_clinics:
                owner_vet = getattr(getattr(clinica, 'owner', None), 'veterinario', None)
                if owner_vet and getattr(owner_vet, 'id', None) is not None:
                    clinic_vets.append(owner_vet)
            specialists = []
            for clinica in associated_clinics:
                specialists.extend(
                    vet
                    for vet in (getattr(clinica, 'veterinarios_associados', []) or [])
                    if getattr(vet, 'id', None) is not None
                )
            combined_vets = unique_items_by_id(clinic_vets + specialists + [veterinario])

            def _vet_sort_key(vet):
                name = getattr(getattr(vet, 'user', None), 'name', '') or ''
                return name.lower()

            combined_vets = sorted(
                (
                    vet
                    for vet in combined_vets
                    if getattr(vet, 'id', None) is not None
                ),
                key=_vet_sort_key,
            )
            combined_vets = calendar_access_scope.filter_veterinarians(combined_vets)
            if not combined_vets:
                combined_vets = [veterinario]

            clinic_vet_ids = {
                getattr(vet, 'id', None) for vet in clinic_vets if getattr(vet, 'id', None)
            }
            specialist_ids = {
                getattr(vet, 'id', None)
                for vet in specialists
                if getattr(vet, 'id', None)
            }

            def _vet_label(vet):
                base_name = getattr(getattr(vet, 'user', None), 'name', None)
                label = base_name or f"Profissional #{getattr(vet, 'id', '—')}"
                vet_id = getattr(vet, 'id', None)
                if vet_id in specialist_ids and vet_id not in clinic_vet_ids:
                    return f"{label} (Especialista)"
                return label

            appointment_form.veterinario_id.choices = [
                (vet.id, _vet_label(vet)) for vet in combined_vets
            ]
            calendar_summary_vets = [
                {
                    'id': vet.id,
                    'name': _vet_label(vet),
                    'label': _vet_label(vet),
                    'full_name': getattr(getattr(vet, 'user', None), 'name', None),
                    'specialty_list': getattr(vet, 'specialty_list', None),
                    'is_specialist': getattr(vet, 'id', None) in specialist_ids
                    and getattr(vet, 'id', None) not in clinic_vet_ids,
                    'clinic_ids': _vet_clinic_ids(vet),
                }
                for vet in combined_vets
            ]
            calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)
            if not calendar_summary_vets:
                calendar_summary_vets = [
                    {
                        'id': veterinario.id,
                        'name': _vet_label(veterinario),
                        'label': _vet_label(veterinario),
                        'full_name': getattr(getattr(veterinario, 'user', None), 'name', None),
                        'specialty_list': getattr(veterinario, 'specialty_list', None),
                        'is_specialist': getattr(veterinario, 'id', None) in specialist_ids
                        and getattr(veterinario, 'id', None) not in clinic_vet_ids,
                        'clinic_ids': _vet_clinic_ids(veterinario),
                    }
                ]
            if request.method == 'GET':
                appointment_form.veterinario_id.data = veterinario.id
        if schedule_form.submit.data and not _is_admin():
            raw_vet_id = request.form.get(schedule_form.veterinario_id.name)
            if raw_vet_id is None:
                abort(403)
            try:
                submitted_vet_id = int(raw_vet_id)
            except (TypeError, ValueError):
                abort(403)
            if submitted_vet_id != veterinario.id:
                abort(403)

        if schedule_form.submit.data and schedule_form.validate_on_submit():
            if not _is_admin() and schedule_form.veterinario_id.data != veterinario.id:
                abort(403)

            vet_id = schedule_form.veterinario_id.data
            for dia in schedule_form.dias_semana.data:
                if has_schedule_conflict(
                    vet_id,
                    dia,
                    schedule_form.hora_inicio.data,
                    schedule_form.hora_fim.data,
                ):
                    flash(f'Conflito de horário em {dia}.', 'danger')
                    return redirect(appointments_url)
            added = False
            for dia in schedule_form.dias_semana.data:
                if has_schedule_conflict(
                    schedule_form.veterinario_id.data,
                    dia,
                    schedule_form.hora_inicio.data,
                    schedule_form.hora_fim.data,
                ):
                    flash(f'Horário em {dia} conflita com um existente.', 'danger')
                    continue
                horario = VetSchedule(
                    veterinario_id=vet_id,
                    dia_semana=dia,
                    hora_inicio=schedule_form.hora_inicio.data,
                    hora_fim=schedule_form.hora_fim.data,
                    intervalo_inicio=schedule_form.intervalo_inicio.data,
                    intervalo_fim=schedule_form.intervalo_fim.data,
                )
                db.session.add(horario)
                added = True
            if added:
                db.session.commit()
                flash('Horário salvo com sucesso.', 'success')
            else:
                flash('Nenhum novo horário foi salvo.', 'info')
            return redirect(appointments_url)
        if appointment_form and appointment_form.validate_on_submit():
            scheduled_at_local = datetime.combine(
                appointment_form.date.data, appointment_form.time.data
            )
            if not is_slot_available(
                appointment_form.veterinario_id.data,
                scheduled_at_local,
                kind=appointment_form.kind.data,
            ):
                flash(
                    'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                    'danger'
                )
            else:
                animal = get_animal_or_404(appointment_form.animal_id.data)
                tutor_id = animal.user_id
                requires_plan = current_app.config.get(
                    'REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT', False
                )
                if requires_plan and not Appointment.has_active_subscription(
                    animal.id, tutor_id
                ):
                    flash(
                        'O animal não possui uma assinatura de plano de saúde ativa.',
                        'danger',
                    )
                else:
                    scheduled_at = normalize_to_utc(scheduled_at_local)
                    current_vet = getattr(current_user, 'veterinario', None)
                    selected_vet_id = appointment_form.veterinario_id.data
                    same_user = current_vet and current_vet.id == selected_vet_id
                    selected_vet = next(
                        (
                            vet
                            for vet in combined_vets
                            if getattr(vet, 'id', None) == selected_vet_id
                        ),
                        None,
                    )
                    if not selected_vet and selected_vet_id:
                        selected_vet = Veterinario.query.get(selected_vet_id)
                    selected_clinic_id = (
                        getattr(selected_vet, 'clinica_id', None)
                        if selected_vet
                        else None
                    )
                    appt = Appointment(
                        animal_id=animal.id,
                        tutor_id=tutor_id,
                        veterinario_id=selected_vet_id,
                        scheduled_at=scheduled_at,
                        clinica_id=selected_clinic_id or animal.clinica_id,
                        notes=appointment_form.reason.data,
                        kind=appointment_form.kind.data,
                        status='accepted' if same_user else 'scheduled',
                        created_by=current_user.id,
                        created_at=utcnow(),
                    )
                    db.session.add(appt)
                    db.session.commit()
                    flash(
                        f'Agendamento de {animal.name} criado para '
                        f'{format_datetime_brazil(scheduled_at, "%d/%m às %H:%M")}. 🐾',
                        'success',
                    )
            return redirect(appointments_url)
        horarios = VetSchedule.query.filter_by(
            veterinario_id=veterinario.id
        ).all()
        weekday_order = {
            'Segunda': 0,
            'Terça': 1,
            'Quarta': 2,
            'Quinta': 3,
            'Sexta': 4,
            'Sábado': 5,
            'Domingo': 6,
        }
        horarios.sort(key=lambda h: weekday_order.get(h.dia_semana, 7))
        horarios_grouped = []
        for h in horarios:
            if not horarios_grouped or horarios_grouped[-1]['dia'] != h.dia_semana:
                horarios_grouped.append({'dia': h.dia_semana, 'itens': []})
            horarios_grouped[-1]['itens'].append(h)
        now = utcnow()
        today_start_local = datetime.now(BR_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_start_utc = today_start_local.astimezone(timezone.utc)
        start_str = request.args.get('start')
        end_str = request.args.get('end')
        if start_str and end_str:
            start_dt = datetime.fromisoformat(start_str)
            end_dt = datetime.fromisoformat(end_str) + timedelta(days=1)
            restrict_to_today = False
        else:
            today = date.today()
            start_dt = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
            end_dt = start_dt + timedelta(days=7)
            restrict_to_today = True
        start_dt_utc, end_dt_utc = local_date_range_to_utc(start_dt, end_dt)
        upcoming_start = start_dt_utc or today_start_utc
        if restrict_to_today and today_start_utc:
            upcoming_start = max(upcoming_start, today_start_utc)

        appointment_scope_conditions = [
            Appointment.veterinario_id == veterinario.id
        ]
        if vet_user_id:
            appointment_scope_conditions.append(Appointment.created_by == vet_user_id)
        if len(appointment_scope_conditions) == 1:
            appointment_scope_filter = appointment_scope_conditions[0]
        else:
            appointment_scope_filter = or_(*appointment_scope_conditions)

        pending_consultas = (
            Appointment.query.filter(Appointment.status == 'scheduled')
            .filter(Appointment.scheduled_at > now)
            .filter(appointment_scope_filter)
            .order_by(Appointment.scheduled_at)
            .all()
        )
        appointments_pending_consults = []
        pending_consults_for_me = []
        pending_consults_waiting_others = []
        for appt in pending_consultas:
            appt.time_left = (appt.scheduled_at - timedelta(hours=2)) - now
            kind = appt.kind or ('retorno' if appt.consulta_id else 'consulta')
            if kind == 'general':
                kind = 'consulta'
            item = {'kind': kind, 'appt': appt}
            appointments_pending_consults.append(item)
            if appt.veterinario_id == veterinario.id:
                pending_consults_for_me.append(item)
            else:
                pending_consults_waiting_others.append(item)

        from models import ExamAppointment, Message, BlocoExames

        exam_pending = (
            ExamAppointment.query.filter_by(specialist_id=veterinario.id, status='pending')
            .filter(ExamAppointment.scheduled_at > now)
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        exams_pending_to_accept = []
        for ex in exam_pending:
            ex.time_left = ex.confirm_by - now
            if ex.time_left.total_seconds() <= 0:
                ex.status = 'canceled'
                msg = Message(
                    sender_id=vet_user_id or getattr(current_user, "id", None),
                    receiver_id=ex.requester_id,
                    animal_id=ex.animal_id,
                    content=f"Especialista não aceitou exame para {ex.animal.name}. Reagende com outro profissional.",
                )
                db.session.add(msg)
                db.session.commit()
            else:
                exams_pending_to_accept.append(ex)

        if vet_user_id:
            pending_requested_exams = (
                ExamAppointment.query.filter(
                    ExamAppointment.requester_id == vet_user_id,
                    ExamAppointment.status.in_(['pending', 'confirmed']),
                    ExamAppointment.specialist_id != veterinario.id,
                    ExamAppointment.scheduled_at > now,
                )
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
        else:
            pending_requested_exams = []
        exams_waiting_other_vets = []
        status_styles = {
            'pending': {
                'badge_class': 'bg-warning text-dark',
                'icon_class': 'text-warning',
                'status_label': 'Aguardando confirmação',
                'show_time_left': True,
            },
            'confirmed': {
                'badge_class': 'bg-success',
                'icon_class': 'text-success',
                'status_label': 'Confirmado',
                'show_time_left': False,
            },
        }
        default_style = {
            'badge_class': 'bg-secondary',
            'icon_class': 'text-secondary',
            'status_label': 'Status desconhecido',
            'show_time_left': False,
        }
        for ex in pending_requested_exams:
            if ex.confirm_by:
                ex.time_left = ex.confirm_by - now
            else:
                ex.time_left = timedelta(0)
            style = status_styles.get(ex.status, default_style)
            include_exam = ex.status == 'confirmed'
            if ex.status == 'pending':
                include_exam = ex.time_left.total_seconds() > 0
            if not include_exam:
                continue
            exams_waiting_other_vets.append(
                {
                    'exam': ex,
                    'status': ex.status,
                    'status_label': style['status_label'],
                    'badge_class': style['badge_class'],
                    'icon_class': style['icon_class'],
                    'show_time_left': style['show_time_left'] and ex.time_left.total_seconds() > 0,
                }
            )

        accepted_consultas_in_range = (
            Appointment.query.filter(Appointment.status == 'accepted')
            .filter(Appointment.scheduled_at >= start_dt_utc)
            .filter(Appointment.scheduled_at < end_dt_utc)
            .filter(appointment_scope_filter)
            .order_by(Appointment.scheduled_at)
            .all()
        )
        future_cutoff = max(now, upcoming_start) if upcoming_start else now
        past_accepted_consultas = []
        upcoming_consultas = []
        for appt in accepted_consultas_in_range:
            scheduled_at = appt.scheduled_at
            if scheduled_at:
                scheduled_at_utc = normalize_to_utc(scheduled_at)
                if scheduled_at_utc >= future_cutoff:
                    upcoming_consultas.append(appt)
                    continue
            past_accepted_consultas.append(appt)

        upcoming_exams = (
            ExamAppointment.query.filter_by(specialist_id=veterinario.id, status='confirmed')
            .filter(ExamAppointment.scheduled_at >= future_cutoff)
            .filter(ExamAppointment.scheduled_at < end_dt_utc)
            .order_by(ExamAppointment.scheduled_at)
            .all()
        )
        appointments_upcoming = []
        for appt in upcoming_consultas:
            kind = appt.kind or ('retorno' if appt.consulta_id else 'consulta')
            if kind == 'general':
                kind = 'consulta'
            appointments_upcoming.append({'kind': kind, 'appt': appt})
        for exam in upcoming_exams:
            appointments_upcoming.append({'kind': 'exame', 'appt': exam})
        appointments_upcoming.sort(key=lambda x: x['appt'].scheduled_at)

        appointments_upcoming_for_me = []
        appointments_upcoming_requested = []
        for item in appointments_upcoming:
            if item['kind'] == 'exame':
                appointments_upcoming_for_me.append(item)
                continue
            appt = item['appt']
            if getattr(appt, 'veterinario_id', None) == veterinario.id:
                appointments_upcoming_for_me.append(item)
            elif vet_user_id and getattr(appt, 'created_by', None) == vet_user_id:
                appointments_upcoming_requested.append(item)

        consulta_filters = [Consulta.status == 'finalizada']
        scope_filters = []
        if vet_user_id:
            scope_filters.append(Consulta.created_by == vet_user_id)
        if veterinario.clinica_id:
            scope_filters.append(Consulta.clinica_id == veterinario.clinica_id)
        if scope_filters:
            consulta_filters.append(or_(*scope_filters))

        consultas_query = (
            Consulta.query.outerjoin(Appointment, Consulta.appointment)
            .options(
                joinedload(Consulta.animal).joinedload(Animal.owner),
                joinedload(Consulta.veterinario),
                joinedload(Consulta.appointment)
                .joinedload(Appointment.animal)
                .joinedload(Animal.owner),
            )
            .filter(*consulta_filters)
        )

        consulta_timestamp_expr = case(
            (Consulta.finalizada_em.isnot(None), Consulta.finalizada_em),
            (Appointment.scheduled_at.isnot(None), Appointment.scheduled_at),
            else_=Consulta.created_at,
        )
        if start_dt_utc is not None:
            consultas_query = consultas_query.filter(consulta_timestamp_expr >= start_dt_utc)
        if end_dt_utc is not None:
            consultas_query = consultas_query.filter(consulta_timestamp_expr < end_dt_utc)

        consultas_finalizadas = consultas_query.all()

        consulta_animal_ids = {c.animal_id for c in consultas_finalizadas}
        exam_blocks_by_consulta = defaultdict(list)
        exam_blocks_by_animal = defaultdict(list)
        if consulta_animal_ids:
            blocos_query = (
                BlocoExames.query.options(joinedload(BlocoExames.exames))
                .filter(BlocoExames.animal_id.in_(consulta_animal_ids))
            )
            for bloco in blocos_query.all():
                exam_blocks_by_animal[bloco.animal_id].append(bloco)
                consulta_ref = getattr(bloco, 'consulta_id', None)
                if consulta_ref:
                    exam_blocks_by_consulta[consulta_ref].append(bloco)

        schedule_events = []

        def _consulta_timestamp(consulta_obj):
            if consulta_obj.finalizada_em:
                return consulta_obj.finalizada_em
            if consulta_obj.appointment and consulta_obj.appointment.scheduled_at:
                return consulta_obj.appointment.scheduled_at
            return consulta_obj.created_at

        for consulta in consultas_finalizadas:
            timestamp = _consulta_timestamp(consulta)
            timestamp_utc = normalize_to_utc(timestamp) if timestamp else None

            if not timestamp_utc or not (start_dt_utc <= timestamp_utc < end_dt_utc):
                continue
            relevant_blocks = exam_blocks_by_consulta.get(consulta.id)
            if not relevant_blocks:
                relevant_blocks = [
                    bloco
                    for bloco in exam_blocks_by_animal.get(consulta.animal_id, [])
                    if bloco.data_criacao
                    and timestamp
                    and bloco.data_criacao.date() == timestamp.date()
                ]
            exam_summary = []
            exam_ids = []
            for bloco in relevant_blocks or []:
                for exame in bloco.exames:
                    exam_ids.append(exame.id)
                    exam_summary.append(
                        {
                            'nome': exame.nome,
                            'status': exame.status,
                            'justificativa': exame.justificativa,
                            'bloco_id': bloco.id,
                        }
                    )
            schedule_events.append(
                {
                    'kind': 'consulta_finalizada',
                    'timestamp': timestamp,
                    'animal': consulta.animal,
                    'consulta': consulta,
                    'consulta_id': consulta.id,
                    'appointment': consulta.appointment,
                    'exam_summary': exam_summary,
                    'exam_blocks': relevant_blocks or [],
                    'exam_ids': exam_ids,
                }
            )

        for appt in past_accepted_consultas:
            if not appt.scheduled_at or not (start_dt_utc <= appt.scheduled_at < end_dt_utc):
                continue
            schedule_events.append(
                {
                    'kind': 'consulta_aceita',
                    'timestamp': appt.scheduled_at,
                    'animal': appt.animal,
                    'consulta': appt.consulta,
                    'consulta_id': appt.consulta_id,
                    'appointment': appt,
                    'exam_summary': [],
                    'exam_blocks': [],
                    'exam_ids': [],
                }
            )

        for item in appointments_upcoming:
            if item['kind'] == 'retorno':
                appt = item['appt']
                schedule_events.append(
                    {
                        'kind': 'retorno',
                        'timestamp': appt.scheduled_at,
                        'animal': appt.animal,
                        'appointment': appt,
                        'consulta_id': appt.consulta_id,
                        'exam_summary': [],
                        'exam_blocks': [],
                        'exam_ids': [],
                    }
                )

        for exam in upcoming_exams:
            schedule_events.append(
                {
                    'kind': 'exame',
                    'timestamp': exam.scheduled_at,
                    'animal': exam.animal,
                    'exam': exam,
                    'consulta_id': None,
                    'exam_summary': [],
                    'exam_blocks': [],
                    'exam_ids': [exam.id],
                }
            )

        schedule_events.sort(
            key=lambda event: event.get('timestamp') or datetime.min,
            reverse=True,
        )

        # Nota: os contadores de "visto" em sessão foram removidos — os badges
        # da navbar agora contam apenas itens acionáveis (exames pendentes e
        # consultas aguardando aceite) e zeram quando o item é tratado.

        vet_clinic_ids = _veterinarian_accessible_clinic_ids(veterinario)
        vet_clinic_scope = (
            vet_clinic_ids
            if len(vet_clinic_ids) > 1
            else vet_clinic_ids[0]
            if vet_clinic_ids
            else None
        )
        require_vet_appointments = _is_specialist_veterinarian(veterinario)
        pet_scope_param = request.args.get('scope', 'all')
        pet_page = request.args.get('page', 1, type=int)
        pet_search = (request.args.get('animal_search', '', type=str) or '').strip()
        pet_sort = (request.args.get('animal_sort', 'date_desc', type=str) or 'date_desc').strip()
        vet_animais_adicionados, vet_animais_pagination, vet_animais_scope = _get_recent_animais(
            pet_scope_param,
            pet_page,
            clinic_id=vet_clinic_scope,
            user_id=vet_user_id,
            require_appointments=require_vet_appointments,
            veterinario_id=veterinario.id if require_vet_appointments else None,
            search=pet_search,
            sort_option=pet_sort,
        )

        tutor_scope_param = request.args.get('tutor_scope', 'all')
        tutor_page = request.args.get('tutor_page', 1, type=int)
        tutor_search = (request.args.get('tutor_search', '', type=str) or '').strip()
        tutor_sort = (request.args.get('tutor_sort', 'name_asc', type=str) or 'name_asc').strip()
        vet_tutores_adicionados, vet_tutores_pagination, vet_tutores_scope = _get_recent_tutores(
            tutor_scope_param,
            tutor_page,
            clinic_id=vet_clinic_scope,
            user_id=vet_user_id,
            require_appointments=require_vet_appointments,
            veterinario_id=veterinario.id if require_vet_appointments else None,
            search=tutor_search,
            sort_option=tutor_sort,
        )

        species_list = list_species()
        breed_list = list_breeds()

        return render_template(
            'agendamentos/edit_vet_schedule.html',
            schedule_form=schedule_form,
            appointment_form=appointment_form,
            veterinario=veterinario,
            agenda_veterinarios=agenda_veterinarios,
            agenda_colaboradores=agenda_colaboradores,
            admin_selected_view=admin_selected_view,
            admin_selected_veterinario_id=admin_selected_veterinario_id,
            admin_selected_colaborador_id=admin_selected_colaborador_id,
            horarios_grouped=horarios_grouped,
            appointments_pending_consults=appointments_pending_consults,
            pending_consults_for_me=pending_consults_for_me,
            pending_consults_waiting_others=pending_consults_waiting_others,
            exams_pending_to_accept=exams_pending_to_accept,
            exams_waiting_other_vets=exams_waiting_other_vets,
            appointments_upcoming=appointments_upcoming,
            appointments_upcoming_for_me=appointments_upcoming_for_me,
            appointments_upcoming_requested=appointments_upcoming_requested,
            schedule_events=schedule_events,
            start_dt=start_dt,
            end_dt=end_dt,
            timedelta=timedelta,
            calendar_summary_vets=calendar_summary_vets,
            calendar_summary_clinic_ids=calendar_summary_clinic_ids,
            calendar_redirect_url=calendar_redirect_url,
            exam_confirm_default_hours=current_app.config.get(
                'EXAM_CONFIRM_DEFAULT_HOURS',
                2,
            ),
            species_list=species_list,
            breed_list=breed_list,
            vet_animais_adicionados=vet_animais_adicionados,
            vet_animais_pagination=vet_animais_pagination,
            vet_animais_scope=vet_animais_scope,
            vet_animal_search=pet_search,
            vet_animal_sort=pet_sort,
            vet_tutores_adicionados=vet_tutores_adicionados,
            vet_tutores_pagination=vet_tutores_pagination,
            vet_tutores_scope=vet_tutores_scope,
            vet_tutor_search=tutor_search,
            vet_tutor_sort=tutor_sort,
        )
    else:
        if worker in ['colaborador', 'admin']:
            clinica_id = current_user.clinica_id
            if current_user.role == 'admin' and worker == 'colaborador':
                colaborador_id_arg = request.args.get('colaborador_id', type=int)
                if colaborador_id_arg:
                    selected_colaborador = next(
                        (c for c in agenda_colaboradores if c.id == colaborador_id_arg),
                        None,
                    )
                    if not selected_colaborador:
                        selected_colaborador = (
                            User.query.filter_by(
                                id=colaborador_id_arg, worker='colaborador'
                            )
                            .first_or_404()
                        )
                elif agenda_colaboradores:
                    selected_colaborador = agenda_colaboradores[0]
                if selected_colaborador:
                    admin_selected_colaborador_id = selected_colaborador.id
                    if selected_colaborador.clinica_id:
                        clinica_id = selected_colaborador.clinica_id
                if not clinica_id:
                    clinica = Clinica.query.first()
                    clinica_id = clinica.id if clinica else None
            elif current_user.role == 'admin' and not clinica_id:
                clinica = Clinica.query.first()
                clinica_id = clinica.id if clinica else None
            appointment_form = None
            if not clinica_id:
                flash(
                    'Associe o colaborador a uma clínica para habilitar novos agendamentos.',
                    'warning',
                )
                if request.method == 'POST' and 'appointment-submit' in request.form:
                    return _redirect_to_current_appointments()
            else:
                appointment_form = AppointmentForm(
                    prefix='appointment',
                    clinic_ids=[clinica_id],
                    require_clinic_scope=True,
                )

                clinic = Clinica.query.get(clinica_id) if clinica_id else None
                vets = Veterinario.query.filter_by(clinica_id=clinica_id).all()
                specialists = []
                if clinic:
                    specialists = [
                        vet
                        for vet in getattr(clinic, 'veterinarios_associados', []) or []
                        if getattr(vet, 'id', None) is not None
                    ]
                combined_vets = unique_items_by_id(vets + specialists)

                def _vet_sort_key(vet):
                    name = (
                        getattr(getattr(vet, 'user', None), 'name', '')
                        or ''
                    )
                    return name.lower()

                combined_vets = sorted(
                    (vet for vet in combined_vets if getattr(vet, 'id', None) is not None),
                    key=_vet_sort_key,
                )
                combined_vets = calendar_access_scope.filter_veterinarians(combined_vets)

                clinic_vet_ids = {getattr(vet, 'id', None) for vet in vets if getattr(vet, 'id', None) is not None}
                specialist_ids = {getattr(vet, 'id', None) for vet in specialists}

                def _vet_label(vet):
                    base_name = getattr(getattr(vet, 'user', None), 'name', None)
                    label = base_name or f"Profissional #{getattr(vet, 'id', '—')}"
                    if getattr(vet, 'id', None) in specialist_ids and getattr(vet, 'id', None) not in clinic_vet_ids:
                        return f"{label} (Especialista)"
                    return label

                appointment_form.veterinario_id.choices = [
                    (vet.id, _vet_label(vet)) for vet in combined_vets
                ]
                calendar_summary_vets = [
                    {
                        'id': vet.id,
                        'name': _vet_label(vet),
                        'label': _vet_label(vet),
                        'full_name': getattr(getattr(vet, 'user', None), 'name', None),
                        'specialty_list': getattr(vet, 'specialty_list', None),
                        'is_specialist': getattr(vet, 'id', None) in specialist_ids
                        and getattr(vet, 'id', None) not in clinic_vet_ids,
                    }
                    for vet in combined_vets
                ]
                calendar_summary_vets = calendar_access_scope.filter_veterinarians(calendar_summary_vets)
                calendar_summary_clinic_ids = calendar_access_scope.filter_clinic_ids([clinica_id]) if clinica_id else []
            if appointment_form and appointment_form.validate_on_submit():
                scheduled_at_local = datetime.combine(
                    appointment_form.date.data, appointment_form.time.data
                )
                if not is_slot_available(
                    appointment_form.veterinario_id.data,
                    scheduled_at_local,
                    kind=appointment_form.kind.data,
                ):
                    flash(
                        'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                        'danger'
                    )
                else:
                    scheduled_at = normalize_to_utc(scheduled_at_local)
                    if appointment_form.kind.data == 'exame':
                        duration = get_appointment_duration('exame')
                        if has_conflict_for_slot(
                            appointment_form.veterinario_id.data,
                            scheduled_at_local,
                            duration,
                        ):
                            flash(
                                'Horário indisponível para o veterinário selecionado. Já existe uma consulta ou exame nesse intervalo.',
                                'danger'
                            )
                        else:
                            appt = ExamAppointment(
                                animal_id=appointment_form.animal_id.data,
                                specialist_id=appointment_form.veterinario_id.data,
                                requester_id=current_user.id,
                                scheduled_at=scheduled_at,
                                status='confirmed',
                            )
                            db.session.add(appt)
                            db.session.commit()
                            flash('Exame agendado com sucesso.', 'success')
                    else:
                        animal = get_animal_or_404(appointment_form.animal_id.data)
                        tutor_id = animal.user_id
                        requires_plan = current_app.config.get(
                            'REQUIRE_HEALTH_SUBSCRIPTION_FOR_APPOINTMENT', False
                        )
                        if requires_plan and not Appointment.has_active_subscription(
                            animal.id, tutor_id
                        ):
                            flash(
                                'O animal não possui uma assinatura de plano de saúde ativa.',
                                'danger',
                            )
                            return _redirect_to_current_appointments()

                    appt = Appointment(
                        animal_id=animal.id,
                        tutor_id=tutor_id,
                        veterinario_id=appointment_form.veterinario_id.data,
                        scheduled_at=scheduled_at,
                        clinica_id=clinica_id,
                        notes=appointment_form.reason.data,
                        kind=appointment_form.kind.data,
                        created_by=current_user.id,
                        created_at=utcnow(),
                    )
                    db.session.add(appt)
                    db.session.commit()
                    flash(
                        f'Agendamento de {animal.name} criado para '
                        f'{format_datetime_brazil(scheduled_at, "%d/%m às %H:%M")}. 🐾',
                        'success',
                    )
                return _redirect_to_current_appointments()
            appointments = (
                Appointment.query
                .filter_by(clinica_id=clinica_id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            exam_appointments = (
                ExamAppointment.query
                .join(ExamAppointment.animal)
                .filter(Animal.clinica_id == clinica_id)
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
            vaccine_appointments = (
                Vacina.query
                .join(Vacina.animal)
                .filter(Animal.clinica_id == clinica_id)
                .filter(Vacina.aplicada_em >= date.today())
                .order_by(Vacina.aplicada_em)
                .all()
            )
            for vac in vaccine_appointments:
                vac.scheduled_at = datetime.combine(vac.aplicada_em, time.min, tzinfo=BR_TZ)
            form = appointment_form
        else:
            tutor_user = current_user
            if current_user.role == 'admin' and worker == 'tutor':
                tutor_user = User.query.filter(User.worker.is_(None)).first() or current_user
            appointments = (
                Appointment.query.filter_by(tutor_id=tutor_user.id)
                .order_by(Appointment.scheduled_at)
                .all()
            )
            exam_appointments = (
                ExamAppointment.query
                .join(ExamAppointment.animal)
                .filter(Animal.user_id == tutor_user.id)
                .order_by(ExamAppointment.scheduled_at)
                .all()
            )
            vaccine_appointments = (
                Vacina.query
                .join(Vacina.animal)
                .filter(Animal.user_id == tutor_user.id)
                .filter(Vacina.aplicada_em >= date.today())
                .order_by(Vacina.aplicada_em)
                .all()
            )
            for vac in vaccine_appointments:
                vac.scheduled_at = datetime.combine(vac.aplicada_em, time.min, tzinfo=BR_TZ)
            form = None
        appointments_grouped = group_appointments_by_day(appointments)
        nfse_documents_by_appointment = {}
        if appointments:
            appointment_ids = [appt.id for appt in appointments]
            nfse_documents = (
                FiscalDocument.query
                .filter(FiscalDocument.related_type == "appointment")
                .filter(FiscalDocument.related_id.in_(appointment_ids))
                .order_by(FiscalDocument.created_at.desc())
                .all()
            )
            for doc in nfse_documents:
                if doc.related_id not in nfse_documents_by_appointment:
                    nfse_documents_by_appointment[doc.related_id] = doc
        exam_appointments_grouped = group_appointments_by_day(exam_appointments)
        vaccine_appointments_grouped = group_appointments_by_day(vaccine_appointments)
        if request.headers.get('X-Partial') == 'appointments_table' or request.args.get('partial') == 'appointments_table':
            return render_template(
                'partials/appointments_table.html',
                appointments_grouped=appointments_grouped,
                nfse_documents_by_appointment=nfse_documents_by_appointment,
            )

        return render_template(
            'agendamentos/appointments.html',
            appointments=appointments,
            appointments_grouped=appointments_grouped,
            exam_appointments=exam_appointments,
            exam_appointments_grouped=exam_appointments_grouped,
            vaccine_appointments=vaccine_appointments,
            vaccine_appointments_grouped=vaccine_appointments_grouped,
            form=form,
            agenda_users=agenda_users,
            agenda_veterinarios=agenda_veterinarios,
            agenda_colaboradores=agenda_colaboradores,
            admin_selected_view=admin_selected_view,
            admin_selected_veterinario_id=admin_selected_veterinario_id,
            admin_selected_colaborador_id=admin_selected_colaborador_id,
            admin_default_selection_value=admin_default_selection_value,
            calendar_summary_vets=calendar_summary_vets,
            calendar_summary_clinic_ids=calendar_summary_clinic_ids,
            nfse_documents_by_appointment=nfse_documents_by_appointment,
        )


@bp.route("/appointments/<int:appointment_id>/nfse", methods=["POST"])
@login_required
def appointment_emit_nfse(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    if not appointment.clinica_id:
        abort(403)

    clinic_id = current_user_clinic_id()
    if clinic_id and appointment.clinica_id != clinic_id and (current_user.role or '').lower() != 'admin':
        abort(403)

    if not appointment.clinica or not appointment.clinica.fiscal_emitter:
        flash("Clínica sem emissor fiscal configurado.", "warning")
        return redirect(url_for("appointments"))

    payload = build_nfse_payload_from_appointment(appointment)
    document = create_nfse_document(
        related_type="appointment",
        related_id=appointment.id,
        emitter_id=appointment.clinica.fiscal_emitter.id,
        payload=payload,
    )
    queue_emit_nfse(document.id, clinic_id=appointment.clinica_id)
    flash("Emissão de NFS-e enfileirada.", "success")
    return redirect(url_for("fiscal_document_detail", document_id=document.id))


@bp.route("/appointments/calendar", methods=["GET"])
@login_required
def appointments_calendar():
    """Página experimental de calendário para tutores."""
    return render_template('agendamentos/appointments_calendar.html')


@bp.route("/appointments/<int:veterinario_id>/schedule/<int:horario_id>/edit", methods=["POST"])
@login_required
def edit_vet_schedule_slot(veterinario_id, horario_id):
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )

    def json_response(success, status=200, message=None, errors=None, extra=None):
        if not wants_json:
            abort(status)
        payload = {'success': success}
        if message:
            payload['message'] = message
        if errors:
            payload['errors'] = errors
        if extra:
            payload.update(extra)
        response = jsonify(payload)
        response.status_code = status
        return response

    if not (
        _is_admin()
        or (
            is_veterinarian(current_user)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
        abort(403)
    veterinario = Veterinario.query.get_or_404(veterinario_id)
    horario = VetSchedule.query.get_or_404(horario_id)
    if not _is_admin() and horario.veterinario_id != veterinario_id:
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
        abort(403)
    form = VetScheduleForm(prefix='schedule')
    if _is_admin():
        vet_choices = Veterinario.query.all()
    else:
        vet_choices = [veterinario]
    form.veterinario_id.choices = [
        (v.id, v.user.name) for v in vet_choices
    ]
    if not _is_admin():
        raw_vet_id = request.form.get(form.veterinario_id.name)
        if raw_vet_id is None:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        try:
            submitted_vet_id = int(raw_vet_id)
        except (TypeError, ValueError):
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        if submitted_vet_id != veterinario_id:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
    redirect_response = redirect(url_for('appointments'))
    if form.validate_on_submit():
        novo_vet = form.veterinario_id.data
        if not _is_admin() and novo_vet != veterinario_id:
            if wants_json:
                return json_response(False, status=403, message='Você não tem permissão para editar este horário.')
            abort(403)
        dias_submetidos = form.dias_semana.data or []
        dias_unicos = []
        vistos = set()
        for dia in dias_submetidos:
            if not dia:
                continue
            if dia not in vistos:
                dias_unicos.append(dia)
                vistos.add(dia)
        if not dias_unicos:
            if wants_json:
                return json_response(False, status=400, message='Selecione ao menos um dia da semana.')
            flash('Selecione ao menos um dia da semana.', 'danger')
            return redirect_response

        inicio = form.hora_inicio.data
        fim = form.hora_fim.data
        intervalo_inicio = form.intervalo_inicio.data
        intervalo_fim = form.intervalo_fim.data

        original_inicio = horario.hora_inicio
        original_fim = horario.hora_fim
        original_intervalo_inicio = horario.intervalo_inicio
        original_intervalo_fim = horario.intervalo_fim

        primary_day = horario.dia_semana if horario.dia_semana in dias_unicos else dias_unicos[0]
        schedules_por_dia = {primary_day: horario}

        for dia in dias_unicos:
            if dia == primary_day:
                continue
            schedules_por_dia[dia] = (
                VetSchedule.query.filter_by(
                    veterinario_id=novo_vet,
                    dia_semana=dia,
                    hora_inicio=original_inicio,
                    hora_fim=original_fim,
                    intervalo_inicio=original_intervalo_inicio,
                    intervalo_fim=original_intervalo_fim,
                )
                .order_by(VetSchedule.id.asc())
                .first()
            )

        conflitos = []
        for dia, schedule_obj in schedules_por_dia.items():
            exclude_id = schedule_obj.id if schedule_obj else None
            if has_schedule_conflict(novo_vet, dia, inicio, fim, exclude_id=exclude_id):
                conflitos.append(dia)

        if conflitos:
            mensagem_conflito = 'Conflito de horário.'
            if len(conflitos) == 1:
                mensagem_conflito = f'Conflito de horário em {conflitos[0]}.'
            else:
                dias_texto = ', '.join(conflitos)
                mensagem_conflito = f'Conflitos de horário nos dias: {dias_texto}.'
            if wants_json:
                return json_response(False, status=400, message=mensagem_conflito)
            flash(mensagem_conflito, 'danger')
            return redirect_response

        horario.veterinario_id = novo_vet
        horario.dia_semana = primary_day
        horario.hora_inicio = inicio
        horario.hora_fim = fim
        horario.intervalo_inicio = intervalo_inicio
        horario.intervalo_fim = intervalo_fim

        processed_schedules = [horario]

        for dia, schedule_obj in schedules_por_dia.items():
            if dia == primary_day:
                continue
            if schedule_obj:
                schedule_obj.veterinario_id = novo_vet
                schedule_obj.dia_semana = dia
                schedule_obj.hora_inicio = inicio
                schedule_obj.hora_fim = fim
                schedule_obj.intervalo_inicio = intervalo_inicio
                schedule_obj.intervalo_fim = intervalo_fim
                processed_schedules.append(schedule_obj)
            else:
                novo_horario = VetSchedule(
                    veterinario_id=novo_vet,
                    dia_semana=dia,
                    hora_inicio=inicio,
                    hora_fim=fim,
                    intervalo_inicio=intervalo_inicio,
                    intervalo_fim=intervalo_fim,
                )
                db.session.add(novo_horario)
                processed_schedules.append(novo_horario)
                schedules_por_dia[dia] = novo_horario

        db.session.flush()
        db.session.commit()

        total_dias = len(dias_unicos)
        if total_dias > 1:
            mensagem_sucesso = f'Horários atualizados para {total_dias} dias.'
        else:
            mensagem_sucesso = 'Horário atualizado com sucesso.'

        def serialize_schedule(record):
            return {
                'id': record.id,
                'veterinario_id': record.veterinario_id,
                'dia_semana': record.dia_semana,
                'hora_inicio': record.hora_inicio.strftime('%H:%M') if record.hora_inicio else None,
                'hora_fim': record.hora_fim.strftime('%H:%M') if record.hora_fim else None,
                'intervalo_inicio': record.intervalo_inicio.strftime('%H:%M') if record.intervalo_inicio else None,
                'intervalo_fim': record.intervalo_fim.strftime('%H:%M') if record.intervalo_fim else None,
            }

        if wants_json:
            schedules_payload = []
            vistos_ids = set()
            for schedule in processed_schedules:
                if schedule.id in vistos_ids:
                    continue
                vistos_ids.add(schedule.id)
                schedules_payload.append(serialize_schedule(schedule))
            return json_response(
                True,
                message=mensagem_sucesso,
                extra={
                    'schedules': schedules_payload,
                    'processed_days': dias_unicos,
                },
            )
        flash(mensagem_sucesso, 'success')
        return redirect_response
    if wants_json:
        errors = form.errors or {}
        flat_errors = [err for field_errors in errors.values() for err in field_errors]
        message = flat_errors[0] if flat_errors else 'Não foi possível atualizar o horário.'
        return json_response(False, status=400, message=message, errors=errors if errors else None)
    flash('Não foi possível atualizar o horário. Verifique os dados e tente novamente.', 'danger')
    return redirect_response


@bp.route("/appointments/<int:veterinario_id>/schedule/bulk_delete", methods=["POST"])
@login_required
def bulk_delete_vet_schedule(veterinario_id):
    from models import Veterinario, VetSchedule
    from sqlalchemy.exc import SQLAlchemyError

    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )

    def json_response(success, status=200, message=None, extra=None):
        if not wants_json:
            abort(status)
        payload = {'success': success}
        if message:
            payload['message'] = message
        if extra:
            payload.update(extra)
        response = jsonify(payload)
        response.status_code = status
        return response

    if not (
        _is_admin()
        or (
            is_veterinarian(current_user)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        if wants_json:
            return json_response(False, status=403, message='Você não tem permissão para excluir estes horários.')
        abort(403)

    Veterinario.query.get_or_404(veterinario_id)

    raw_ids = request.form.getlist('schedule_ids')
    if not raw_ids:
        message = 'Nenhum horário selecionado.'
        if wants_json:
            return json_response(False, status=400, message=message)
        flash(message, 'warning')
        return redirect(request.referrer or url_for('appointments'))

    schedule_ids = []
    for raw_id in raw_ids:
        try:
            schedule_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    unique_ids = list(dict.fromkeys(schedule_ids))
    if not unique_ids:
        message = 'Nenhum horário selecionado.'
        if wants_json:
            return json_response(False, status=400, message=message)
        flash(message, 'warning')
        return redirect(request.referrer or url_for('appointments'))

    schedules = (
        VetSchedule.query.filter(
            VetSchedule.id.in_(unique_ids),
            VetSchedule.veterinario_id == veterinario_id,
        )
        .order_by(VetSchedule.id.asc())
        .all()
    )

    if len(schedules) != len(unique_ids):
        message = 'Alguns horários selecionados não foram encontrados ou não pertencem a este profissional.'
        if wants_json:
            return json_response(False, status=400, message=message)
        flash(message, 'warning')
        return redirect(request.referrer or url_for('appointments'))

    try:
        for schedule in schedules:
            db.session.delete(schedule)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        message = 'Não foi possível excluir os horários selecionados.'
        if wants_json:
            return json_response(False, status=500, message=message)
        flash(message, 'danger')
        return redirect(request.referrer or url_for('appointments'))

    total = len(schedules)
    removed_ids = [schedule.id for schedule in schedules]
    if total == 1:
        message = 'Horário removido com sucesso.'
    else:
        message = f'{total} horários removidos com sucesso.'

    if wants_json:
        return json_response(True, message=message, extra={'removed_ids': removed_ids})

    flash(message, 'success')
    return redirect(request.referrer or url_for('appointments'))


@bp.route("/appointments/<int:veterinario_id>/schedule/<int:horario_id>/delete", methods=["POST"])
@login_required
def delete_vet_schedule(veterinario_id, horario_id):
    if not (
        _is_admin()
        or (
            is_veterinarian(current_user)
            and current_user.veterinario.id == veterinario_id
        )
    ):
        abort(403)
    horario = VetSchedule.query.get_or_404(horario_id)
    if not _is_admin() and horario.veterinario_id != veterinario_id:
        abort(403)
    db.session.delete(horario)
    db.session.commit()
    flash('Horário removido com sucesso.', 'success')
    return redirect(url_for('appointments'))


@bp.route("/appointments/pending", methods=["GET"])
@login_required
def pending_appointments():
    return redirect(url_for('appointments'))


@bp.route("/appointments/manage", methods=["GET"])
@login_required
def manage_appointments():
    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'
    if current_user.role != 'admin' and not (is_vet or is_collaborator):
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('index'))

    appointment_repo = AppointmentRepository()
    wants_json = 'application/json' in request.headers.get('Accept', '')
    page = max(request.args.get('page', type=int, default=1), 1)
    per_page = request.args.get('per_page', type=int, default=20)
    per_page = max(1, min(per_page or 20, 100))

    clinic_id = None
    if current_user.role != 'admin':
        if is_vet:
            clinic_id = current_user.veterinario.clinica_id
        elif is_collaborator:
            clinic_id = current_user.clinica_id

    pagination = appointment_repo.paginate_for_management(
        is_admin=current_user.role == 'admin',
        clinic_id=clinic_id,
        page=page,
        per_page=per_page,
    )
    appointments = pagination.items

    if wants_json:
        delete_form = AppointmentDeleteForm()
        items_html = render_template(
            'agendamentos/_appointments_admin_items.html',
            appointments=appointments,
            delete_form=delete_form,
        )
        next_page = pagination.next_num if pagination.has_next else None
        return jsonify({
            'success': True,
            'html': items_html,
            'next_page': next_page,
            'page': page,
        })

    delete_form = AppointmentDeleteForm()
    next_page = pagination.next_num if pagination.has_next else None
    return render_template(
        'agendamentos/appointments_admin.html',
        appointments=appointments,
        delete_form=delete_form,
        next_page=next_page,
        per_page=per_page,
    )


@bp.route("/appointments/<int:appointment_id>/edit", methods=["GET", "POST"])
@login_required
def edit_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'
    if is_vet or is_collaborator:
        if is_vet:
            user_clinic = current_user.veterinario.clinica_id
        else:
            user_clinic = current_user.clinica_id

        # Some legacy appointments might not have `clinica_id` stored.
        # In that case, fall back to the clinic of the assigned veterinarian
        # to validate access instead of denying with a 403.
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if appointment_clinic != user_clinic:
            abort(403)
    elif current_user.role != 'admin' and appointment.tutor_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        date_str = data.get('date')
        time_str = data.get('time')
        vet_id = data.get('veterinario_id')
        notes = data.get('notes')
        if not date_str or not time_str or not vet_id:
            return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
        try:
            scheduled_at_local = datetime.combine(
                datetime.strptime(date_str, '%Y-%m-%d').date(),
                datetime.strptime(time_str, '%H:%M').time(),
            )
            vet_id = int(vet_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Dados inválidos.'}), 400
        existing_local = coerce_to_brazil_tz(appointment.scheduled_at).replace(tzinfo=None)
        if not is_slot_available(vet_id, scheduled_at_local, kind=appointment.kind) and not (
            vet_id == appointment.veterinario_id and scheduled_at_local == existing_local
        ):
            return jsonify({
                'success': False,
                'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
            }), 400
        appointment.veterinario_id = vet_id
        appointment.scheduled_at = normalize_to_utc(scheduled_at_local)
        if notes is not None:
            appointment.notes = notes
        db.session.commit()
        card_html = render_template('partials/_appointment_card.html', appt=appointment)
        return jsonify({
            'success': True,
            'message': 'Agendamento atualizado com sucesso.',
            'card_html': card_html,
            'appointment_id': appointment.id,
        })

    veterinarios = Veterinario.query.all()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template(
            'partials/edit_appointment_form.html',
            appointment=appointment,
            veterinarios=veterinarios,
        )
    return render_template('agendamentos/edit_appointment.html', appointment=appointment, veterinarios=veterinarios)


@bp.route("/appointments/<int:appointment_id>/status", methods=["POST"])
@login_required
def update_appointment_status(appointment_id):
    """Update the status of an appointment."""
    appointment = Appointment.query.get_or_404(appointment_id)

    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if current_user.role == 'admin':
        pass
    elif is_vet or is_collaborator:
        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if is_vet:
            veterinario = getattr(current_user, 'veterinario', None)
            vet_id = getattr(veterinario, 'id', None)
            if not (vet_id and appointment.veterinario_id == vet_id):
                clinic_ids = set()
                primary_clinic = getattr(veterinario, 'clinica_id', None)
                if primary_clinic is not None:
                    clinic_ids.add(primary_clinic)
                clinic_ids.update(
                    clinica_id
                    for clinica_id in (
                        getattr(clinica, 'id', None)
                        for clinica in getattr(veterinario, 'clinicas', [])
                    )
                    if clinica_id is not None
                )

                if appointment_clinic not in clinic_ids:
                    abort(403)
        else:
            user_clinic = getattr(current_user, 'clinica_id', None)
            if appointment_clinic != user_clinic:
                abort(403)
    elif appointment.tutor_id != current_user.id:
        abort(403)

    accepts = request.accept_mimetypes
    accept_json = accepts['application/json']
    accept_html = accepts['text/html']
    wants_json = (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or (accept_json > 0 and accept_json > accept_html)
    )
    redirect_url = request.referrer or url_for('appointments')

    status_value = request.form.get('status') or (request.get_json(silent=True) or {}).get('status')
    status = (status_value or '').strip().lower()
    allowed_statuses = {'scheduled', 'completed', 'canceled', 'accepted'}
    if status not in allowed_statuses:
        message = 'Status inválido.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 400
        flash(message, 'error')
        return redirect(redirect_url)

    if status == 'accepted' and current_user.role != 'admin':
        error_message = 'Somente o veterinário responsável pode aceitar este agendamento.'
        if not is_vet:
            if wants_json:
                return jsonify({'success': False, 'message': error_message}), 403
            flash(error_message, 'error')
            return redirect(redirect_url)
        veterinario = getattr(current_user, 'veterinario', None)
        vet_id = getattr(veterinario, 'id', None)
        if not (vet_id and appointment.veterinario_id == vet_id):
            if wants_json:
                return jsonify({'success': False, 'message': error_message}), 403
            flash(error_message, 'error')
            return redirect(redirect_url)

    should_enforce_deadline = False
    if status == 'accepted':
        should_enforce_deadline = current_user.role != 'admin'
    elif status == 'canceled':
        should_enforce_deadline = (
            current_user.role != 'admin'
            and not (is_vet or is_collaborator)
        )

    if should_enforce_deadline and appointment.scheduled_at - utcnow() < timedelta(hours=2):
        message = 'Prazo expirado.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 400
        # Mantém o comportamento simples de texto quando o prazo expira.
        return message, 400

    appointment.status = status
    db.session.commit()
    # Atualiza o badge da Agenda imediatamente (sem esperar o TTL do cache).
    _invalidate_cached_context(current_user.id, 'pending_appointment_count')

    if wants_json:
        card_html = render_template('partials/_appointment_card.html', appt=appointment)
        return jsonify({
            'success': True,
            'message': 'Status atualizado.',
            'status': appointment.status,
            'appointment_id': appointment.id,
            'card_html': card_html,
        })

    flash('Status atualizado.', 'success')
    # Sempre redireciona de volta à página anterior para evitar exibir apenas
    # o JSON "{\"success\": true}".
    return redirect(request.referrer or url_for('appointments'))


@bp.route("/appointments/<int:appointment_id>/delete", methods=["POST"])
@login_required
def delete_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    wants_json = 'application/json' in request.headers.get('Accept', '')
    is_vet = is_veterinarian(current_user)
    is_collaborator = getattr(current_user, 'worker', None) == 'colaborador'

    if current_user.role == 'admin':
        pass
    elif is_vet or is_collaborator:
        if is_vet:
            veterinario = getattr(current_user, 'veterinario', None)
            user_clinic = getattr(veterinario, 'clinica_id', None)
        else:
            user_clinic = getattr(current_user, 'clinica_id', None)

        appointment_clinic = appointment.clinica_id
        if appointment_clinic is None and appointment.veterinario:
            appointment_clinic = appointment.veterinario.clinica_id

        if appointment_clinic != user_clinic:
            abort(403)
    else:
        abort(403)
    try:
        db.session.delete(appointment)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        message = 'Não foi possível remover o agendamento.'
        if wants_json:
            return jsonify({'success': False, 'message': message}), 500
        flash(message, 'danger')
        return redirect(request.referrer or url_for('manage_appointments'))

    message = 'Agendamento removido.'
    if wants_json:
        return jsonify({'success': True, 'message': message, 'appointment_id': appointment_id})

    flash(message, 'success')
    return redirect(request.referrer or url_for('manage_appointments'))


@bp.route("/animal/<int:animal_id>/schedule_exam", methods=["POST"])
@login_required
def schedule_exam(animal_id):
    from models import ExamAppointment, AgendaEvento, Veterinario, Animal, Message
    data = request.get_json(silent=True) or {}
    specialist_id = data.get('specialist_id')
    date_str = data.get('date')
    time_str = data.get('time')
    exam_name = (data.get('exam_name') or '').strip()
    if not all([specialist_id, date_str, time_str]):
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    if len(exam_name) > 120:
        return jsonify({'success': False, 'message': 'Nome do exame muito longo.'}), 400
    scheduled_at_local = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    scheduled_at = normalize_to_utc(scheduled_at_local)
    # Ensure requested time falls within the veterinarian's available schedule
    available_times = get_available_times(specialist_id, scheduled_at_local.date(), kind='exame')
    if time_str not in available_times:
        if available_times:
            msg = (
                'Horário selecionado não está disponível. '
                f"Horários disponíveis: {', '.join(available_times)}"
            )
        else:
            msg = 'Nenhum horário disponível para a data escolhida.'
        return jsonify({'success': False, 'message': msg}), 400
    duration = get_appointment_duration('exame')
    if has_conflict_for_slot(specialist_id, scheduled_at_local, duration):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
        }), 400
    vet = Veterinario.query.get(specialist_id)
    animal = Animal.query.get_or_404(animal_id)
    same_user = vet and vet.user_id == current_user.id
    if not vet:
        abort(404)
    if not same_user:
        if not _is_public_veterinarian(vet):
            abort(404)
        animal_city = None
        if getattr(animal, 'owner', None) and getattr(animal.owner, 'endereco', None):
            animal_city = (animal.owner.endereco.cidade or '').strip() or None
        if not animal_city and getattr(current_user, 'endereco', None):
            animal_city = (current_user.endereco.cidade or '').strip() or None
        if animal_city and not _vet_matches_public_city(vet, animal_city, kind='exame'):
            abort(404)
    if animal.user_id != current_user.id and not same_user:
        animal = get_animal_or_404(animal_id)
    appt = ExamAppointment(
        animal_id=animal_id,
        specialist_id=specialist_id,
        requester_id=current_user.id,
        exam_name=exam_name or None,
        scheduled_at=scheduled_at,
        status='confirmed' if same_user else 'pending',
    )
    if vet and animal:
        exam_label = exam_name or 'Exame'
        evento = AgendaEvento(
            titulo=f"{exam_label} de {animal.name}",
            inicio=scheduled_at,
            fim=scheduled_at + duration,
            responsavel_id=vet.user_id,
            clinica_id=animal.clinica_id,
        )
        db.session.add(evento)
        if not same_user:
            confirm_by_local = to_timezone_aware(appt.confirm_by, target_tz=BR_TZ)
            msg = Message(
                sender_id=current_user.id,
                receiver_id=vet.user_id,
                animal_id=animal_id,
                content=(
                    f"{exam_label} agendado para {animal.name} em {scheduled_at_local.strftime('%d/%m/%Y %H:%M')}. "
                    f"Confirme até {confirm_by_local.strftime('%H:%M') if confirm_by_local else 'N/A'}"
                ),
            )
            db.session.add(msg)
    db.session.add(appt)
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    confirm_by = None if same_user else appt.confirm_by.isoformat()
    return jsonify({'success': True, 'confirm_by': confirm_by, 'html': html})


@bp.route("/exam_appointment/<int:appointment_id>/status", methods=["POST"])
@login_required
def update_exam_appointment_status(appointment_id):
    from models import ExamAppointment, Message
    appt = ExamAppointment.query.get_or_404(appointment_id)
    if current_user.id != appt.specialist.user_id and current_user.role != 'admin':
        abort(403)
    status = request.form.get('status') or (request.get_json(silent=True) or {}).get('status')
    if status not in {'confirmed', 'canceled'}:
        return jsonify({'success': False, 'message': 'Status inválido.'}), 400
    if status == 'confirmed' and utcnow() > appt.confirm_by:
        return jsonify({'success': False, 'message': 'Tempo de confirmação expirado.'}), 400
    appt.status = status
    if status == 'canceled':
        msg = Message(
            sender_id=current_user.id,
            receiver_id=appt.requester_id,
            animal_id=appt.animal_id,
            content=f"Especialista não aceitou exame para {appt.animal.name}. Reagende com outro profissional.",
        )
        db.session.add(msg)
    elif status == 'confirmed':
        scheduled_local = to_timezone_aware(appt.scheduled_at, target_tz=BR_TZ)
        msg = Message(
            sender_id=current_user.id,
            receiver_id=appt.requester_id,
            animal_id=appt.animal_id,
            content=(
                f"Exame de {appt.animal.name} confirmado para "
                f"{scheduled_local.strftime('%d/%m/%Y %H:%M')} com {appt.specialist.user.name}."
            ),
        )
        db.session.add(msg)
    db.session.commit()
    return jsonify({'success': True})


@bp.route("/exam_appointment/<int:appointment_id>/update", methods=["POST"])
@login_required
def update_exam_appointment(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    data = request.get_json(silent=True) or {}
    date_str = data.get('date')
    time_str = data.get('time')
    specialist_id = data.get('specialist_id', appt.specialist_id)
    if not date_str or not time_str:
        return jsonify({'success': False, 'message': 'Dados incompletos.'}), 400
    scheduled_at_local = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    scheduled_at = normalize_to_utc(scheduled_at_local)
    duration = get_appointment_duration('exame')
    if has_conflict_for_slot(
        specialist_id,
        scheduled_at_local,
        duration,
        exclude_exam_id=appointment_id,
    ):
        return jsonify({
            'success': False,
            'message': 'Horário indisponível. Já existe uma consulta ou exame nesse intervalo.'
        }), 400
    appt.specialist_id = specialist_id
    appt.scheduled_at = scheduled_at
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=appt.animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    return jsonify({'success': True, 'html': html})


@bp.route("/exam_appointment/<int:appointment_id>/requester_update", methods=["POST"])
@login_required
def update_exam_appointment_requester(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    if current_user.id != appt.requester_id and current_user.role != 'admin':
        abort(403)

    data = request.get_json(silent=True) or {}
    confirm_by_str = data.get('confirm_by')
    status = data.get('status')
    updated = False

    if appt.status == 'confirmed' and any(
        value is not None for value in (confirm_by_str, status)
    ):
        return jsonify({'success': False, 'message': 'Este exame já foi confirmado pelo especialista.'}), 400

    if confirm_by_str is not None:
        if not confirm_by_str:
            appt.confirm_by = None
            updated = True
        else:
            try:
                confirm_local = datetime.strptime(confirm_by_str, '%Y-%m-%dT%H:%M')
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Formato de data inválido.'}), 400
            confirm_utc = normalize_to_utc(confirm_local)
            if appt.confirm_by != confirm_utc:
                appt.confirm_by = confirm_utc
                updated = True

    if status is not None:
        normalized_status = str(status).strip().lower()
        allowed_statuses = {'pending', 'canceled'}
        if normalized_status not in allowed_statuses:
            return jsonify({'success': False, 'message': 'Status inválido.'}), 400
        if normalized_status != appt.status:
            appt.status = normalized_status
            updated = True

    if updated:
        db.session.commit()

    status_styles = {
        'pending': {
            'badge_class': 'bg-warning text-dark',
            'icon_class': 'text-warning',
            'status_label': 'Aguardando confirmação',
            'show_time_left': True,
        },
        'confirmed': {
            'badge_class': 'bg-success',
            'icon_class': 'text-success',
            'status_label': 'Confirmado',
            'show_time_left': False,
        },
        'canceled': {
            'badge_class': 'bg-secondary',
            'icon_class': 'text-secondary',
            'status_label': 'Cancelado',
            'show_time_left': False,
        },
    }

    style = status_styles.get(appt.status, status_styles['pending'])
    now = utcnow()
    time_left_seconds = None
    time_left_display = None
    if appt.confirm_by:
        comparable_now = now.replace(tzinfo=None) if appt.confirm_by.tzinfo is None else now
        time_left = appt.confirm_by - comparable_now
        time_left_seconds = time_left.total_seconds()
        if time_left_seconds > 0 and style.get('show_time_left'):
            time_left_display = format_timedelta(time_left)

    confirm_localized = coerce_to_brazil_tz(appt.confirm_by) if appt.confirm_by else None
    confirm_display = confirm_localized.strftime('%d/%m/%Y %H:%M') if confirm_localized else None
    confirm_local_value = confirm_localized.strftime('%Y-%m-%dT%H:%M') if confirm_localized else None

    return jsonify({
        'success': True,
        'updated': updated,
        'exam': {
            'id': appt.id,
            'status': appt.status,
            'status_label': style['status_label'],
            'badge_class': style['badge_class'],
            'icon_class': style['icon_class'],
            'confirm_by': appt.confirm_by.isoformat() if appt.confirm_by else None,
            'confirm_by_display': confirm_display,
            'confirm_by_value': confirm_local_value,
            'show_time_left': bool(style.get('show_time_left') and time_left_seconds and time_left_seconds > 0),
            'time_left_seconds': time_left_seconds,
            'time_left_display': time_left_display,
        },
    })


@bp.route("/exam_appointment/<int:appointment_id>/delete", methods=["POST"])
@login_required
def delete_exam_appointment(appointment_id):
    from models import ExamAppointment
    appt = ExamAppointment.query.get_or_404(appointment_id)
    animal_id = appt.animal_id
    db.session.delete(appt)
    db.session.commit()
    appointments = ExamAppointment.query.filter_by(animal_id=animal_id).order_by(ExamAppointment.scheduled_at.desc()).all()
    html = render_template('partials/historico_exam_appointments.html', appointments=appointments)
    return jsonify({'success': True, 'html': html})


@bp.route("/animal/<int:animal_id>/exam_appointments", methods=["GET"])
@login_required
def animal_exam_appointments(animal_id):
    from models import ExamAppointment
    appointments = (
        ExamAppointment.query.filter_by(animal_id=animal_id)
        .order_by(ExamAppointment.scheduled_at.desc())
        .all()
    )
    return render_template('partials/historico_exam_appointments.html', appointments=appointments)

