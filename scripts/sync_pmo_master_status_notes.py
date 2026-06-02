import argparse
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from googleapiclient.errors import HttpError

from app import app
from models import PmoVaccinationVisit
from services.sfa_service import _extract_google_sheet_id
from services.vacina_pmo_service import (
    DEFAULT_SHEET_URL,
    PMO_STATUS_CLEAR_COLOR,
    PMO_STATUS_COLORS,
    _get_sheets_service_rw,
    _parse_date_object,
    infer_visit_status,
    list_vacina_pmo_sheets,
    persist_vacina_pmo_rows,
    sync_vacina_pmo_sheet,
)


MASTER_SHEET_TITLE = "Vacinação 2026"
TIMESTAMP_COLUMN_INDEX = 0
STATUS_LINK_COLUMN_INDEX = 12
DATED_SHEET_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")
AUXILIARY_TITLES = {
    "controle de doses",
    "padrão",
    "padrao",
    "copia",
    "interesse vacina",
    "teste do bot",
}
TRACKED_NON_DATE_TITLES = {
    "solicitacoes",
    "agendadas",
    "encaixes",
    "inscrição a agendar",
    "inscricao a agendar",
}
STATUS_LABELS = {
    "vacinado": "Vacinado",
    "parcial": "Parcial",
    "remarcar": "Remarcar",
    "recusou": "Cancelado/recusou",
    "ausente": "Ausente",
    "pendente": "Pendente",
    "agendado": "Agendado",
    "perdeu_contato": "Perdeu contato",
    "reagendar": "Reagendar",
}
STATUS_COLORS = {
    "vacinado": PMO_STATUS_COLORS["vacinado"],
    "parcial": PMO_STATUS_COLORS["parcial"],
    "remarcar": PMO_STATUS_COLORS["parcial"],
    "recusou": PMO_STATUS_COLORS["recusou"],
    "ausente": PMO_STATUS_COLORS["ausente"],
    "pendente": PMO_STATUS_CLEAR_COLOR,
    "sem_registro": PMO_STATUS_CLEAR_COLOR,
    "agendado": PMO_STATUS_CLEAR_COLOR,
    "perdeu_contato": PMO_STATUS_COLORS["parcial"],
    "reagendar": PMO_STATUS_CLEAR_COLOR,
}


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    )


def _normalize_text_key(value: str) -> str:
    text = _strip_accents(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _phone_keys(visit: PmoVaccinationVisit) -> set[str]:
    keys = set()
    for phone in (visit.phone1, visit.phone2):
        digits = _digits(phone)
        if len(digits) >= 8:
            keys.add(digits[-8:])
        if len(digits) >= 10:
            keys.add(digits[-10:])
        if len(digits) >= 11:
            keys.add(digits[-11:])
    return keys


def _name_key(visit: PmoVaccinationVisit) -> str:
    return _normalize_text_key(visit.tutor_name or "")


def _name_tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalize_text_key(value).split()
        if len(token) >= 3
    }


def _names_compatible(left: PmoVaccinationVisit, right: PmoVaccinationVisit) -> bool:
    left_key = _name_key(left)
    right_key = _name_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if left_key in right_key or right_key in left_key:
        return True
    left_tokens = _name_tokens(left.tutor_name or "")
    right_tokens = _name_tokens(right.tutor_name or "")
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    return smaller >= 2 and (overlap / smaller) >= 0.75


def _animal_names(visit: PmoVaccinationVisit) -> str:
    names = [animal.name for animal in visit.animals if animal.name]
    return ", ".join(names) if names else "sem pets na linha"


def _sheet_sort_key(visit: PmoVaccinationVisit) -> tuple[int, date, str, int]:
    parsed_date = _parse_date_object((visit.sheet_title or "").strip())
    if parsed_date:
        return (0, parsed_date, visit.sheet_title or "", visit.source_row or 0)
    return (1, date.max, visit.sheet_title or "", visit.source_row or 0)


def _should_sync_sheet(title: str) -> bool:
    normalized = _normalize_text_key(title)
    if normalized in AUXILIARY_TITLES:
        return False
    return title == MASTER_SHEET_TITLE or DATED_SHEET_RE.match(title or "") or normalized in TRACKED_NON_DATE_TITLES


