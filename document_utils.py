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
