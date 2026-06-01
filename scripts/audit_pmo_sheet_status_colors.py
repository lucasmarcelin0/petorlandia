import argparse
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from googleapiclient.errors import HttpError

from app import app
from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit, Vacina
from services.sfa_service import _extract_google_sheet_id, _resolve_sheet_title_by_gid
from services.vacina_pmo_service import (
    DEFAULT_SHEET_URL,
    PMO_STATUS_COLORS,
    _get_sheets_service_rw,
    _parse_count,
    _parse_date_object,
    _row_column_offset,
    infer_visit_status,
    list_vacina_pmo_sheets,
    persist_vacina_pmo_rows,
    sync_vacina_pmo_sheet,
)


DATED_SHEET_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")
SKIP_TITLES = {"controle de doses", "solicitacoes", "agendadas", "encaixes", "inscrição a agendar", "inscricao a agendar", "padrão", "padrao", "copia", "interesse vacina", "teste do bot"}


def _color_tuple(color: dict[str, Any] | None) -> tuple[float, float, float] | None:
    if not color:
        return None
    return (
        round(float(color.get("red", 0.0)), 3),
        round(float(color.get("green", 0.0)), 3),
        round(float(color.get("blue", 0.0)), 3),
    )


KNOWN_COLORS = {
    _color_tuple(color): status
    for status, color in PMO_STATUS_COLORS.items()
}
KNOWN_COLORS.update({
    (0.0, 1.0, 0.0): "vacinado",
    (1.0, 1.0, 0.0): "parcial",
    (1.0, 0.0, 0.0): "recusou",
    (0.851, 0.918, 0.824): "vacinado",
    (1.0, 0.945, 0.8): "parcial",
})


def _nearest_known_status(color: dict[str, Any] | None) -> str | None:
    current = _color_tuple(color)
    if not current:
        return None
    if current in KNOWN_COLORS:
        return KNOWN_COLORS[current]
    best_status = None
    best_distance = 99.0
    for known, status in KNOWN_COLORS.items():
        distance = sum((current[index] - known[index]) ** 2 for index in range(3))
        if distance < best_distance:
            best_distance = distance
            best_status = status
    return best_status if best_distance <= 0.0005 else None


def _sheet_date(title: str) -> date | None:
    return _parse_date_object(title.strip())


def _cell_value(row: list[Any], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index].get("formattedValue", "") if isinstance(row[index], dict) else ""
    return str(value or "").strip()


def _cell_color(row: list[Any], index: int) -> dict[str, Any] | None:
    if index >= len(row):
        return None
    cell = row[index] if isinstance(row[index], dict) else {}
    return (
        cell.get("effectiveFormat", {}).get("backgroundColor")
        or cell.get("userEnteredFormat", {}).get("backgroundColor")
    )


def _row_values(row: list[Any]) -> list[str]:
    return [_cell_value(row, index) for index in range(20)]


def _vaccinated_count(row_values: list[str], species: str, offset: int) -> int:
    base_index = 12 if species == "cao" else 13
    return _parse_count(row_values[base_index + offset] if len(row_values) > base_index + offset else "")


def _fetch_sheet_rows(service, spreadsheet_id: str, sheet_title: str, sheet_gid: str) -> list[list[Any]]:
    title = sheet_title
    if not title and sheet_gid:
        title = _resolve_sheet_title_by_gid(service, spreadsheet_id, sheet_gid)
    last_error = None
    for attempt in range(4):
        try:
            metadata = (
                service.spreadsheets()
                .get(
                    spreadsheetId=spreadsheet_id,
                    ranges=[f"'{title}'!A:T"],
                    includeGridData=True,
                )
                .execute()
            )
            break
        except HttpError as exc:
            last_error = exc
            if exc.resp.status not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    else:
        raise last_error
    sheets = metadata.get("sheets", [])
    if not sheets:
        return []
    data = sheets[0].get("data", [])
    if not data:
        return []
    return [row.get("values", []) for row in data[0].get("rowData", [])]


def _status_from_row(row: list[Any], row_values: list[str], offset: int) -> str | None:
    color_indexes = [0 + offset, 0]
    for index in color_indexes:
        status = _nearest_known_status(_cell_color(row, index))
        if status:
            return status
    for cell_index in range(min(len(row), 20)):
        status = _nearest_known_status(_cell_color(row, cell_index))
        if status:
            return status
    return None