def _is_encaixes(visit: PmoVaccinationVisit) -> bool:
    return _normalize_text_key(visit.sheet_title or "") == "encaixes"


def _retry_execute(request, *, attempts: int = 4):
    last_error = None
    for attempt in range(attempts):
        try:
            return request.execute()
        except HttpError as exc:
            last_error = exc
            if exc.resp.status not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise last_error


def _resolve_sheet_id_by_title(service, spreadsheet_id: str) -> dict[str, int]:
    metadata = _retry_execute(
        service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
    )
    return {
        sheet["properties"].get("title", ""): int(sheet["properties"].get("sheetId"))
        for sheet in metadata.get("sheets", [])
        if sheet.get("properties", {}).get("title")
    }


def _sync_relevant_sheets() -> tuple[int, int]:
    total_sheets = 0
    total_rows = 0
    for sheet in list_vacina_pmo_sheets():
        title = sheet.get("title") or ""
        if not _should_sync_sheet(title):
            continue
        result = sync_vacina_pmo_sheet(sheet_gid=sheet.get("gid") or "", sheet_title=title)
        saved = persist_vacina_pmo_rows(
            result.rows,
            spreadsheet_id=result.spreadsheet_id,
            sheet_gid=result.sheet_gid,
            sheet_title=result.sheet_title,
        )
        total_sheets += 1
        total_rows += len(saved)
    return total_sheets, total_rows


def _build_visit_index(visits: list[PmoVaccinationVisit]):
    by_phone = defaultdict(list)
    by_name = defaultdict(list)
    by_user = defaultdict(list)
    for visit in visits:
        if visit.sheet_title == MASTER_SHEET_TITLE:
            continue
        for key in _phone_keys(visit):
            by_phone[key].append(visit)
        name_key = _name_key(visit)
        if name_key:
            by_name[name_key].append(visit)
        if visit.tutor_user_id:
            by_user[visit.tutor_user_id].append(visit)
    return by_phone, by_name, by_user


def _matching_visits(
    master_visit: PmoVaccinationVisit,
    *,
    by_phone,
    by_name,
    by_user,
) -> list[PmoVaccinationVisit]:
    matches: dict[int, PmoVaccinationVisit] = {}
    if master_visit.tutor_user_id:
        for visit in by_user.get(master_visit.tutor_user_id, []):
            matches[visit.id] = visit
    for key in _phone_keys(master_visit):
        for visit in by_phone.get(key, []):
            same_user = bool(master_visit.tutor_user_id) and visit.tutor_user_id == master_visit.tutor_user_id
            if same_user or _names_compatible(master_visit, visit):
                matches[visit.id] = visit
    name_key = _name_key(master_visit)
    if name_key:
        for visit in by_name.get(name_key, []):
            matches[visit.id] = visit
    return sorted(matches.values(), key=_sheet_sort_key)


def _overall_status(matches: list[PmoVaccinationVisit]) -> str:
    if not matches:
        return "sem_registro"
    statuses = [infer_visit_status(visit.animals) for visit in matches]
    dated_statuses = [
        infer_visit_status(visit.animals)
        for visit in matches
        if _parse_date_object((visit.sheet_title or "").strip())
    ]
    if dated_statuses:
        if any(status == "vacinado" for status in dated_statuses):
            return "vacinado"
        if any(status == "parcial" for status in dated_statuses):
            return "parcial"
        if any(status == "remarcar" for status in dated_statuses):
            return "remarcar"
        if any(status == "recusou" for status in dated_statuses):
            return "recusou"
        if any(status == "ausente" for status in dated_statuses):
            return "ausente"
        if any(status == "pendente" for status in dated_statuses):
            return "agendado"
    contextual_statuses = [_display_status_key(visit) for visit in matches]
    if any(status == "vacinado" for status in statuses):
        return "vacinado"
    for status in ("recusou", "perdeu_contato", "reagendar"):
        if status in contextual_statuses:
            return status
    return "pendente"


def _display_status_key(visit: PmoVaccinationVisit) -> str:
    status = infer_visit_status(visit.animals)
    if not _is_encaixes(visit):
        return status
    if status == "recusou":
        return "recusou"
    if status in {"ausente", "parcial"}:
        return "perdeu_contato"
    if status in {"remarcar", "vacinado"}:
        return "reagendar"
    return "reagendar"


