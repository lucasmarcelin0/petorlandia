import requests

from flask import redirect, render_template, session
from flask_login import current_user
from functools import wraps


from datetime import date, datetime, timedelta, timezone, time
from itertools import groupby
from dateutil.relativedelta import relativedelta
from sqlalchemy import case
from zoneinfo import ZoneInfo


BR_TZ = ZoneInfo("America/Sao_Paulo")


DEFAULT_APPOINTMENT_DURATION_MINUTES = 30

APPOINTMENT_KIND_DURATIONS = {
    'consulta': 30,
    'retorno': 30,
    'exame': 30,
    'banho_tosa': 30,
    'vacina': 30,
}

DEFAULT_VACCINE_EVENT_START_TIME = time(9, 0)
DEFAULT_VACCINE_EVENT_DURATION = timedelta(minutes=30)

if APPOINTMENT_KIND_DURATIONS:
    MAX_APPOINTMENT_DURATION_MINUTES = max(APPOINTMENT_KIND_DURATIONS.values())
else:
    MAX_APPOINTMENT_DURATION_MINUTES = DEFAULT_APPOINTMENT_DURATION_MINUTES
MAX_APPOINTMENT_DURATION = timedelta(minutes=MAX_APPOINTMENT_DURATION_MINUTES)


def get_appointment_duration_minutes(kind):
    """Return the duration in minutes for the given appointment ``kind``."""

    if not kind:
        return DEFAULT_APPOINTMENT_DURATION_MINUTES
    return APPOINTMENT_KIND_DURATIONS.get(kind, DEFAULT_APPOINTMENT_DURATION_MINUTES)


def get_appointment_duration(kind):
    """Return a ``timedelta`` with the duration for the given appointment kind."""

    return timedelta(minutes=get_appointment_duration_minutes(kind))


def _to_utc_naive(dt):
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _local_start_candidates(dt):
    """Return possible naive local times for a stored datetime.

    Historic data may have been stored either as naive UTC or naive BRT values.
    To safely detect conflicts we consider both interpretations.
    """

    candidates = []
    if dt.tzinfo is None:
        candidates.append(dt)
        converted = dt.replace(tzinfo=timezone.utc).astimezone(BR_TZ).replace(tzinfo=None)
        candidates.append(converted)
    else:
        candidates.append(dt.astimezone(BR_TZ).replace(tzinfo=None))
    unique = []
    seen = set()
    for value in candidates:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _intervals_overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def has_conflict_for_slot(
    veterinario_id,
    start_local,
    duration,
    *,
    exclude_appointment_id=None,
    exclude_exam_id=None,
    preloaded_appointments=None,
    preloaded_exams=None,
):
    """Return ``True`` when the slot conflicts with existing appointments/exams."""

    from models import Appointment, ExamAppointment

    if start_local.tzinfo is None:
        start_local_with_tz = start_local.replace(tzinfo=BR_TZ)
        start_local_naive = start_local
    else:
        start_local_with_tz = start_local.astimezone(BR_TZ)
        start_local_naive = start_local_with_tz.replace(tzinfo=None)

    end_local_naive = start_local_naive + duration
    start_utc_naive = start_local_with_tz.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc_naive = start_utc_naive + duration

    windows = (
        (start_utc_naive - MAX_APPOINTMENT_DURATION, end_utc_naive + MAX_APPOINTMENT_DURATION),
        (start_local_naive - MAX_APPOINTMENT_DURATION, end_local_naive + MAX_APPOINTMENT_DURATION),
    )

    cached_appts = preloaded_appointments is not None
    cached_exams = preloaded_exams is not None

    appointments = preloaded_appointments if cached_appts else {}
    exams = preloaded_exams if cached_exams else {}

    if not cached_appts or not cached_exams:
        for window_start, window_end in windows:
            if not cached_appts:
                appts = (
                    Appointment.query
                    .filter(
                        Appointment.veterinario_id == veterinario_id,
                        Appointment.scheduled_at < window_end,
                        Appointment.scheduled_at > window_start,
                    )
                    .all()
                )
                for appt in appts:
                    appointments.setdefault(appt.id, appt)
            if not cached_exams:
                exams_conflicts = (
                    ExamAppointment.query
                    .filter(
                        ExamAppointment.specialist_id == veterinario_id,
                        ExamAppointment.scheduled_at < window_end,
                        ExamAppointment.scheduled_at > window_start,
                    )
                    .all()
                )
                for exam in exams_conflicts:
                    exams.setdefault(exam.id, exam)

    for appt in appointments.values():
        if exclude_appointment_id and appt.id == exclude_appointment_id:
            continue
        appt_duration = get_appointment_duration(appt.kind or 'consulta')
        appt_start_utc = _to_utc_naive(appt.scheduled_at)
        appt_end_utc = appt_start_utc + appt_duration
        if _intervals_overlap(start_utc_naive, end_utc_naive, appt_start_utc, appt_end_utc):
            return True
        for local_start in _local_start_candidates(appt.scheduled_at):
            local_end = local_start + appt_duration
            if _intervals_overlap(start_local_naive, end_local_naive, local_start, local_end):
                return True

    exam_duration = get_appointment_duration('exame')
    for exam in exams.values():
        if exclude_exam_id and exam.id == exclude_exam_id:
            continue
        exam_start_utc = _to_utc_naive(exam.scheduled_at)
        exam_end_utc = exam_start_utc + exam_duration
        if _intervals_overlap(start_utc_naive, end_utc_naive, exam_start_utc, exam_end_utc):
            return True
        for local_start in _local_start_candidates(exam.scheduled_at):
            local_end = local_start + exam_duration
            if _intervals_overlap(start_local_naive, end_local_naive, local_start, local_end):
                return True

    return False


