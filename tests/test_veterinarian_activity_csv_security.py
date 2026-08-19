import csv
import io
from datetime import date, datetime
from types import SimpleNamespace

from app import _export_veterinarian_activity_csv


def test_veterinarian_activity_csv_escapes_formula_cells(app):
    veterinario = SimpleNamespace(
        id=7,
        crmv="=CMD()",
        user=SimpleNamespace(name="+Dr Formula"),
    )
    activities = [
        {
            "timestamp": datetime(2026, 6, 23, 9, 0),
            "kind": "consulta",
            "status": "@hidden",
            "animal_name": "-Rex",
            "tutor_name": "=Tutor",
            "clinic_name": "+Clinic",
            "detail": "=HYPERLINK(\"https://evil.test\")",
            "record_id": "1",
            "detail_url": "@url",
        }
    ]

    with app.app_context():
        response = _export_veterinarian_activity_csv(
            veterinario,
            activities,
            date(2026, 6, 1),
            date(2026, 6, 23),
        )

    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))

    assert rows[0]["Veterinario"].startswith("'+")
    assert rows[0]["CRMV"].startswith("'=")
    assert rows[0]["Detalhes"].startswith("'=")
    assert rows[0]["Link"].startswith("'@")
