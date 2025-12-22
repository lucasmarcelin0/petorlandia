from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")


def now_in_brazil() -> datetime:
    return datetime.now(BR_TZ)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def brazil_now_as_utc_naive() -> datetime:
    return now_in_brazil().astimezone(timezone.utc).replace(tzinfo=None)