def to_timezone_aware(dt, target_tz=BR_TZ):
    """Return ``dt`` converted to ``target_tz`` with an explicit offset.

    Datetimes stored in the database are naive UTC values.  When they are
    rendered for the calendar we need to include the timezone offset so the
    client can display the correct local hour.  This helper treats naive
    datetimes as UTC and converts them to the desired timezone.
    """

    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if target_tz:
        return dt.astimezone(target_tz)
    return dt

def parse_data_nascimento(data_str):
    """
    Converte uma string no formato 'dd/mm/yyyy' para datetime.
    Retorna None se for inválida.
    """
    try:
        return datetime.strptime(data_str, '%d/%m/%Y')
    except (ValueError, TypeError):
        return None


def calcular_idade(data_nasc):
    """Calcula idade com base na data de nascimento.

    Retorna a idade em anos quando for igual ou superior a 1 ano, ou
    em meses caso seja menor que isso. Quando ``data_nasc`` não é
    informado, retorna uma string vazia.
    """
    hoje = date.today()
    if data_nasc:
        delta = relativedelta(hoje, data_nasc)
        if delta.years > 0:
            return delta.years
        return delta.months
    return ''


def apology(message, code=400):
    """Render message as an apology to user."""

    def escape(s):
        """
        Escape special characters.

        https://github.com/jacebrowning/memegen#special-characters
        """
        for old, new in [
            ("-", "--"),
            (" ", "-"),
            ("_", "__"),
            ("?", "~q"),
            ("%", "~p"),
            ("#", "~h"),
            ("/", "~s"),
            ('"', "''"),
        ]:
            s = s.replace(old, new)
        return s

    return render_template("apology.html", top=code, bottom=escape(message)), code

def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function

