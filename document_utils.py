"""Utilities for normalizing and formatting Brazilian document numbers."""


def only_digits(value) -> str:
    """Extrai apenas os dígitos de um valor com fast-path seguro para números e strings."""
    if not value:
        return ""
    if isinstance(value, str):
        if value.isdigit():
            return value
        return "".join([c for c in value if c.isdigit()])
    s = str(value)
    if s.isdigit():
        return s
    return "".join([c for c in s if c.isdigit()])


def format_cnpj(value) -> str:
    raw = "" if value is None else str(value).strip()
    digits = only_digits(raw)
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return raw


# --- CPF e telefone ---------------------------------------------------------
#
# O banco guarda o mesmo dado em formatos diferentes conforme a tela que o
# gravou: "36243026809" e "362.430.268-09"; "16992690405", "(16) 99269-0405" e
# "+5516992690405". Por isso nenhuma tela pode exigir um formato: quem compara
# usa os dígitos, quem mostra usa format_*, e quem grava usa normalize_*.


def format_cpf(value) -> str:
    """CPF como ``000.000.000-00``; o que não tiver 11 dígitos volta intacto."""
    raw = "" if value is None else str(value).strip()
    digits = only_digits(raw)
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return raw


def normalize_cpf(value) -> str:
    """Forma de gravação do CPF: só os 11 dígitos (ou o texto, se não for CPF)."""
    raw = "" if value is None else str(value).strip()
    digits = only_digits(raw)
    return digits if len(digits) == 11 else raw


def is_valid_cpf_length(value) -> bool:
    return len(only_digits(value)) == 11


def phone_national_digits(value) -> str:
    """DDD + número de um telefone brasileiro, ou ``""`` se não for um.

    Aceita o que as telas e as importações já gravaram: com máscara, com
    ``+55`` na frente e com o zero de tronco (``016...``).
    """
    raw = "" if value is None else str(value).strip()
    digits = only_digits(raw)
    if raw.startswith("+") and not digits.startswith("55"):
        return ""  # número de outro país
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    if len(digits) in (11, 12) and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) in (10, 11) else ""


def format_phone_br(value) -> str:
    """Telefone como ``(16) 99269-0405``; o que não for brasileiro volta intacto."""
    raw = "" if value is None else str(value).strip()
    digits = phone_national_digits(raw)
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return raw


def normalize_phone(value) -> str:
    """Forma de gravação do telefone: DDD + número; estrangeiro fica como veio."""
    raw = "" if value is None else str(value).strip()
    return phone_national_digits(raw) or raw


def is_valid_phone(value) -> bool:
    raw = "" if value is None else str(value).strip()
    if phone_national_digits(raw):
        return True
    return raw.startswith("+") and 8 <= len(only_digits(raw)) <= 15


def same_cpf(a, b) -> bool:
    """Mesmo documento, qualquer que seja a máscara."""
    da, db_ = only_digits(a), only_digits(b)
    if da or db_:
        return da == db_
    return (a or "").strip() == (b or "").strip()


def same_phone(a, b) -> bool:
    """Mesmo número, com ou sem máscara, ``+55`` ou zero de tronco."""
    na, nb = phone_national_digits(a), phone_national_digits(b)
    if na or nb:
        return na == nb
    return only_digits(a) == only_digits(b)
