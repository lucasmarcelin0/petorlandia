import os
import sys
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from datetime import datetime, date, timezone

from app import format_datetime_brazil


def test_format_datetime_brazil_with_date():
    d = date(2024, 1, 31)
    assert format_datetime_brazil(d, "%d/%m/%Y") == "31/01/2024"


def test_format_datetime_brazil_with_datetime():
    dt = datetime(2024, 1, 31, 15, 0, tzinfo=timezone.utc)
    out = format_datetime_brazil(dt, "%d/%m/%Y %H:%M")
    assert "31/01/2024" in out
