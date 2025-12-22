import logging
import os
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

_require_tz_for_display = os.getenv("BRAZIL_TIME_REQUIRE_TZ", "0").lower() in {"1", "true", "yes"}
_logger = logging.getLogger(__name__)


def now_in_brazil() -> datetime:
    """Return current time in Brazil timezone.
    
    This function is robust against system clock issues by using UTC as the
    reference and converting to Brazil timezone.
    """
    # Get UTC time first (most reliable)
    utc_time = datetime.now(timezone.utc)
    # Convert to Brazil timezone
    return utc_time.astimezone(BR_TZ)


def utcnow() -> datetime:
    """Return current time in UTC.
    
    This uses timezone-aware UTC to ensure accuracy regardless of system timezone.
    """
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


def coerce_to_brazil_tz(value: datetime, *, allow_naive: bool | None = None) -> datetime:
    """Normalize ``value`` into a Brazil-timezone-aware ``datetime``.

    When ``allow_naive`` is ``False`` (or ``BRAZIL_TIME_REQUIRE_TZ`` is set),
    naive values raise ``ValueError`` and are logged. Otherwise, naive values
    are assumed to be expressed in Brazil's timezone to avoid shifting stored
    local datetimes when rendering.
    """

    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime, got {type(value)!r}")

    allow_naive = (not _require_tz_for_display) if allow_naive is None else allow_naive

    if value.tzinfo is None:
        if not allow_naive:
            _logger.warning("Naive datetime received where timezone-aware was required: %r", value)
            raise ValueError("Timezone-aware datetime required")
        _logger.warning("Naive datetime received; assuming America/Sao_Paulo timezone: %r", value)
        value = value.replace(tzinfo=BR_TZ)
    else:
        value = value.astimezone(BR_TZ)

    return value
