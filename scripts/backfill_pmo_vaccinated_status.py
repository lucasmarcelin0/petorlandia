# -*- coding: utf-8 -*-
"""Backfill de status de vacinação PMO com base nas colunas M e N das abas de dia.

Lê as abas de dias passados (e a aba Agendadas) e atualiza o status dos animais
no banco conforme as quantidades preenchidas manualmente nas colunas:
  - M: Qtde cachorros vacinados
  - N: Qtde gatos vacinados

Regras aplicadas linha a linha:
  - Data Vacina (col L) vazia → pula (visita não aconteceu ou não há informação)
  - M+N == total animais    → todos os animais marcados como "vacinado"
  - M+N == 0                → todos marcados como "ausente"
  - M+N parcial (>0 <total) → primeiros M cães = vacinado, resto = ausente;
                               primeiros N gatos = vacinado, resto = ausente;
                               adiciona nota de revisão para o tutor

Sem flags roda em SIMULAÇÃO (só loga, não grava). Use --apply para gravar.

Ex.:
    python scripts/backfill_pmo_vaccinated_status.py              # simulação
    python scripts/backfill_pmo_vaccinated_status.py --apply      # grava
    python scripts/backfill_pmo_vaccinated_status.py --apply --sheet "29/05/2026"
"""

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import date as _date_cls

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services.sfa_service import _extract_google_sheet_id
from services.vacina_pmo_service import (
    DEFAULT_SHEET_URL,
    _cell,
    _ensure_pmo_vaccine_record,
    _get_sheets_service_rw,
    _is_summary_or_header,
    _normalize_note_line,
    _parse_count,
    _parse_date_object,
    _quote_sheet_title,
    _row_column_offset,
    _strip_accents,
    list_vacina_pmo_sheets,
    write_tutor_name_color_to_sheet,
    write_vaccinated_counts_to_sheet,
)
from time_utils import utcnow

log = logging.getLogger(__name__)

# Abas que NÃO devem ser processadas por este script.
SKIP_TITLES = {
    "vacinação 2026",
    "vacina 2026",
    "controle de doses",
    "padrão",
    "padrao",
    "copia",
    "interesse vacina",
    "teste do bot",
    "inscrição a agendar",
    "inscricao a agendar",
}

# Colunas com offset=0 (índices 0-based na lista de valores da linha)
COL_DATA_VACINA = 11     # L
COL_DOGS_VAC = 12        # M
COL_CATS_VAC = 13        # N
COL_DATE_FALLBACK = 16   # Q (algumas abas colocam a data aqui)


def _norm(value: str) -> str:
    text = _strip_accents(value or "").lower()
    import re
    return re.sub(r"\s+", " ", text).strip()


def _should_process(title: str) -> bool:
    return _norm(title) not in SKIP_TITLES


def _read_sheet_rows(service, spreadsheet_id: str, title: str) -> list[list]:
    range_value = f"{_quote_sheet_title(title)}!A:R"
    resp = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_value)
        .execute()
    )
    return resp.get("values", [])


def _get_date_cell(row: list, offset: int) -> str:
    """Data Vacina: tenta col L primeiro, cai para col Q (carimbo de data/hora)."""
    return _cell(row, COL_DATA_VACINA + offset) or _cell(row, COL_DATE_FALLBACK + offset)


def _compute_new_statuses(
    visit: PmoVaccinationVisit,
    dogs_vac: int,
    cats_vac: int,
) -> dict[int, str] | None:
    """Retorna {animal.id: novo_status} ou None se não houver nada a fazer."""
    dog_animals = sorted(
        [a for a in visit.animals if a.species == "cao"], key=lambda a: a.position or 0
    )
    cat_animals = sorted(
        [a for a in visit.animals if a.species == "gato"], key=lambda a: a.position or 0
    )
    total = len(visit.animals)
    total_vac = dogs_vac + cats_vac

    if total == 0:
        return None

    new_statuses: dict[int, str] = {}

    if total_vac == 0:
        # Nenhum vacinado — ausente
        for animal in visit.animals:
            new_statuses[animal.id] = "ausente"

    elif total_vac >= total:
        # Todos vacinados
        for animal in visit.animals:
            new_statuses[animal.id] = "vacinado"

    else:
        # Parcial — marca por espécie na ordem da lista
        for i, animal in enumerate(dog_animals):
            new_statuses[animal.id] = "vacinado" if i < dogs_vac else "ausente"
        for i, animal in enumerate(cat_animals):
            new_statuses[animal.id] = "vacinado" if i < cats_vac else "ausente"

    # Só retorna se houver alguma mudança real
    has_change = any(
        a.status != new_statuses[a.id] for a in visit.animals if a.id in new_statuses
    )
    return new_statuses if has_change else None


def _is_partial(visit: PmoVaccinationVisit, new_statuses: dict[int, str]) -> bool:
    return any(s == "vacinado" for s in new_statuses.values()) and any(
        s == "ausente" for s in new_statuses.values()
    )


