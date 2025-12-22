import os
import sys
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from datetime import datetime, date, timezone

from app import format_datetime_brazil, isoformat_with_tz


def test_format_datetime_brazil_with_date():
    d = date(2024, 1, 31)
    assert format_datetime_brazil(d, "%d/%m/%Y") == "31/01/2024"


def test_format_datetime_brazil_with_datetime():
    dt = datetime(2024, 1, 31, 15, 0, tzinfo=timezone.utc)
    out = format_datetime_brazil(dt, "%d/%m/%Y %H:%M")
    assert "31/01/2024" in out


def test_format_datetime_brazil_with_utc_aware_datetime():
    dt = datetime(2024, 5, 1, 3, 0, tzinfo=timezone.utc)
    out = format_datetime_brazil(dt, "%d/%m/%Y %H:%M")
    assert out.startswith("01/05/2024")


def test_format_datetime_brazil_with_naive_utc_value():
    dt = datetime(2024, 5, 1, 1, 0)
    out = format_datetime_brazil(dt, "%d/%m/%Y %H:%M")
    assert out.startswith("01/05/2024")


def test_format_datetime_brazil_with_naive_brt_value():
    dt = datetime(2024, 5, 1, 0, 30)
    out = format_datetime_brazil(dt, "%d/%m/%Y %H:%M")
    assert out.startswith("01/05/2024")


def test_isoformat_with_tz_returns_utc_z():
    dt = datetime(2024, 12, 25, 15, 30, tzinfo=timezone.utc)
    iso_out = isoformat_with_tz(dt)
    assert iso_out.endswith('Z')
    assert iso_out.startswith('2024-12-25T15:30')
