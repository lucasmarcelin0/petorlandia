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

def is_slot_available(veterinario_id, scheduled_at):
    """Return True if the veterinarian has the slot available.

    A slot is available when it falls inside the veterinarian's schedule
    (``VetSchedule``) for the corresponding weekday and there is no
    existing ``Appointment`` at the exact datetime.
    """
    from models import VetSchedule, Appointment

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
    if not schedules:
        return False

    time = scheduled_at.time()
    available = any(
        s.hora_inicio <= time < s.hora_fim
        and not (
            s.intervalo_inicio
            and s.intervalo_fim
            and s.intervalo_inicio <= time < s.intervalo_fim
        )
        for s in schedules
    )
    if not available:
        return False

    conflict = (
        Appointment.query
        .filter_by(veterinario_id=veterinario_id, scheduled_at=scheduled_at)
        .first()
    )
    return conflict is None


def has_schedule_conflict(veterinario_id, dia_semana, hora_inicio, hora_fim):
    """Verifica se há conflito com horários existentes do veterinário."""
    from models import VetSchedule

    existentes = VetSchedule.query.filter_by(
        veterinario_id=veterinario_id, dia_semana=dia_semana
    ).all()
    for s in existentes:
        if hora_inicio < s.hora_fim and hora_fim > s.hora_inicio:
            return True
    return False


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
    """Group appointments by date.

    Returns a list of tuples ``(date, [appointments])`` ordered by day.
    """
    sorted_appts = sorted(appointments, key=lambda a: a.scheduled_at)
    return [
        (day, list(items))
        for day, items in groupby(sorted_appts, key=lambda a: a.scheduled_at.date())
    ]


def appointment_to_event(appointment, duration_minutes=30):
    """Convert an ``Appointment`` into a FullCalendar-friendly event dict."""
    end_time = appointment.scheduled_at + timedelta(minutes=duration_minutes)
    title = appointment.animal.name if appointment.animal else 'Consulta'
    if appointment.veterinario and appointment.veterinario.user:
        title = f"{title} - {appointment.veterinario.user.name}"
    return {
        'id': appointment.id,
        'title': title,
        'start': appointment.scheduled_at.isoformat(),
        'end': end_time.isoformat(),
    }


def appointments_to_events(appointments, duration_minutes=30):
    """Convert a list of ``Appointment`` objects into event dicts."""
    return [appointment_to_event(a, duration_minutes) for a in appointments]


def get_available_times(veterinario_id, date):
    """Retorna horários disponíveis para um especialista em uma data."""
    from models import VetSchedule, Appointment, ExamAppointment

    weekday_map = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
    dia_semana = weekday_map[date.weekday()]
    schedules = VetSchedule.query.filter_by(veterinario_id=veterinario_id, dia_semana=dia_semana).all()
    available = []
    step = timedelta(minutes=30)
    for s in schedules:
        current = datetime.combine(date, s.hora_inicio)
        end = datetime.combine(date, s.hora_fim)
        while current < end:
            if s.intervalo_inicio and s.intervalo_fim:
                intervalo_inicio = datetime.combine(date, s.intervalo_inicio)
                intervalo_fim = datetime.combine(date, s.intervalo_fim)
                if intervalo_inicio <= current < intervalo_fim:
                    current += step
                    continue
            current_utc = (
                current
                .replace(tzinfo=BR_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            conflito = (
                Appointment.query.filter_by(veterinario_id=veterinario_id, scheduled_at=current_utc).first()
                or ExamAppointment.query.filter_by(specialist_id=veterinario_id, scheduled_at=current_utc).first()
            )
            if not conflito:
                available.append(current.strftime('%H:%M'))
            current += step
    return available


def get_weekly_schedule(veterinario_id, start_date, days=7, day_start=time(8, 0), day_end=time(18, 0)):
    """Return schedule overview for a veterinarian.

    The result is a list of dictionaries, one for each day, containing
    arrays of available times, booked times and slots when the vet does
    not work. All times are returned as strings in ``HH:MM`` format.
    """
    from models import VetSchedule, Appointment, ExamAppointment

    result = []
    step = timedelta(minutes=30)
    weekday_map = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']

    for i in range(days):
        dia = start_date + timedelta(days=i)
        dia_semana = weekday_map[dia.weekday()]
        schedules = VetSchedule.query.filter_by(
            veterinario_id=veterinario_id, dia_semana=dia_semana
        ).all()

        working_slots = set()
        for s in schedules:
            current = datetime.combine(dia, s.hora_inicio)
            end = datetime.combine(dia, s.hora_fim)
            while current < end:
                if s.intervalo_inicio and s.intervalo_fim:
                    intervalo_inicio = datetime.combine(dia, s.intervalo_inicio)
                    intervalo_fim = datetime.combine(dia, s.intervalo_fim)
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
            conflito = (
                Appointment.query.filter_by(veterinario_id=veterinario_id, scheduled_at=current_utc).first()
                or ExamAppointment.query.filter_by(specialist_id=veterinario_id, scheduled_at=current_utc).first()
            )
            time_str = slot.strftime('%H:%M')
            if conflito:
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

