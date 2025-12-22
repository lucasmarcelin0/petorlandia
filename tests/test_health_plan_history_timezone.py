from datetime import datetime, timezone

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.health_plan import _serialize_usage_timestamp
from time_utils import BR_TZ


def test_usage_timestamp_serialization_produces_utc_iso_and_localized_dt():
    naive_local = datetime(2025, 12, 22, 15, 30)

    utc_iso, localized = _serialize_usage_timestamp(naive_local)

    # API/JS should receive explicit timezone info (UTC with Z suffix)
    assert utc_iso.endswith("Z")
    parsed_utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    assert parsed_utc.tzinfo == timezone.utc
    # Local -> UTC adds 3h during standard time in Sao Paulo
    assert parsed_utc.hour == 18

    # Server-side formatting keeps the local Sao Paulo clock time
    assert localized.tzinfo == BR_TZ
    assert localized.hour == naive_local.hour
