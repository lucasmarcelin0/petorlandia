from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

from flask import render_template

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_factory import create_app


def _export_pdf_if_possible(html_path: Path, pdf_path: Path) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - fallback operacional
        return f"PDF nao gerado ({exc})"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
            )
            browser.close()
    except Exception as exc:  # pragma: no cover - fallback operacional
        return f"PDF nao gerado ({exc})"
    return None


def main() -> None:
    from blueprints.sfa import (
        _consulta_pacientes_filtrada,
        _filtros_pacientes_vazios,
        _formularios_impressao_sfa,
        _montar_dashboard_testes_sfa,
    )

    app = create_app()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    with app.app_context():
        filtros = _filtros_pacientes_vazios(visao="testes")
        dashboard_testes = _montar_dashboard_testes_sfa(_consulta_pacientes_filtrada(filtros).all())
        formularios = _formularios_impressao_sfa()
        generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

        with app.test_request_context("/sfa/pacientes/impressao/testes"):
            graficos_html = render_template(
                "sfa/print_dashboard_testes.html",
                dashboard_testes=dashboard_testes,
                filtros=filtros,
                generated_at=generated_at,
            )

        with app.test_request_context("/sfa/formularios/impressao"):
            formularios_html = render_template(
                "sfa/print_form_questions.html",
                formularios=formularios,
                generated_at=generated_at,
            )

    graficos_html_path = OUTPUT_DIR / f"sfa_graficos_testes_a4_{timestamp}.html"
    formularios_html_path = OUTPUT_DIR / f"sfa_perguntas_t0_t10_t30_a4_{timestamp}.html"
    graficos_pdf_path = OUTPUT_DIR / f"sfa_graficos_testes_a4_{timestamp}.pdf"
    formularios_pdf_path = OUTPUT_DIR / f"sfa_perguntas_t0_t10_t30_a4_{timestamp}.pdf"

    graficos_html_path.write_text(graficos_html, encoding="utf-8")
    formularios_html_path.write_text(formularios_html, encoding="utf-8")

    graficos_pdf_result = _export_pdf_if_possible(graficos_html_path, graficos_pdf_path)
    formularios_pdf_result = _export_pdf_if_possible(formularios_html_path, formularios_pdf_path)

    print(f"HTML gerado: {graficos_html_path}")
    print(f"HTML gerado: {formularios_html_path}")
    print(
        f"PDF graficos: {graficos_pdf_path}"
        if graficos_pdf_result is None
        else f"PDF graficos: {graficos_pdf_result}"
    )
    print(
        f"PDF formularios: {formularios_pdf_path}"
        if formularios_pdf_result is None
        else f"PDF formularios: {formularios_pdf_result}"
    )


if __name__ == "__main__":
    main()
