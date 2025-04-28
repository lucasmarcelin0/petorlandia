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
