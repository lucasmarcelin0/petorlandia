import os
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from zoneinfo import ZoneInfo

from helpers import BR_TZ, group_appointments_by_day


class AppointmentStub:
    def __init__(self, scheduled_at, label):
        self.scheduled_at = scheduled_at
        self.label = label


def test_group_appointments_uses_local_date():
    utc = ZoneInfo("UTC")
    midday_local = datetime(2024, 5, 1, 12, 0, tzinfo=BR_TZ)
    midday_utc = midday_local.astimezone(utc).replace(tzinfo=None)
    late_local = datetime(2024, 5, 1, 22, 0, tzinfo=BR_TZ)
    late_utc = late_local.astimezone(utc).replace(tzinfo=None)

    appointments = [
        AppointmentStub(midday_utc, "midday"),
        AppointmentStub(late_utc, "late"),
    ]

    grouped = group_appointments_by_day(appointments)

    assert len(grouped) == 1
    day, items = grouped[0]
    assert day == midday_local.date()
    assert [appt.label for appt in items] == ["midday", "late"]


def test_group_appointments_multiple_days():
    utc = ZoneInfo("UTC")

    day1_local = datetime(2024, 5, 1, 10, 0, tzinfo=BR_TZ)
    day1_utc = day1_local.astimezone(utc).replace(tzinfo=None)

    day2_local = datetime(2024, 5, 2, 10, 0, tzinfo=BR_TZ)
    day2_utc = day2_local.astimezone(utc).replace(tzinfo=None)

    day3_local = datetime(2024, 5, 3, 10, 0, tzinfo=BR_TZ)
    day3_utc = day3_local.astimezone(utc).replace(tzinfo=None)

    appointments = [
        AppointmentStub(day3_utc, "day3"),
        AppointmentStub(day1_utc, "day1"),
        AppointmentStub(day2_utc, "day2"),
        AppointmentStub(day1_utc, "day1_2"),
    ]

    grouped = group_appointments_by_day(appointments)

    assert len(grouped) == 3

    assert grouped[0][0] == day1_local.date()
    assert [appt.label for appt in grouped[0][1]] == ["day1", "day1_2"]

    assert grouped[1][0] == day2_local.date()
    assert [appt.label for appt in grouped[1][1]] == ["day2"]

    assert grouped[2][0] == day3_local.date()
    assert [appt.label for appt in grouped[2][1]] == ["day3"]
