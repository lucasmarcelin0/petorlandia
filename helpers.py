import requests

from flask import redirect, render_template, session
from functools import wraps


from datetime import date

from datetime import datetime

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
    """Calcula idade com base na data de nascimento."""
    hoje = date.today()
    if data_nasc:
        idade = hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))
        return idade
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