def _apply_row_status(visit: PmoVaccinationVisit, sheet_status: str, row_values: list[str], offset: int) -> bool:
    changed = False
    visit_date = visit.vaccine_date or _sheet_date(visit.sheet_title)
    dogs_vaccinated = _vaccinated_count(row_values, "cao", offset)
    cats_vaccinated = _vaccinated_count(row_values, "gato", offset)
    remaining_by_species = {
        "cao": dogs_vaccinated,
        "gato": cats_vaccinated,
    }

    for animal in visit.animals:
        wanted_status = animal.status
        if sheet_status == "vacinado":
            wanted_status = "vacinado"
        elif sheet_status in {"recusou", "ausente"}:
            wanted_status = "recusou" if sheet_status == "recusou" else "ausente"
        elif sheet_status == "parcial":
            if remaining_by_species.get(animal.species, 0) > 0:
                wanted_status = "vacinado"
                remaining_by_species[animal.species] -= 1
            elif dogs_vaccinated or cats_vaccinated:
                wanted_status = "remarcar"
            else:
                continue

        if animal.status != wanted_status:
            animal.status = wanted_status
            changed = True
        if wanted_status == "vacinado" and visit_date and not animal.vaccinated_at:
            animal.vaccinated_at = datetime.combine(visit_date, datetime.min.time())
            changed = True
        if wanted_status != "vacinado":
            if animal.vaccinated_at:
                animal.vaccinated_at = None
                changed = True
            if animal.vaccine_id:
                vaccine = db.session.get(Vacina, animal.vaccine_id)
                animal.vaccine_id = None
                if vaccine and vaccine.tipo == "Campanha PMO":
                    db.session.delete(vaccine)
                changed = True
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Atualiza os status no banco.")
    parser.add_argument("--limit-sheets", type=int, default=0)
    args = parser.parse_args()

    with app.app_context():
        service = _get_sheets_service_rw()
        spreadsheet_id = _extract_google_sheet_id(DEFAULT_SHEET_URL)
        if not spreadsheet_id:
            raise RuntimeError("Planilha PMO inválida.")

        summary = Counter()
        examples = defaultdict(list)
        sheets = [
            sheet for sheet in list_vacina_pmo_sheets()
            if DATED_SHEET_RE.match(sheet.get("title") or "")
            and (sheet.get("title") or "").strip().lower() not in SKIP_TITLES
        ]
        if args.limit_sheets:
            sheets = sheets[:args.limit_sheets]

        for sheet in sheets:
            title = sheet.get("title") or ""
            gid = sheet.get("gid") or ""
            sync_result = sync_vacina_pmo_sheet(sheet_gid=gid, sheet_title=title)
            persist_vacina_pmo_rows(
                sync_result.rows,
                spreadsheet_id=sync_result.spreadsheet_id,
                sheet_gid=sync_result.sheet_gid,
                sheet_title=sync_result.sheet_title,
            )
            rows = _fetch_sheet_rows(service, spreadsheet_id, title, gid)
            visits = {
                visit.source_row: visit
                for visit in PmoVaccinationVisit.query.filter_by(
                    spreadsheet_id=spreadsheet_id,
                    sheet_gid=gid,
                ).all()
            }
            for source_row, visit in visits.items():
                if source_row <= 0 or source_row > len(rows):
                    continue
                row = rows[source_row - 1]
                row_values = _row_values(row)
                offset = _row_column_offset(row_values)
                sheet_status = _status_from_row(row, row_values, offset)
                if not sheet_status:
                    summary["sem_cor"] += 1
                    continue

                current_status = infer_visit_status(visit.animals)
                summary[f"cor_{sheet_status}"] += 1
                if current_status == sheet_status or (
                    sheet_status == "parcial" and current_status in {"parcial", "remarcar"}
                ):
                    summary["ja_batia"] += 1
                    continue

                summary["divergente"] += 1
                if len(examples[sheet_status]) < 8:
                    examples[sheet_status].append(
                        f"{title} linha {source_row}: {visit.tutor_name} | planilha={sheet_status} banco={current_status}"
                    )
                if args.apply and _apply_row_status(visit, sheet_status, row_values, offset):
                    for animal in visit.animals:
                        if animal.status == "vacinado":
                            from services.vacina_pmo_service import _ensure_pmo_vaccine_record

                            _ensure_pmo_vaccine_record(animal)
                    summary["atualizado"] += 1

            if args.apply:
                db.session.commit()

        print("RESUMO")
        for key, value in sorted(summary.items()):
            print(f"{key}: {value}")
        if examples:
            print("EXEMPLOS")
            for status, rows in examples.items():
                for row in rows:
                    print(f"{status}: {row}")


if __name__ == "__main__":
    main()
