import requests

from flask import redirect, render_template, session
from functools import wraps


from datetime import date

from datetime import datetime

from models import VetSchedule, Appointment

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


def is_slot_available(veterinario_id, when):
    """Check if a veterinarian is free at the given datetime."""
    weekday_map = {
        0: 'Segunda',
        1: 'Terça',
        2: 'Quarta',
        3: 'Quinta',
        4: 'Sexta',
        5: 'Sábado',
        6: 'Domingo',
    }
    dia_semana = weekday_map[when.weekday()]

    schedule = VetSchedule.query.filter_by(
        veterinario_id=veterinario_id,
        dia_semana=dia_semana,
    ).first()
    if not schedule or not (schedule.hora_inicio <= when.time() < schedule.hora_fim):
        return False

    existing = Appointment.query.filter_by(
        veterinario_id=veterinario_id,
        scheduled_at=when,
    ).first()
    return existing is None


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