def is_slot_available(veterinario_id, scheduled_at, kind='consulta'):
    """Return ``True`` if the veterinarian can take an appointment of ``kind``."""
    from models import VetSchedule

    weekday_map = {
        0: 'Segunda',
        1: 'Terça',
        2: 'Quarta',
        3: 'Quinta',
        4: 'Sexta',
        5: 'Sábado',
        6: 'Domingo',
    }
    dia = weekday_map[scheduled_at.weekday()]
    schedules = VetSchedule.query.filter_by(
        veterinario_id=veterinario_id, dia_semana=dia
    ).all()

    duration = get_appointment_duration(kind)
    if scheduled_at.tzinfo is None:
        scheduled_at_with_tz = scheduled_at.replace(tzinfo=BR_TZ)
        scheduled_at_local = scheduled_at
    else:
        scheduled_at_with_tz = scheduled_at.astimezone(BR_TZ)
        scheduled_at_local = scheduled_at_with_tz.replace(tzinfo=None)

    if schedules:
        slot_start = scheduled_at_local
        slot_end = slot_start + duration

        def _interval_overlaps_break(schedule):
            if schedule.intervalo_inicio and schedule.intervalo_fim:
                interval_start = datetime.combine(slot_start.date(), schedule.intervalo_inicio)
                interval_end = datetime.combine(slot_start.date(), schedule.intervalo_fim)
                return _intervals_overlap(slot_start, slot_end, interval_start, interval_end)
            return False

        available = any(
            datetime.combine(slot_start.date(), s.hora_inicio) <= slot_start
            and slot_end <= datetime.combine(slot_start.date(), s.hora_fim)
            and not _interval_overlaps_break(s)
            for s in schedules
        )
        if not available:
            return False

    return not has_conflict_for_slot(veterinario_id, scheduled_at_local, duration)


def clinicas_do_usuario():
    """Retorna query de ``Clinica`` filtrada pelo usuário atual."""
    from models import Clinica

    if not current_user.is_authenticated:
        return Clinica.query.filter(False)

    if current_user.role == "admin":
        query = Clinica.query
        default_id = None
        if getattr(current_user, "veterinario", None) and current_user.veterinario.clinica_id:
            default_id = current_user.veterinario.clinica_id
        elif current_user.clinica_id:
            default_id = current_user.clinica_id
        elif getattr(current_user, "clinicas", []):
            default_id = current_user.clinicas[0].id
        if default_id:
            query = query.order_by(
                case((Clinica.id == default_id, 0), else_=1)
            )
        return query

    if getattr(current_user, "veterinario", None) and current_user.veterinario.clinica_id:
        return Clinica.query.filter_by(id=current_user.veterinario.clinica_id)

    if current_user.clinica_id:
        return Clinica.query.filter_by(id=current_user.clinica_id)

    return Clinica.query.filter_by(owner_id=current_user.id)


def has_schedule_conflict(veterinario_id, dia_semana, hora_inicio, hora_fim, exclude_id=None):
    """Verifica se já existe horário que conflita para o veterinário."""
    from models import VetSchedule

    query = VetSchedule.query.filter_by(
        veterinario_id=veterinario_id, dia_semana=dia_semana
    )
    if exclude_id is not None:
        query = query.filter(VetSchedule.id != exclude_id)
    for existente in query.all():
        if not (hora_fim <= existente.hora_inicio or hora_inicio >= existente.hora_fim):
            return True
    return False


