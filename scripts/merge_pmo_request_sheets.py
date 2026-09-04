"""
merge_pmo_request_sheets.py
===========================
Devolve para a aba oficial de solicitacoes as linhas que cairam em abas
duplicadas da planilha da campanha PMO.

O QUE ACONTECEU
  A aba de solicitacoes foi renomeada na planilha ("Solicitacoes" ->
  "Solicitacoes de vacina"). O app procurava a aba pelo nome exato, nao
  encontrou e criou uma copia vazia com o nome antigo no fim da planilha. A
  partir dai toda solicitacao enviada em /vacina-pmo/solicitar foi gravada
  nessa copia -- some da aba que a equipe acompanha, mesmo tendo sido enviada
  com sucesso pelo morador.

O QUE ESTE SCRIPT FAZ
  1. Resolve qual e a aba oficial (mesma regra que o app usa agora).
  2. Procura outras abas com o MESMO cabecalho de solicitacoes.
  3. Copia para a aba oficial as linhas que ainda nao estao la (compara
     carimbo de data/hora + tutor + animais, entao rodar duas vezes nao
     duplica nada).
  4. Reaponta o registro local (PmoVaccinationVisit) para a linha nova, para
     que protocolo, carteirinha e historico do morador continuem validos.
  5. Limpa as linhas ja copiadas da aba duplicada, para que uma sincronizacao
     futura daquela aba nao recrie visitas repetidas. A aba vazia pode ser
     apagada a mao depois.

Uso:
  python scripts/merge_pmo_request_sheets.py --dry-run
  python scripts/merge_pmo_request_sheets.py
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Colunas usadas como identidade da solicitacao (ver PMO_REQUEST_HEADERS).
_COL_TUTOR = 0
_COL_ANIMAIS = 9
_COL_CARIMBO = 15


def _row_key(row: list[str]) -> tuple[str, str, str]:
    def cell(index: int) -> str:
        value = row[index] if index < len(row) else ""
        return re.sub(r"\s+", " ", str(value or "")).strip().lower()

    return (cell(_COL_CARIMBO), cell(_COL_TUTOR), cell(_COL_ANIMAIS))


def _is_empty(row: list[str]) -> bool:
    return not any(str(cell or "").strip() for cell in row)


def run(dry_run: bool = False) -> int:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app_factory import create_app
    from extensions import db
    from models import PmoVaccinationVisit
    from services.vacina_pmo_service import (
        DEFAULT_SHEET_URL,
        PMO_REQUEST_HEADER_RANGE,
        PMO_REQUEST_RANGE_COLS,
        _extract_google_sheet_id,
        _get_sheet_gid,
        _get_sheets_service_rw,
        _quote_sheet_title,
        _request_sheet_header_matches,
        _resolve_request_sheet_title,
        pmo_request_sheet_titles,
    )

    prefix = "[DRY-RUN] " if dry_run else ""
    app = create_app()
    with app.app_context():
        sheet_url = os.getenv("PMO_VACCINE_SHEET_URL", DEFAULT_SHEET_URL)
        spreadsheet_id = _extract_google_sheet_id(sheet_url)
        if not spreadsheet_id:
            log.error("URL/ID da planilha PMO invalido: %s", sheet_url)
            return 1

        service = _get_sheets_service_rw()
        canonical = _resolve_request_sheet_title(
            service, spreadsheet_id, pmo_request_sheet_titles()[0]
        )
        canonical_gid = _get_sheet_gid(service, spreadsheet_id, canonical)
        log.info("Aba oficial de solicitacoes: %r (gid %s)", canonical, canonical_gid)

        metadata = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
            .execute()
        )
        others = [
            (sheet.get("properties") or {}).get("title", "")
            for sheet in metadata.get("sheets", [])
            if (sheet.get("properties") or {}).get("title", "") not in ("", canonical)
        ]

        header_ranges = [
            f"{_quote_sheet_title(title)}!{PMO_REQUEST_HEADER_RANGE}" for title in others
        ]
        headers = (
            service.spreadsheets()
            .values()
            .batchGet(spreadsheetId=spreadsheet_id, ranges=header_ranges)
            .execute()
            .get("valueRanges", [])
        )
        duplicates = [
            title
            for title, value_range in zip(others, headers)
            if _request_sheet_header_matches(value_range.get("values"))
        ]
        if not duplicates:
            log.info("Nenhuma aba duplicada de solicitacoes. Nada a fazer.")
            return 0
        log.info("Abas duplicadas encontradas: %s", ", ".join(repr(t) for t in duplicates))

        canonical_rows = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"{_quote_sheet_title(canonical)}!{PMO_REQUEST_RANGE_COLS}",
            )
            .execute()
            .get("values", [])
        )
        known = {_row_key(row) for row in canonical_rows[1:] if not _is_empty(row)}
        next_row = len(canonical_rows) + 1

        copiadas = 0
        reapontadas = 0
        for title in duplicates:
            rows = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=spreadsheet_id,
                    range=f"{_quote_sheet_title(title)}!{PMO_REQUEST_RANGE_COLS}",
                )
                .execute()
                .get("values", [])
            )
            dup_gid = _get_sheet_gid(service, spreadsheet_id, title)

            pendentes: list[tuple[int, list[str]]] = []
            for index, row in enumerate(rows[1:], start=2):
                if _is_empty(row):
                    continue
                key = _row_key(row)
                if key in known:
                    continue
                known.add(key)
                pendentes.append((index, row))

            if not pendentes:
                log.info("%r: nada novo para copiar.", title)
                continue

            log.info("%s%r: copiando %d linha(s) para %r.", prefix, title, len(pendentes), canonical)
            for source_row, row in pendentes:
                log.info(
                    "%s  linha %d -> %s (%s)",
                    prefix,
                    source_row,
                    row[_COL_TUTOR] if len(row) > _COL_TUTOR else "?",
                    row[_COL_CARIMBO] if len(row) > _COL_CARIMBO else "sem carimbo",
                )
            if dry_run:
                copiadas += len(pendentes)
                continue

            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=f"{_quote_sheet_title(canonical)}!{PMO_REQUEST_RANGE_COLS}",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [row for _, row in pendentes]},
            ).execute()

            # Reaponta o registro local para a linha nova: o protocolo publico
            # ja entregue ao morador continua abrindo a mesma solicitacao.
            for offset, (source_row, _row) in enumerate(pendentes):
                visit = PmoVaccinationVisit.query.filter_by(
                    spreadsheet_id=spreadsheet_id,
                    sheet_gid=dup_gid,
                    source_row=source_row,
                ).first()
                if visit is None:
                    continue
                visit.sheet_gid = canonical_gid
                visit.sheet_title = canonical
                visit.source_row = next_row + offset
                reapontadas += 1
            db.session.commit()

            next_row += len(pendentes)
            copiadas += len(pendentes)

            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"{_quote_sheet_title(title)}!A2:R",
                body={},
            ).execute()
            log.info("%r: linhas copiadas foram limpas da aba duplicada.", title)

        log.info(
            "%sResumo: %d solicitacao(oes) copiada(s), %d registro(s) local(is) reapontado(s).",
            prefix,
            copiadas,
            reapontadas,
        )
        if not dry_run and copiadas:
            log.info("Apague as abas duplicadas vazias a mao quando conferir a planilha.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria copiado sem escrever na planilha nem no banco.",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
