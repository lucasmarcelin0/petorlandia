"""
Teste: extrai o produto Agemoxi do VetSmart e imprime os campos
(inclui a tabela estruturada de doses).

Uso:
  python scripts/testar_agemoxi.py
  python scripts/testar_agemoxi.py --visible
"""
import sys, os, json, argparse, re, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from importar_medicamentos_vetsmart import (  # type: ignore
    BASE_URL, LIST_URL, aguardar_e_aceitar_cookies,
    _coletar_links_da_pagina, scrape_detalhe_produto,
)

from playwright.sync_api import sync_playwright

TERMO = "agemoxi"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--visible", action="store_true")
    p.add_argument("--max-paginas", type=int, default=61)
    args = p.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.visible)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Home p/ cookies
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        aguardar_e_aceitar_cookies(page, timeout=8000)

        # Percorre páginas procurando "agemoxi"
        encontrados = []
        ids_vistos = set()
        for n in range(1, args.max_paginas + 1):
            url = f"{LIST_URL}/{n}"
            print(f"→ lista pág {n}: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
                page.wait_for_selector("a[href*='/produto/']", timeout=8000)
            except Exception as e:
                print(f"   ! erro: {e}")
                continue
            links = _coletar_links_da_pagina(page, ids_vistos)
            for l in links:
                if TERMO.lower() in (l["nome"] or "").lower():
                    encontrados.append(l)
                    print(f"   ✓ match: {l['nome']}  ({l['url']})")
            if encontrados:
                break
            time.sleep(0.4)

        if not encontrados:
            print(f"Nenhum produto com '{TERMO}' encontrado.")
            return

        # Extrai detalhe de TODOS os matches
        for info in encontrados:
            print(f"\n═══════════════════════════════════════════════════════")
            print(f"═══ Extraindo detalhe: {info['nome']} ═══")
            print(f"═══════════════════════════════════════════════════════")
            prod = scrape_detalhe_produto(page, info)
            _imprimir(prod)


def _imprimir(prod):
        print("\n── CAMPOS ────────────────────────────────────────────")
        print(f"nome:              {prod.nome}")
        print(f"fabricante:        {prod.fabricante}")
        print(f"classificacao:     {prod.classificacao}")
        print(f"especies:          {prod.especies}")
        print(f"principio_ativo:   {prod.principio_ativo}")
        print(f"via_administracao: {prod.via_administracao}")
        print(f"dosagem_recomendada: {prod.dosagem_recomendada}")
        print(f"frequencia:        {prod.frequencia}")
        print(f"duracao_tratamento: {prod.duracao_tratamento}")

        print("\n── APRESENTAÇÕES ────────────────────────────────────")
        for ap in prod.apresentacoes:
            print(f"  • {ap.get('forma'):20s} | {ap.get('concentracao')}")

        print("\n── DOSES ESTRUTURADAS ───────────────────────────────")
        if not prod.doses:
            print("  (nenhuma dose estruturada extraída)")
        for i, d in enumerate(prod.doses, 1):
            print(f"  [{i}] especie={d.get('especie')!r}  "
                  f"faixa_peso={d.get('faixa_peso')!r}  "
                  f"via={d.get('via')!r}")
            print(f"      dose={d.get('dose')!r}  "
                  f"freq={d.get('frequencia')!r}  "
                  f"dur={d.get('duracao')!r}")
            if d.get("observacao"):
                print(f"      obs: {d['observacao']}")

        print("\n── INDICAÇÕES / INTERAÇÕES (trechos) ────────────────")
        def _preview(x, n=400):
            if not x:
                return "(vazio)"
            return (x[:n] + "…") if len(x) > n else x
        print(f"observacoes: {_preview(prod.observacoes, 400)}")
        print(f"\nbula: {_preview(prod.bula, 400)}")

        print("\n── JSON COMPLETO ────────────────────────────────────")
        from dataclasses import asdict
        print(json.dumps(asdict(prod), ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
