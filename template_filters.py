"""Template filters e helpers de formatação do Jinja.

Extraído de app.py durante a modularização. Registrar na factory/app com:

    from template_filters import register_template_filters
    register_template_filters(app)

Só pode conter funções puras de formatação (sem models, sem request).
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import quote_plus

from document_utils import format_cnpj as format_cnpj_value
from services.health_plan import coverage_badge, coverage_label
from time_utils import BR_TZ, coerce_to_brazil_tz


def date_now(format_string="%Y-%m-%d"):
    return datetime.now(BR_TZ).strftime(format_string)


def datetime_brazil(value):
    if isinstance(value, datetime):
        value = coerce_to_brazil_tz(value)
        return value.strftime("%d/%m/%Y %H:%M")
    return value


def format_datetime_brazil(value, fmt="%d/%m/%Y %H:%M"):
    if value is None:
        return ""

    if isinstance(value, datetime):
        assume_utc_local = os.getenv("BRAZIL_TIME_ASSUME_UTC_LOCAL", "0").lower() in {"1", "true", "yes"}

        if value.tzinfo is None:
            localized = coerce_to_brazil_tz(value)
        elif assume_utc_local and value.tzinfo == timezone.utc:
            # Some records may have been stored with UTC tzinfo even though the
            # timestamp was captured in local time. Reattach the Brazil timezone
            # without shifting the clock to avoid showing hours behind.
            localized = value.replace(tzinfo=BR_TZ)
        else:
            localized = coerce_to_brazil_tz(value)
        return localized.strftime(fmt)

    if isinstance(value, date):
        return value.strftime(fmt)

    return value


def isoformat_with_tz(value):
    """Return an ISO-8601 string with explicit timezone information.

    Datetimes are converted to UTC and rendered with a ``Z`` suffix. Naive
    datetimes are assumed to be expressed in Brazil's timezone to avoid
    unintended shifts when the client parses them.
    """

    if value is None:
        return ""

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=BR_TZ)
        value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")

    if isinstance(value, date):
        localized = datetime.combine(value, datetime.min.time(), tzinfo=BR_TZ)
        return localized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    return str(value)


def format_timedelta(value):
    """Format a ``timedelta`` as ``'Xh Ym'``."""
    total_seconds = int(value.total_seconds())
    if total_seconds <= 0:
        return "0h 0m"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"


def digits_only(value):
    """Return only the digits from a string."""
    return "".join(filter(str.isdigit, value)) if value else ""


def whatsapp_chat_url(phone: str | None, message: str | None = None) -> str | None:
    """Build a public WhatsApp chat URL for Brazilian phone numbers."""
    digits = digits_only(phone)
    if not digits:
        return None

    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) in {11, 12}:
        digits = digits[1:]
    if not digits.startswith("55") and len(digits) in {10, 11}:
        digits = f"55{digits}"
    if len(digits) < 12:
        return None

    url = f"https://wa.me/{digits}"
    if message:
        url = f"{url}?text={quote_plus(str(message))}"
    return url


def normalize_email(value: str | None) -> str | None:
    """Normalize an email for case-insensitive lookups."""
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_phone(value: str | None) -> str | None:
    """Normalize a phone number into a comparable storage format."""
    digits = digits_only(value)
    if not digits:
        return None

    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) >= 11:
        digits = digits[1:]

    if len(digits) in {10, 11}:
        return f"+55{digits}"

    if str(value or "").strip().startswith("+"):
        return f"+{digits}"
    return f"+55{digits}"


def format_cnpj(value):
    """Return a formatted CNPJ (00.000.000/0000-00)."""
    return format_cnpj_value(value)


def currency_br(value):
    """Format numeric values using the Brazilian currency style."""
    if value is None:
        value = Decimal("0")
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (ArithmeticError, ValueError):
            return str(value)
    quantized = value.quantize(Decimal("0.01"))
    formatted = f"{quantized:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def payment_status_label(value):
    """Translate payment status codes to Portuguese labels."""
    mapping = {
        "pending": "Pendente",
        "success": "Aprovado",
        "completed": "Aprovado",
        "approved": "Aprovado",
        "failure": "Falha no pagamento",
        "failed": "Falha no pagamento",
    }
    return mapping.get(value.lower(), value) if value else ""


PAYER_TYPE_LABELS = {
    "plan": "Plano",
    "particular": "Particular",
}


def payer_type_label(value):
    return PAYER_TYPE_LABELS.get(value or "particular", "Particular")


def default_payer_type_for_consulta(consulta):
    return "plan" if getattr(consulta, "health_subscription_id", None) else "particular"


def payer_label_filter(value):
    return payer_type_label(value)


def coverage_label_filter(value):
    return coverage_label(value)


def coverage_badge_filter(value):
    return coverage_badge(value)


def _resolve_species_name(species) -> str | None:
    if not species:
        return None
    name = getattr(species, "name", None)
    if isinstance(name, str) and name.strip():
        return name
    if isinstance(species, str):
        return species
    return str(species)


def species_display(species) -> str:
    """Return a readable label for a Species relationship or string."""
    return _resolve_species_name(species) or "Espécie não informada"


def _normalize_species_token(species: str | None) -> str | None:
    name = _resolve_species_name(species)
    if not name:
        return None
    normalized = unicodedata.normalize("NFKD", name)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents).strip("-")
    token = cleaned.lower()
    return token or None


_SPECIES_VISUAL_TOKENS = {
    "cao": "dog",
    "cachorro": "dog",
    "canino": "dog",
    "gato": "cat",
    "felino": "cat",
    "gata": "cat",
    "ave": "bird",
    "passaro": "bird",
    "canario": "bird",
    "papagaio": "bird",
    "coelho": "rabbit",
    "lagarto": "reptile",
    "jabuti": "reptile",
    "tartaruga": "reptile",
    "reptil": "reptile",
    "hamster": "rodent",
    "roedor": "rodent",
}


def _resolve_species_visual(species) -> str:
    token = _normalize_species_token(species)
    if not token:
        return "default"
    if token in _SPECIES_VISUAL_TOKENS:
        return _SPECIES_VISUAL_TOKENS[token]
    root = token.split("-")[0]
    return _SPECIES_VISUAL_TOKENS.get(root, "default")


def species_visual_token_filter(species) -> str:
    """Return a semantic token used to colorize and iconize species placeholders."""
    return _resolve_species_visual(species)


def _resolve_size_data(weight):
    try:
        value = float(weight)
    except (TypeError, ValueError):
        value = None

    if value is None or value <= 0:
        return "Porte indefinido", "unknown"
    if value < 10:
        return "Porte pequeno", "small"
    if value < 25:
        return "Porte médio", "medium"
    return "Porte grande", "large"


def animal_size_label(weight) -> str:
    return _resolve_size_data(weight)[0]


def animal_size_token(weight) -> str:
    return _resolve_size_data(weight)[1]


_FILTERS = {
    "date_now": date_now,
    "datetime_brazil": datetime_brazil,
    "format_datetime_brazil": format_datetime_brazil,
    "isoformat_with_tz": isoformat_with_tz,
    "format_timedelta": format_timedelta,
    "digits_only": digits_only,
    "format_cnpj": format_cnpj,
    "currency_br": currency_br,
    "payment_status_label": payment_status_label,
    "payer_label": payer_label_filter,
    "coverage_label": coverage_label_filter,
    "coverage_badge": coverage_badge_filter,
    "species_display": species_display,
    "species_visual_token": species_visual_token_filter,
    "animal_size_label": animal_size_label,
    "animal_size_token": animal_size_token,
}


def register_template_filters(app):
    for name, func in _FILTERS.items():
        app.add_template_filter(func, name)
    # Imported Jinja macros do not receive context-processor values by default.
    # Register the helper globally so the shared WhatsApp component is reliable.
    app.jinja_env.globals["whatsapp_chat_url"] = whatsapp_chat_url
