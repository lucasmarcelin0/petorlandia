import argparse
import logging
import os
import sys
from collections import Counter
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from extensions import db
from models import PmoVaccinationVisit
from services.sfa_service import _extract_google_sheet_id
from services.vacina_pmo_service import (
    DEFAULT_SHEET_URL,
    _ensure_pmo_vaccine_record,
    _get_sheets_service_rw,
    _row_column_offset,
    infer_visit_status,
    list_vacina_pmo_sheets,
)

from scripts.audit_pmo_sheet_status_colors import (
    _apply_row_status,
    _fetch_sheet_rows,
    _row_values,
    _status_from_row,
)
from scripts.sync_pmo_master_status_notes import (
    MASTER_SHEET_TITLE,
    _build_requests,
    _build_visit_index,
    _chunked,
    _matching_visits,
    _overall_status,
    _resolve_sheet_id_by_title,
    _retry_execute,
    _sync_relevant_sheets,
)


log = logging.getLogger(__name__)


def _find_sheet(title: str) -> dict[str, Any] | None:
    wanted = title.strip().lower()
    for sheet in list_vacina_pmo_sheets():
        if (sheet.get("title") or "").strip().lower() == wanted:
            return sheet
    return None


def _apply_encaixes_colors(service, spreadsheet_id: str) -> Counter:
    summary: Counter = Counter()
    sheet = _find_sheet("Encaixes")
    if not sheet:
        summary["encaixes_nao_encontrada"] += 1
        return summary

    title = sheet.get("title") or "Encaixes"
    gid = sheet.get("gid") or ""
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
        sheet_status = _status_from_row(row, row_values, offset, title)
        if not sheet_status:
            summary["encaixes_sem_cor"] += 1
            continue

        summary[f"encaixes_cor_{sheet_status}"] += 1
        current_status = infer_visit_status(visit.animals)
        if current_status == sheet_status or (
            sheet_status == "parcial" and current_status in {"parcial", "remarcar"}
        ):
            summary["encaixes_ja_batia"] += 1
            continue

        if _apply_row_status(visit, sheet_status, row_values, offset):
            for animal in visit.animals:
                if animal.status == "vacinado":
                    _ensure_pmo_vaccine_record(animal)
            summary["encaixes_atualizado"] += 1

    db.session.commit()
    return summary


def _apply_master_status(service, spreadsheet_id: str) -> Counter:
    summary: Counter = Counter()
    master_visits = (
        PmoVaccinationVisit.query
        .filter(PmoVaccinationVisit.sheet_title == MASTER_SHEET_TITLE)
        .order_by(PmoVaccinationVisit.source_row.asc())
        .all()
    )
    all_visits = PmoVaccinationVisit.query.all()
    by_phone, by_name, by_user = _build_visit_index(all_visits)
    match_map = {
        visit.id: _matching_visits(visit, by_phone=by_phone, by_name=by_name, by_user=by_user)
        for visit in master_visits
    }
    status_counts = Counter(_overall_status(matches) for matches in match_map.values())
    matched_count = sum(1 for matches in match_map.values() if matches)

    sheet_ids = _resolve_sheet_id_by_title(service, spreadsheet_id)
    master_sheet_id = sheet_ids.get(MASTER_SHEET_TITLE)
    if master_sheet_id is None:
        raise RuntimeError(f"Aba {MASTER_SHEET_TITLE!r} nao encontrada.")

    requests = _build_requests(master_sheet_id, master_visits, match_map)
    for chunk in _chunked(requests, 200):
        _retry_execute(
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": chunk},
            )
        )

    summary["linhas_mestre"] = len(master_visits)
    summary["linhas_com_match"] = matched_count
    summary["requests_mestre"] = len(requests)
    for status, count in status_counts.items():
        summary[f"status_{status}"] = count
    return summary


def run_pmo_full_sync(*, apply: bool = True, skip_sheet_sync: bool = False) -> dict[str, int]:
    with app.app_context():
        service = _get_sheets_service_rw()
        spreadsheet_id = _extract_google_sheet_id(DEFAULT_SHEET_URL)
        if not spreadsheet_id:
            raise RuntimeError("Planilha PMO invalida.")

        summary: Counter = Counter()
        if not skip_sheet_sync:
            synced_sheets, synced_rows = _sync_relevant_sheets()
            summary["abas_sincronizadas"] = synced_sheets
            summary["linhas_sincronizadas"] = synced_rows

        if apply:
            summary.update(_apply_encaixes_colors(service, spreadsheet_id))
            summary.update(_apply_master_status(service, spreadsheet_id))

        return dict(summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Relê as abas, mas não grava cores/status na planilha mestre.")
    parser.add_argument("--skip-sheet-sync", action="store_true", help="Usa o banco como está, sem reler as abas.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    result = run_pmo_full_sync(apply=not args.dry_run, skip_sheet_sync=args.skip_sheet_sync)
    for key, value in sorted(result.items()):
        log.info("%s: %s", key, value)


if __name__ == "__main__":
    main()
