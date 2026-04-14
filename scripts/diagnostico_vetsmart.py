"""
Diagnóstico: salva o HTML completo de uma página de produto do VetSmart
para que possamos inspecionar a estrutura real e melhorar os seletores.

Uso:
    python scripts/diagnostico_vetsmart.py
"""
import time
import re
import sys
from pathlib import Path

URL_PRODUTO = "https://vetsmart.com.br/cg/produto/2616/4dx-plus"
SAIDA_HTML  = "diagnostico_vetsmart_produto.html"
SAIDA_TXT   = "diagnostico_vetsmart_produto.txt"

COOKIE_SELECTORS = [
    "button:has-text('Aceitar')",
    "button:has-text('Aceitar todos')",
    "button:has-text('Concordo')",
    "button:has-text('OK')",
    "button:has-text('Entendi')",
    "button:has-text('Continuar')",
    "a:has-text('Aceitar')",
    "[id*='accept']", "[class*='accept']",
    "[id*='cookie'] button", "[class*='cookie'] button",
    "[id*='lgpd'] button", "[class*='lgpd'] button",
    "[class*='consent'] button",
    "#onetrust-accept-btn-handler", ".cc-accept", ".cc-btn",
]

def aceitar_cookies(page):
    for sel in COOKIE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f"  ✓ Cookie aceito via: {sel}")
                page.wait_for_load_state("networkidle", timeout=5000)
                return True
        except Exception:
            pass
    return False

def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Instale: pip install playwright && playwright install chromium")
        sys.exit(1)

    print("Iniciando navegador...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # visível para depurar
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="pt-BR",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # 1. Home – aceita cookies
        print("Abrindo home...")
        page.goto("https://vetsmart.com.br", wait_until="networkidle", timeout=30000)
        try:
            page.wait_for_selector(
                "button:has-text('Aceitar'), [id*='cookie'], [class*='lgpd']",
                timeout=8000
            )
            time.sleep(0.5)
            aceitar_cookies(page)
        except Exception:
            print("  (nenhum banner de cookie na home)")

        # 2. Produto
        print(f"\nAbrindo produto: {URL_PRODUTO}")
        page.goto(URL_PRODUTO, wait_until="networkidle", timeout=60000)
        try:
            page.wait_for_selector(
                "button:has-text('Aceitar'), [id*='cookie'], [class*='lgpd']",
                timeout=5000
            )
            aceitar_cookies(page)
        except Exception:
            pass

        time.sleep(2)  # deixa JS renderizar

        # 3. Salva HTML completo
        html = page.content()
        Path(SAIDA_HTML).write_text(html, encoding="utf-8")
        print(f"\n✓ HTML completo salvo em: {SAIDA_HTML}  ({len(html):,} bytes)")

        # 4. Salva texto limpo (inner_text do body)
        texto = page.inner_text("body") or ""
        Path(SAIDA_TXT).write_text(texto, encoding="utf-8")
        print(f"✓ Texto limpo salvo em:   {SAIDA_TXT}  ({len(texto):,} chars)")

        # 5. Tenta listar todos os elementos com texto relevante
        print("\n── Elementos encontrados na página ──────────────────────────")
        seletores_interesse = [
            "table", "dl", ".info", ".detalhe", ".produto",
            "[class*='principio']", "[class*='via']", "[class*='dose']",
            "[class*='apres']", "[class*='forma']", "[class*='conc']",
            "[class*='composic']", "[class*='indica']", "[class*='contra']",
            "[class*='bula']", "[class*='fabricante']", "[class*='laborat']",
            "h2", "h3", "h4", "strong", "th", "dt",
        ]
        encontrados = set()
        for sel in seletores_interesse:
            els = page.query_selector_all(sel)
            for el in els[:5]:
                try:
                    tag = el.evaluate("el => el.tagName.toLowerCase()")
                    cls = el.evaluate("el => el.className") or ""
                    txt = (el.inner_text() or "")[:80].replace("\n", " ").strip()
                    if txt and txt not in encontrados:
                        encontrados.add(txt)
                        print(f"  <{tag} class='{cls[:40]}'> → {txt}")
                except Exception:
                    pass

        print("\n────────────────────────────────────────────────────────────")
        print(f"\nArquivos salvos na pasta do projeto:")
        print(f"  {Path(SAIDA_HTML).resolve()}")
        print(f"  {Path(SAIDA_TXT).resolve()}")
        print("\nCompartilhe o conteúdo de 'diagnostico_vetsmart_produto.txt' para melhorar os seletores.")

        browser.close()

if __name__ == "__main__":
    main()