def _visit_sheet_url(visit: PmoVaccinationVisit) -> str:
    spreadsheet_id = visit.spreadsheet_id or _extract_google_sheet_id(DEFAULT_SHEET_URL)
    if not spreadsheet_id or not visit.sheet_gid or not visit.source_row:
        return ""
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        f"#gid={visit.sheet_gid}&range=A{visit.source_row}"
    )


def _visit_line(visit: PmoVaccinationVisit) -> str:
    status = _display_status_key(visit)
    row_label = f"linha {visit.source_row}" if visit.source_row else "linha ?"
    animals = "; ".join(
        f"{animal.name}: {STATUS_LABELS.get(animal.status or 'pendente', animal.status or 'pendente')}"
        for animal in visit.animals
    ) or _animal_names(visit)
    date_label = ""
    if visit.vaccine_date:
        date_label = f" em {visit.vaccine_date.strftime('%d/%m/%Y')}"
    return (
        f"- {visit.sheet_title} ({row_label}): "
        f"{STATUS_LABELS.get(status, status)}{date_label}. Pets: {animals}"
    )


def _status_link_cell(matches: list[PmoVaccinationVisit]) -> tuple[str, list[dict[str, Any]]]:
    overall = _overall_status(matches)
    if not matches:
        return STATUS_LABELS.get(overall, "Sem registro"), []

    text_parts = [STATUS_LABELS.get(overall, overall)]
    runs: list[dict[str, Any]] = []
    for visit in matches[:8]:
        status = _display_status_key(visit)
        row_label = f"linha {visit.source_row}" if visit.source_row else "linha ?"
        date_label = f" - {visit.vaccine_date.strftime('%d/%m/%Y')}" if visit.vaccine_date else ""
        text_parts.append("\n")
        start_index = sum(len(part) for part in text_parts)
        sheet_label = visit.sheet_title or "Aba"
        text_parts.append(sheet_label)
        url = _visit_sheet_url(visit)
        if url:
            runs.append(
                {
                    "startIndex": start_index,
                    "format": {
                        "link": {"uri": url},
                        "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.8},
                        "underline": True,
                    },
                }
            )
            runs.append({"startIndex": start_index + len(sheet_label), "format": {}})
        text_parts.append(f" ({row_label}): {STATUS_LABELS.get(status, status)}{date_label}")
    if len(matches) > 8:
        text_parts.append(f"\n+{len(matches) - 8} outros")
    return "".join(text_parts), runs


def _build_note(master_visit: PmoVaccinationVisit, matches: list[PmoVaccinationVisit]) -> str:
    overall = _overall_status(matches)
    lines = [
        "PetOrlandia PMO",
        f"Tutor: {master_visit.tutor_name}",
        f"Status geral: {STATUS_LABELS.get(overall, 'Sem registro em outras abas')}",
        f"Pets no cadastro: {_animal_names(master_visit)}",
    ]
    if master_visit.requested_date:
        lines.append(f"Solicitação: {master_visit.requested_date.strftime('%d/%m/%Y')}")
    if not matches:
        lines.append("")
        lines.append("Ainda não localizado nas abas de agendamento, encaixe ou vacinação.")
        return "\n".join(lines)

    scheduled = [
        visit for visit in matches
        if _normalize_text_key(visit.sheet_title or "") in TRACKED_NON_DATE_TITLES
    ]
    dated = [
        visit for visit in matches
        if _parse_date_object((visit.sheet_title or "").strip())
    ]
    if scheduled:
        lines.append("")
        lines.append("Aparece em abas de fila/agendamento:")
        for visit in scheduled[:8]:
            lines.append(_visit_line(visit))
    if dated:
        lines.append("")
        lines.append("Aparece em abas com data:")
        for visit in dated[:12]:
            lines.append(_visit_line(visit))
    if len(matches) > 20:
        lines.append(f"... +{len(matches) - 20} registros relacionados")
    return "\n".join(lines)


