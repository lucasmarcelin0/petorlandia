"""Utilities for normalizing and formatting Brazilian document numbers."""


def only_digits(value) -> str:
    """Extract digits from value with fast-path short-circuiting for numeric strings."""
    if value is None or value == 0:
        return ""
    if isinstance(value, str):
        if value.isdigit():
            return value
        return "".join([c for c in value if c.isdigit()])
    val_str = str(value)
    if val_str.isdigit():
        return val_str
    return "".join([c for c in val_str if c.isdigit()])


def format_cnpj(value) -> str:
    raw = "" if value is None else str(value).strip()
    digits = only_digits(raw)
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return raw
