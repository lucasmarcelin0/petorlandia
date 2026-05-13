"""Utilities for normalizing and formatting Brazilian document numbers."""


def only_digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def format_cnpj(value) -> str:
    raw = "" if value is None else str(value).strip()
    digits = only_digits(raw)
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return raw
