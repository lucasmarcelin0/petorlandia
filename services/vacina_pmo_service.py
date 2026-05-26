"""Google Sheets sync helpers for the PMO rabies vaccination campaign."""

from __future__ import annotations

import os
import re
import secrets
import string
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services.sfa_service import (
    _extract_google_sheet_id,
    _get_sheets_service,
    _resolve_sheet_title_by_gid,
)
from time_utils import utcnow


DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1oN74lysYpQOIYgS9nlyrQUgxa0w1FHS7yGVftpzbqAk/edit?gid=2076484491#gid=2076484491"
)
DEFAULT_SHEET_RANGE = "A:T"


@dataclass
class PmoSyncResult:
    rows: list[dict[str, Any]]
    spreadsheet_id: str
    sheet_range: str
    sheet_gid: str
    sheet_title: str


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _parse_count(value: Any) -> int:
    text = _normalize_text(value)
    if not re.fullmatch(r"\d{1,2}", text):
        return 0
    parsed = int(text)
    return parsed if 0 <= parsed <= 30 else 0


def _normalize_phone(value: Any) -> str:
    digits = _digits(value)
    if not digits or digits == "0":
        return ""
    if len(digits) in {8, 9}:
        digits = f"16{digits}"
    if not digits.startswith("55"):
        digits = f"55{digits}"
    return digits if len(digits) >= 12 else ""


def _parse_date(value: Any) -> str:
    text = _normalize_text(value)
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def _parse_date_object(value: Any) -> date | None:
    text = _parse_date(value)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_shift(value: Any) -> str:
    text = _strip_accents(_normalize_text(value)).lower()
    if text.startswith("man"):
        return "Manha"
    if text.startswith("tar"):
        return "Tarde"
    return _normalize_text(value)


def _is_summary_or_header(row: list[Any]) -> bool:
    values = [_normalize_text(item) for item in row]
    joined = " ".join(values).lower()
    first = values[0] if values else ""
    if not joined:
        return True
    if not re.search(r"[a-zA-ZÀ-ú]", first):
        return True
    return any(
        marker in joined
        for marker in (
            "nome completo do tutor",
            "total de animais",
            "digite o dia",
            "perdas",
            "sobras",
        )
    )


def _split_animals(value: Any) -> list[str]:
    text = _normalize_text(value)
    if not text:
        return []
    return [
        _normalize_text(item)
        for item in re.split(r",|;|\n|\se\s", text, flags=re.IGNORECASE)
        if _normalize_text(item)
    ]


def _build_animals(names: list[str], dogs: int, cats: int) -> list[dict[str, str]]:
    total = max(len(names), dogs + cats)
    animals: list[dict[str, str]] = []
    for index in range(total):
        species = "cao" if index < dogs else "gato"
        fallback = f"Cao {index + 1}" if species == "cao" else f"Gato {index - dogs + 1}"
        animals.append(
            {
                "name": names[index] if index < len(names) else fallback,
                "species": species,
                "status": "pendente",
            }
        )
    return animals


def _cell(row: list[Any], index: int) -> str:
    return _normalize_text(row[index]) if len(row) > index else ""


def _password(seed: str) -> str:
    suffix = (_digits(seed)[-4:] or "0000").rjust(4, "0")
    letter = secrets.choice(string.ascii_uppercase.replace("I", "").replace("O", ""))
    return f"PMO{letter}{suffix}"