def _build_requests(sheet_id: int, master_visits: list[PmoVaccinationVisit], match_map: dict[int, list[PmoVaccinationVisit]]):
    requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": STATUS_LINK_COLUMN_INDEX,
                    "endIndex": STATUS_LINK_COLUMN_INDEX + 1,
                },
                "properties": {"pixelSize": 260},
                "fields": "pixelSize",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": STATUS_LINK_COLUMN_INDEX,
                    "endColumnIndex": STATUS_LINK_COLUMN_INDEX + 1,
                },
                "cell": {
                    "userEnteredValue": {"stringValue": "Status PMO"},
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.851, "green": 0.918, "blue": 0.827},
                    },
                },
                "fields": "userEnteredValue,userEnteredFormat.textFormat,userEnteredFormat.backgroundColor",
            }
        },
    ]
    for visit in master_visits:
        if not visit.source_row or visit.source_row <= 0:
            continue
        matches = match_map.get(visit.id, [])
        status = _overall_status(matches)
        status_text, status_runs = _status_link_cell(matches)
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": visit.source_row - 1,
                        "endRowIndex": visit.source_row,
                        "startColumnIndex": TIMESTAMP_COLUMN_INDEX,
                        "endColumnIndex": TIMESTAMP_COLUMN_INDEX + 1,
                    },
                    "cell": {
                        "note": _build_note(visit, matches),
                        "userEnteredFormat": {
                            "backgroundColor": STATUS_COLORS.get(status, PMO_STATUS_CLEAR_COLOR),
                            "numberFormat": {
                                "type": "DATE_TIME",
                                "pattern": "dd/MM/yyyy HH:mm:ss",
                            },
                        },
                    },
                    "fields": "note,userEnteredFormat.backgroundColor,userEnteredFormat.numberFormat",
                }
            }
        )
        status_cell = {
            "userEnteredValue": {"stringValue": status_text},
            "userEnteredFormat": {
                "backgroundColor": STATUS_COLORS.get(status, PMO_STATUS_CLEAR_COLOR),
                "wrapStrategy": "WRAP",
            },
        }
        if status_runs:
            status_cell["textFormatRuns"] = status_runs
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": visit.source_row - 1,
                        "endRowIndex": visit.source_row,
                        "startColumnIndex": STATUS_LINK_COLUMN_INDEX,
                        "endColumnIndex": STATUS_LINK_COLUMN_INDEX + 1,
                    },
                    "cell": status_cell,
                    "fields": "userEnteredValue,textFormatRuns,userEnteredFormat.backgroundColor,userEnteredFormat.wrapStrategy",
                }
            }
        )
    return requests


def _chunked(items: list[dict[str, Any]], size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Grava notas e cores na aba Vacinação 2026.")
    parser.add_argument("--limit", type=int, default=0, help="Limita linhas da aba mestre para teste.")
    parser.add_argument("--skip-sync", action="store_true", help="Usa o banco como está, sem reler as abas.")
    args = parser.parse_args()

    with app.app_context():
        service = _get_sheets_service_rw()
        spreadsheet_id = _extract_google_sheet_id(DEFAULT_SHEET_URL)
        if not spreadsheet_id:
            raise RuntimeError("Planilha PMO inválida.")

        if args.skip_sync:
            synced_sheets, synced_rows = 0, 0
        else:
            synced_sheets, synced_rows = _sync_relevant_sheets()
        master_visits = (
            PmoVaccinationVisit.query
            .filter(PmoVaccinationVisit.sheet_title == MASTER_SHEET_TITLE)
            .order_by(PmoVaccinationVisit.source_row.asc())
            .all()
        )
        if args.limit:
            master_visits = master_visits[:args.limit]
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
            raise RuntimeError(f"Aba {MASTER_SHEET_TITLE!r} não encontrada.")

        requests = _build_requests(master_sheet_id, master_visits, match_map)
        if args.apply and requests:
            for chunk in _chunked(requests, 200):
                _retry_execute(
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={"requests": chunk},
                    )
                )

        print(f"abas_sincronizadas: {synced_sheets}")
        print(f"linhas_sincronizadas: {synced_rows}")
        print(f"linhas_mestre: {len(master_visits)}")
        print(f"linhas_com_match: {matched_count}")
        print(f"notas_preparadas: {len(requests)}")
        print(f"aplicado: {bool(args.apply)}")
        for status, count in sorted(status_counts.items()):
            print(f"status_{status}: {count}")


if __name__ == "__main__":
    main()
