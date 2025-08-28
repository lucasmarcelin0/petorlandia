import requests

from flask import redirect, render_template, session
from flask_login import current_user
from functools import wraps


from datetime import date
from datetime import datetime
from dateutil.relativedelta import relativedelta

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


def clinicas_do_usuario():
    """Retorna query de ``Clinica`` filtrada pelo usuário atual."""
    from models import Clinica

    if not current_user.is_authenticated:
        return Clinica.query.filter(False)

    if current_user.role == "admin":
        return Clinica.query

    if getattr(current_user, "veterinario", None) and current_user.veterinario.clinica_id:
        return Clinica.query.filter_by(id=current_user.veterinario.clinica_id)

    if current_user.clinica_id:
        return Clinica.query.filter_by(id=current_user.clinica_id)

    return Clinica.query.filter_by(owner_id=current_user.id)

