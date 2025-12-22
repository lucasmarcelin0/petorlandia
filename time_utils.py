from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


def _coerce_to_datetime(value: datetime | date | str) -> datetime:
    """Convert ``value`` into a ``datetime`` instance."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"Unsupported datetime string: {value!r}") from exc
    raise TypeError(f"Unsupported datetime-like value: {type(value)!r}")

BR_TZ = ZoneInfo("America/Sao_Paulo")


def now_in_brazil() -> datetime:
    return datetime.now(BR_TZ)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def brazil_now_as_utc_naive() -> datetime:
    return now_in_brazil().astimezone(timezone.utc).replace(tzinfo=None)


def normalize_to_utc(value, *, local_tz: ZoneInfo = BR_TZ) -> datetime:
    """Return a timezone-aware UTC ``datetime`` for persistence.

    Any accepted input (``datetime``, ``date`` or ISO-formatted ``str``)
    is first coerced to Brazil's timezone and then converted to UTC. Naive
    datetimes are assumed to be expressed in the provided ``local_tz``.
    """

    dt_value = _coerce_to_datetime(value)
    if dt_value.tzinfo is None:
        localized = dt_value.replace(tzinfo=local_tz)
    else:
        localized = dt_value.astimezone(local_tz)
    return localized.astimezone(timezone.utc)