def group_appointments_by_day(appointments):
    """Group appointments by local (BRT) date.

    Returns a list of tuples ``(date, [appointments])`` ordered by day.
    """

    def to_local_datetime(dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(BR_TZ)

    decorated = [
        (to_local_datetime(appt.scheduled_at), appt)
        for appt in appointments
    ]
    decorated.sort(key=lambda item: item[0])
    grouped = []
    for day, items in groupby(decorated, key=lambda item: item[0].date()):
        grouped.append((day, [appt for _, appt in items]))
    return grouped


def _build_calendar_event(*, event_id, title, start, end, event_type,
                          editable, duration_editable, record_id=None,
                          class_names=None, extra_extended_props=None):
    """Serialize event metadata for FullCalendar."""

    if not start:
        return None

    start_aware = to_timezone_aware(start)
    end_aware = to_timezone_aware(end) if end else None

    if not start_aware:
        return None

    event = {
        'id': event_id,
        'title': title,
        'start': start_aware.isoformat(),
        'end': end_aware.isoformat() if end_aware else None,
        'allDay': False,
        'editable': editable,
        'durationEditable': duration_editable,
        'extendedProps': {
            'eventType': event_type,
        },
    }

    if record_id is not None:
        event['extendedProps']['recordId'] = record_id

    if extra_extended_props:
        event['extendedProps'].update(extra_extended_props)

    if class_names:
        event['classNames'] = list(class_names)

    return event


def appointment_to_event(appointment):
    """Convert an ``Appointment`` into a FullCalendar-friendly event dict."""

    if not appointment:
        return None

    end_time = appointment.scheduled_at + get_appointment_duration(appointment.kind)
    title = appointment.animal.name if appointment.animal else 'Consulta'
    if appointment.veterinario and appointment.veterinario.user:
        title = f"{title} - {appointment.veterinario.user.name}"

    tutor = getattr(appointment, 'tutor', None)
    animal = getattr(appointment, 'animal', None)
    vet = getattr(appointment, 'veterinario', None)
    vet_user = getattr(vet, 'user', None)

    extra_props = {
        'kind': getattr(appointment, 'kind', None),
        'clinicId': getattr(appointment, 'clinica_id', None),
        'veterinarioId': getattr(appointment, 'veterinario_id', None),
        'animalId': getattr(appointment, 'animal_id', None),
        'status': getattr(appointment, 'status', None),
        'tutorId': getattr(appointment, 'tutor_id', None),
        'tutorName': getattr(tutor, 'name', None),
        'animalName': getattr(animal, 'name', None),
        'vetName': getattr(vet_user, 'name', None),
        'notes': getattr(appointment, 'notes', None),
    }

    return _build_calendar_event(
        event_id=f"appointment-{appointment.id}",
        title=title,
        start=appointment.scheduled_at,
        end=end_time,
        event_type='appointment',
        editable=True,
        duration_editable=True,
        record_id=appointment.id,
        class_names=['calendar-event-appointment'],
        extra_extended_props=extra_props,
    )


def exam_to_event(exam):
    """Convert an ``ExamAppointment`` into a calendar event."""

    if not exam:
        return None

    title = f"Exame: {exam.animal.name if getattr(exam, 'animal', None) else 'Exame'}"
    if getattr(exam, 'specialist', None) and getattr(exam.specialist, 'user', None):
        title = f"{title} - {exam.specialist.user.name}"
    end_time = exam.scheduled_at + get_appointment_duration('exame')

    extra_props = {
        'status': getattr(exam, 'status', None),
        'animalId': getattr(exam, 'animal_id', None),
        'specialistId': getattr(exam, 'specialist_id', None),
    }

    return _build_calendar_event(
        event_id=f"exam-{exam.id}",
        title=title,
        start=exam.scheduled_at,
        end=end_time,
        event_type='exam',
        editable=False,
        duration_editable=False,
        record_id=exam.id,
        class_names=['calendar-event-exam'],
        extra_extended_props=extra_props,
    )


def vaccine_to_event(vaccine):
    """Convert a ``Vacina`` record into a calendar event."""

    if not vaccine or not getattr(vaccine, 'aplicada_em', None):
        return None

    start = datetime.combine(vaccine.aplicada_em, DEFAULT_VACCINE_EVENT_START_TIME)
    start = start.replace(tzinfo=BR_TZ)
    end = start + DEFAULT_VACCINE_EVENT_DURATION

    title = f"Vacina: {vaccine.nome}"
    if getattr(vaccine, 'animal', None):
        title = f"{title} - {vaccine.animal.name}"

    extra_props = {
        'aplicada': getattr(vaccine, 'aplicada', None),
        'animalId': getattr(vaccine, 'animal_id', None),
        'aplicadaPor': getattr(vaccine, 'aplicada_por', None),
    }

    return _build_calendar_event(
        event_id=f"vaccine-{vaccine.id}",
        title=title,
        start=start,
        end=end,
        event_type='vaccine',
        editable=False,
        duration_editable=False,
        record_id=vaccine.id,
        class_names=['calendar-event-vaccine'],
        extra_extended_props=extra_props,
    )


def appointments_to_events(appointments):
    """Convert a list of ``Appointment`` objects into event dicts."""
    events = []
    for appointment in appointments or []:
        event = appointment_to_event(appointment)
        if event:
            events.append(event)
    return events


def unique_items_by_id(items):
    """Return a list with duplicate IDs removed while preserving order."""

    seen = set()
    unique = []
    for item in items or []:
        item_id = getattr(item, 'id', None)
        if item_id is None or item_id in seen:
            continue
        seen.add(item_id)
        unique.append(item)
    return unique


def get_available_times(veterinario_id, date, kind='consulta', *, include_booked=False):
    """Retorna horários disponíveis para um especialista em uma data.

    When ``include_booked`` is ``True`` a dictionary with the available and
    booked slots is returned. Otherwise only the list of available times is
    returned for backwards compatibility.
    """
    from models import Appointment, ExamAppointment, VetSchedule

    weekday_map = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    dia_semana = weekday_map[date.weekday()]
    schedules = (
        VetSchedule.query
        .filter_by(veterinario_id=veterinario_id, dia_semana=dia_semana)
        .order_by(VetSchedule.hora_inicio)
        .all()
    )
    if not schedules:
        return {'available': [], 'booked': []} if include_booked else []

    duration = get_appointment_duration(kind)
    step = timedelta(minutes=30)

    earliest_start = min(s.hora_inicio for s in schedules)
    latest_end = max(s.hora_fim for s in schedules)

    day_start = datetime.combine(date, earliest_start)
    day_end = datetime.combine(date, latest_end)

    window_local_start = day_start - MAX_APPOINTMENT_DURATION
    window_local_end = day_end + MAX_APPOINTMENT_DURATION

    window_utc_start = window_local_start.replace(tzinfo=BR_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    window_utc_end = window_local_end.replace(tzinfo=BR_TZ).astimezone(timezone.utc).replace(tzinfo=None)

    appointments_cache = {}
    exams_cache = {}
    for window_start, window_end in (
        (window_utc_start, window_utc_end),
        (window_local_start, window_local_end),
    ):
        appts = (
            Appointment.query
            .filter(
                Appointment.veterinario_id == veterinario_id,
                Appointment.scheduled_at < window_end,
                Appointment.scheduled_at > window_start,
            )
            .all()
        )
        for appt in appts:
            appointments_cache.setdefault(appt.id, appt)

        exams_conflicts = (
            ExamAppointment.query
            .filter(
                ExamAppointment.specialist_id == veterinario_id,
                ExamAppointment.scheduled_at < window_end,
                ExamAppointment.scheduled_at > window_start,
            )
            .all()
        )
        for exam in exams_conflicts:
            exams_cache.setdefault(exam.id, exam)

    available = []
    booked = [] if include_booked else None
    available_seen = set()
    booked_seen = set() if include_booked else None
    for s in schedules:
        current = datetime.combine(date, s.hora_inicio)
        end = datetime.combine(date, s.hora_fim)
        while current + duration <= end:
            if s.intervalo_inicio and s.intervalo_fim:
                intervalo_inicio = datetime.combine(date, s.intervalo_inicio)
                intervalo_fim = datetime.combine(date, s.intervalo_fim)
                if _intervals_overlap(current, current + duration, intervalo_inicio, intervalo_fim):
                    current += step
                    continue
            time_str = current.strftime('%H:%M')
            conflict = has_conflict_for_slot(
                veterinario_id,
                current,
                duration,
                preloaded_appointments=appointments_cache,
                preloaded_exams=exams_cache,
            )
            if not conflict:
                if time_str not in available_seen:
                    available.append(time_str)
                    available_seen.add(time_str)
            elif include_booked:
                if time_str not in booked_seen:
                    booked.append(time_str)
                    booked_seen.add(time_str)
            current += step
    available.sort()
    if include_booked:
        booked = booked or []
        booked = [t for t in booked if t not in available_seen]
        booked.sort()
        return {'available': available, 'booked': booked}
    return available


def get_weekly_schedule(veterinario_id, start_date, days=7, day_start=time(8, 0), day_end=time(18, 0)):
    """Return schedule overview for a veterinarian.

    The result is a list of dictionaries, one for each day, containing
    arrays of available times, booked times and slots when the vet does
    not work. All times are returned as strings in ``HH:MM`` format.
    """
    from models import VetSchedule, Appointment, ExamAppointment

    step = timedelta(minutes=30)
    weekday_map = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']

    # Load all schedules for the veterinarian once and group them by weekday.
    schedules_by_day = {}
    vet_schedules = VetSchedule.query.filter_by(veterinario_id=veterinario_id).all()
    for schedule in vet_schedules:
        schedules_by_day.setdefault(schedule.dia_semana, []).append(schedule)

    # Preload appointments/exams within the requested window so we can
    # determine slot availability without issuing a query per slot.
    range_start_local = datetime.combine(start_date, day_start)
    range_end_local = datetime.combine(start_date + timedelta(days=days), day_end)
    range_start_utc = range_start_local.replace(tzinfo=BR_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    range_end_utc = range_end_local.replace(tzinfo=BR_TZ).astimezone(timezone.utc).replace(tzinfo=None)

    appointment_rows = (
        Appointment.query
        .filter_by(veterinario_id=veterinario_id)
        .filter(Appointment.scheduled_at >= range_start_utc)
        .filter(Appointment.scheduled_at < range_end_utc)
        .with_entities(Appointment.scheduled_at)
        .all()
    )
    exam_rows = (
        ExamAppointment.query
        .filter_by(specialist_id=veterinario_id)
        .filter(ExamAppointment.scheduled_at >= range_start_utc)
        .filter(ExamAppointment.scheduled_at < range_end_utc)
        .with_entities(ExamAppointment.scheduled_at)
        .all()
    )

    booked_datetimes = {
        _to_utc_naive(row[0])
        for row in appointment_rows + exam_rows
        if row and row[0] is not None
    }

    result = []

    for i in range(days):
        dia = start_date + timedelta(days=i)
        dia_semana = weekday_map[dia.weekday()]
        schedules = schedules_by_day.get(dia_semana, [])

        working_slots = set()
        for schedule in schedules:
            current = datetime.combine(dia, schedule.hora_inicio)
            end = datetime.combine(dia, schedule.hora_fim)
            while current < end:
                if schedule.intervalo_inicio and schedule.intervalo_fim:
                    intervalo_inicio = datetime.combine(dia, schedule.intervalo_inicio)
                    intervalo_fim = datetime.combine(dia, schedule.intervalo_fim)
                    if intervalo_inicio <= current < intervalo_fim:
                        current += step
                        continue
                working_slots.add(current)
                current += step

        all_slots = []
        current = datetime.combine(dia, day_start)
        end_day = datetime.combine(dia, day_end)
        while current < end_day:
            all_slots.append(current)
            current += step

        available = []
        booked = []
        for slot in working_slots:
            current_utc = slot.replace(tzinfo=BR_TZ).astimezone(timezone.utc).replace(tzinfo=None)
            time_str = slot.strftime('%H:%M')
            if current_utc in booked_datetimes:
                booked.append(time_str)
            else:
                available.append(time_str)

        not_working = [s.strftime('%H:%M') for s in all_slots if s not in working_slots]
        result.append(
            {
                'date': dia.isoformat(),
                'available': sorted(available),
                'booked': sorted(booked),
                'not_working': sorted(not_working),
            }
        )

    return result


def group_vet_schedules_by_day(schedules):
    """Group veterinarian schedules by weekday.

    Returns a dict mapping each weekday to a list of formatted time ranges.
    The weekdays are ordered from Monday to Sunday and the time ranges are
    ordered by start time.
    """
    day_order = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    sorted_scheds = sorted(schedules, key=lambda s: (day_order.index(s.dia_semana), s.hora_inicio))
    return {
        dia: [
            f"{s.hora_inicio.strftime('%H:%M')} - {s.hora_fim.strftime('%H:%M')}"
            for s in items
        ]
        for dia, items in groupby(sorted_scheds, key=lambda s: s.dia_semana)
    }