def _apply_statuses(
    visit: PmoVaccinationVisit,
    new_statuses: dict[int, str],
    vaccine_date,
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """Aplica os novos status. Retorna (vacinados, ausentes)."""
    vacinados = sum(1 for s in new_statuses.values() if s == "vacinado")
    ausentes = sum(1 for s in new_statuses.values() if s == "ausente")

    if dry_run:
        return vacinados, ausentes

    partial = _is_partial(visit, new_statuses)
    if partial:
        note_line = _normalize_note_line(
            f"[backfill] {vacinados}/{len(visit.animals)} animais vacinados — "
            "revisar ordem se necessário."
        )
        current = (visit.note or "").strip()
        visit.note = f"{current} | {note_line}" if current else note_line

    if vaccine_date and not visit.vaccine_date:
        visit.vaccine_date = vaccine_date

    animal_by_id = {a.id: a for a in visit.animals}
    for animal_id, new_status in new_statuses.items():
        animal = animal_by_id.get(animal_id)
        if not animal or animal.status == new_status:
            continue
        animal.status = new_status
        if new_status == "vacinado":
            animal.vaccinated_at = utcnow()
            _ensure_pmo_vaccine_record(animal)
        else:
            animal.vaccinated_at = None

    db.session.commit()
    write_vaccinated_counts_to_sheet(visit)
    write_tutor_name_color_to_sheet(visit)
    return vacinados, ausentes


def run_backfill(*, dry_run: bool = True, only_sheet: str = "") -> Counter:
    summary: Counter = Counter()
    today = _date_cls.today()
    spreadsheet_id = _extract_google_sheet_id(DEFAULT_SHEET_URL)
    if not spreadsheet_id:
        raise RuntimeError("URL da planilha PMO inválida.")

    service = _get_sheets_service_rw()

    sheets = list_vacina_pmo_sheets()
    for sheet_info in sheets:
        title = sheet_info.get("title") or ""
        gid = sheet_info.get("gid") or ""

        if only_sheet and _norm(title) != _norm(only_sheet):
            continue
        if not _should_process(title):
            log.debug("Pulando aba '%s'", title)
            continue

        log.info("Processando aba '%s' (gid=%s)…", title, gid)
        try:
            rows = _read_sheet_rows(service, spreadsheet_id, title)
        except Exception as exc:
            log.warning("Erro ao ler aba '%s': %s", title, exc)
            summary["erros_leitura"] += 1
            continue

        for row_index_0, row in enumerate(rows):
            source_row = row_index_0 + 1  # 1-based

            if _is_summary_or_header(row):
                continue

            offset = _row_column_offset(row)
            date_raw = _get_date_cell(row, offset)
            vaccine_date = _parse_date_object(date_raw)

            if not vaccine_date:
                summary["sem_data_vacina"] += 1
                continue

            vac_date_only = vaccine_date.date() if hasattr(vaccine_date, "date") else vaccine_date
            if vac_date_only > today:
                summary["data_futura"] += 1
                continue

            dogs_vac = _parse_count(_cell(row, COL_DOGS_VAC + offset))
            cats_vac = _parse_count(_cell(row, COL_CATS_VAC + offset))

            visit: PmoVaccinationVisit | None = (
                PmoVaccinationVisit.query.filter_by(
                    spreadsheet_id=spreadsheet_id,
                    sheet_gid=gid,
                    source_row=source_row,
                ).first()
            )

            if not visit:
                log.debug(
                    "Aba '%s' linha %d: visita não encontrada no banco.",
                    title, source_row,
                )
                summary["visita_nao_encontrada"] += 1
                continue

            new_statuses = _compute_new_statuses(visit, dogs_vac, cats_vac)
            if new_statuses is None:
                summary["sem_mudanca"] += 1
                continue

            partial = _is_partial(visit, new_statuses)
            vacinados, ausentes = _apply_statuses(
                visit, new_statuses, vaccine_date, dry_run=dry_run
            )

            tag = "parcial" if partial else ("vacinado" if ausentes == 0 else "ausente_total")
            summary[tag] += 1
            log.info(
                "%s aba='%s' linha=%d tutor='%s' vacinados=%d ausentes=%d%s",
                "[SIMULAÇÃO]" if dry_run else "[APLICADO]",
                title, source_row, visit.tutor_name or "?",
                vacinados, ausentes,
                " ← PARCIAL (revisar)" if partial else "",
            )

    return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Grava as mudanças no banco e na planilha (padrão: só simula).",
    )
    parser.add_argument(
        "--sheet",
        default="",
        metavar="TÍTULO",
        help="Processa apenas a aba com este título (ex.: '29/05/2026').",
    )
    args = parser.parse_args()

    with app.app_context():
        if args.apply:
            log.info("Modo APLICAR — as mudanças serão gravadas.")
        else:
            log.info("Modo SIMULAÇÃO — nenhuma alteração será feita. Use --apply para gravar.")

        summary = run_backfill(dry_run=not args.apply, only_sheet=args.sheet)

    print("\n── Resumo ──────────────────────────────")
    for key, count in sorted(summary.items()):
        print(f"  {key:30s}: {count}")
    print("────────────────────────────────────────")
    if not args.apply:
        print("\n⚠  Isso foi uma SIMULAÇÃO. Rode com --apply para gravar de verdade.")


if __name__ == "__main__":
    main()
