from app import app
from services.vacina_pmo_service import (
    list_vacina_pmo_sheets,
    persist_vacina_pmo_rows,
    sync_vacina_pmo_sheet,
)


def main() -> None:
    with app.app_context():
        total_rows = 0
        total_sheets = 0
        for sheet in list_vacina_pmo_sheets():
            title = sheet.get("title") or ""
            gid = sheet.get("gid") or ""
            normalized_title = title.strip().lower()
            if normalized_title in {"controle de doses", "padrão", "padrao", "copia"}:
                print(f"PULOU {title}: aba auxiliar")
                continue
            try:
                result = sync_vacina_pmo_sheet(sheet_gid=gid, sheet_title=title)
                saved = persist_vacina_pmo_rows(
                    result.rows,
                    spreadsheet_id=result.spreadsheet_id,
                    sheet_gid=result.sheet_gid,
                    sheet_title=result.sheet_title,
                )
            except Exception as exc:
                print(f"ERRO {title or gid}: {exc}")
                continue

            total_sheets += 1
            total_rows += len(saved)
            print(f"OK {result.sheet_title or title}: {len(saved)} linhas")

        print(f"TOTAL {total_sheets} abas, {total_rows} linhas")


if __name__ == "__main__":
    main()