def parse_vacina_pmo_rows(values: list[list[Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(values):
        if _is_summary_or_header(row):
            continue

        tutor = _cell(row, 0)
        phone1 = _normalize_phone(_cell(row, 5))
        phone2 = _normalize_phone(_cell(row, 6))
        dogs = _parse_count(_cell(row, 7))
        cats = _parse_count(_cell(row, 8))
        animals = _build_animals(_split_animals(_cell(row, 9)), dogs, cats)
        address = ", ".join(
            item for item in (_cell(row, 1), _cell(row, 2), _cell(row, 3), _cell(row, 4)) if item
        )

        if not tutor or not (phone1 or phone2 or address) or not (dogs or cats or animals):
            continue

        parsed.append(
            {
                "id": f"sheet-{index}",
                "status": "pendente",
                "tutor": tutor,
                "address": address,
                "phone1": phone1,
                "phone2": phone2,
                "dogs": dogs,
                "cats": cats,
                "animals": animals,
                "note": _cell(row, 10),
                "date": _parse_date(_cell(row, 16) or _cell(row, 11)),
                "shift": _normalize_shift(_cell(row, 17)),
                "password": _password(phone1 or phone2 or str(index)),
                "certificateUrl": "",
                "sourceRow": index + 1,
            }
        )
    return parsed


def _extract_gid(value: str) -> str:
    match = re.search(r"(?:gid=|#gid=)(\d+)", value or "")
    return match.group(1) if match else ""


def _quote_sheet_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _resolve_sheet_target(
    service,
    sheet_url: str,
    range_value: str,
    *,
    sheet_gid: str = "",
    sheet_title: str = "",
) -> tuple[str, str, str, str]:
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO invalido.")

    gid = sheet_gid or os.getenv("PMO_VACCINE_SHEET_GID", "") or _extract_gid(sheet_url)
    title = sheet_title or os.getenv("PMO_VACCINE_SHEET_TITLE", "")
    if title:
        return spreadsheet_id, f"{_quote_sheet_title(title)}!{range_value}", gid, title
    if gid:
        resolved = _resolve_sheet_title_by_gid(service, spreadsheet_id, gid)
        return spreadsheet_id, f"{_quote_sheet_title(resolved)}!{range_value}", gid, resolved
    return spreadsheet_id, range_value, "", ""


def list_vacina_pmo_sheets() -> list[dict[str, Any]]:
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    service = _get_sheets_service()
    spreadsheet_id = _extract_google_sheet_id(sheet_url)
    if not spreadsheet_id:
        raise RuntimeError("URL/ID da planilha PMO invalido.")
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
        .execute()
    )
    sheets = []
    for sheet in metadata.get("sheets", []):
        props = sheet.get("properties", {})
        title = props.get("title", "")
        if not title:
            continue
        sheets.append(
            {
                "title": title,
                "gid": str(props.get("sheetId", "")),
                "date": _parse_date(title),
            }
        )
    return sheets


def infer_visit_status(animals: list[dict[str, Any]] | list[PmoVaccinationAnimal]) -> str:
    if not animals:
        return "pendente"
    statuses = [
        animal.get("status", "pendente") if isinstance(animal, dict) else (animal.status or "pendente")
        for animal in animals
    ]
    if all(status == "vacinado" for status in statuses):
        return "vacinado"
    if any(status == "vacinado" for status in statuses):
        return "parcial"
    if all(status == "ausente" for status in statuses):
        return "ausente"
    if all(status == "recusou" for status in statuses):
        return "recusou"
    if any(status == "remarcar" for status in statuses):
        return "remarcar"
    return "pendente"


def _serialize_visit(visit: PmoVaccinationVisit) -> dict[str, Any]:
    animals = [
        {
            "id": animal.id,
            "name": animal.name,
            "species": animal.species,
            "status": animal.status,
        }
        for animal in visit.animals
    ]
    return {
        "id": f"visit-{visit.id}",
        "visitId": visit.id,
        "status": infer_visit_status(animals),
        "tutor": visit.tutor_name,
        "address": visit.address or "",
        "phone1": visit.phone1 or "",
        "phone2": visit.phone2 or "",
        "dogs": visit.dogs or 0,
        "cats": visit.cats or 0,
        "animals": animals,
        "note": visit.note or "",
        "date": visit.vaccine_date.isoformat() if visit.vaccine_date else "",
        "shift": visit.shift or "",
        "password": visit.password,
        "certificateUrl": visit.certificate_url or "",
        "sourceRow": visit.source_row,
    }


def _query_sheet_visits(
    *,
    sheet_gid: str = "",
    sheet_title: str = "",
    spreadsheet_id: str = "",
):
    query = PmoVaccinationVisit.query
    if spreadsheet_id:
        query = query.filter(PmoVaccinationVisit.spreadsheet_id == spreadsheet_id)
    if sheet_gid:
        query = query.filter(PmoVaccinationVisit.sheet_gid == sheet_gid)
    if sheet_title:
        query = query.filter(PmoVaccinationVisit.sheet_title == sheet_title)
    return query


def get_saved_vacina_pmo_rows(*, sheet_gid: str = "", sheet_title: str = "") -> dict[str, Any]:
    latest = None
    if not sheet_gid and not sheet_title:
        latest = PmoVaccinationVisit.query.order_by(PmoVaccinationVisit.updated_at.desc()).first()
        if latest:
            sheet_gid = latest.sheet_gid
            sheet_title = latest.sheet_title

    visits = (
        _query_sheet_visits(sheet_gid=sheet_gid, sheet_title=sheet_title)
        .order_by(PmoVaccinationVisit.source_row.asc(), PmoVaccinationVisit.id.asc())
        .all()
    )
    return {
        "rows": [_serialize_visit(visit) for visit in visits],
        "sheet_gid": sheet_gid or (latest.sheet_gid if latest else ""),
        "sheet_title": sheet_title or (latest.sheet_title if latest else ""),
        "spreadsheet_id": visits[0].spreadsheet_id if visits else "",
    }


def persist_vacina_pmo_rows(
    rows: list[dict[str, Any]],
    *,
    spreadsheet_id: str,
    sheet_gid: str,
    sheet_title: str,
) -> list[dict[str, Any]]:
    now = utcnow()
    saved: list[PmoVaccinationVisit] = []
    for row in rows:
        source_row = int(row.get("sourceRow") or 0)
        if source_row <= 0:
            continue

        visit = (
            PmoVaccinationVisit.query.filter_by(
                spreadsheet_id=spreadsheet_id,
                sheet_gid=sheet_gid,
                source_row=source_row,
            )
            .first()
        )
        if not visit:
            visit = PmoVaccinationVisit(
                spreadsheet_id=spreadsheet_id,
                sheet_gid=sheet_gid,
                source_row=source_row,
                password=row.get("password") or _password(row.get("phone1") or row.get("phone2") or source_row),
            )
            db.session.add(visit)

        visit.sheet_title = sheet_title
        visit.tutor_name = row.get("tutor") or ""
        visit.address = row.get("address") or ""
        visit.phone1 = row.get("phone1") or ""
        visit.phone2 = row.get("phone2") or ""
        visit.dogs = int(row.get("dogs") or 0)
        visit.cats = int(row.get("cats") or 0)
        visit.vaccine_date = _parse_date_object(row.get("date"))
        visit.shift = row.get("shift") or ""
        visit.note = row.get("note") or ""
        visit.synced_at = now

        existing_by_position = {animal.position: animal for animal in visit.animals}
        parsed_animals = row.get("animals") or []
        keep_positions = set()
        for position, animal_data in enumerate(parsed_animals, start=1):
            animal = existing_by_position.get(position)
            if not animal:
                animal = PmoVaccinationAnimal(
                    visit=visit,
                    position=position,
                    status=animal_data.get("status") or "pendente",
                )
                db.session.add(animal)
            animal.name = animal_data.get("name") or f"Animal {position}"
            animal.species = animal_data.get("species") or "cao"
            keep_positions.add(position)

        for position, animal in list(existing_by_position.items()):
            if position not in keep_positions:
                db.session.delete(animal)

        saved.append(visit)

    db.session.commit()
    return [_serialize_visit(visit) for visit in saved]


def update_vacina_pmo_animal_status(animal_id: int, status: str) -> dict[str, Any]:
    allowed = {"pendente", "vacinado", "ausente", "remarcar", "recusou"}
    if status not in allowed:
        raise ValueError("Status invalido.")
    animal = PmoVaccinationAnimal.query.get_or_404(animal_id)
    animal.status = status
    animal.vaccinated_at = utcnow() if status == "vacinado" else None
    db.session.commit()
    return _serialize_visit(animal.visit)


def sync_vacina_pmo_sheet(*, sheet_gid: str = "", sheet_title: str = "") -> PmoSyncResult:
    sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
    range_value = os.getenv("PMO_VACCINE_SHEET_RANGE", DEFAULT_SHEET_RANGE)
    service = _get_sheets_service()
    spreadsheet_id, sheet_range, resolved_gid, resolved_title = _resolve_sheet_target(
        service,
        sheet_url,
        range_value,
        sheet_gid=sheet_gid,
        sheet_title=sheet_title,
    )
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=sheet_range)
        .execute()
    )
    rows = parse_vacina_pmo_rows(result.get("values", []))
    return PmoSyncResult(
        rows=rows,
        spreadsheet_id=spreadsheet_id,
        sheet_range=sheet_range,
        sheet_gid=resolved_gid,
        sheet_title=resolved_title,
    )
