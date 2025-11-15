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
