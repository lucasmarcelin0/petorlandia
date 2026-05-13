"""
run_1_harvest.py — Fase 1: Baixar HTMLs do Vetsmart
=====================================================
Responsabilidade única: percorrer o catálogo do Vetsmart e salvar o HTML
bruto de cada página de produto em disco.  NÃO parseia, NÃO escreve no banco.

Características:
  - Checkpoint SQLite: retoma de onde parou se for interrompido
  - Detecção de Cloudflare: não salva HTMLs bloqueados
  - Delays aleatórios (2–5 s) para não ser banido
  - Retry com backoff exponencial (3 tentativas por produto)
  - Salva em data/vetsmart_html/<pid>.html

USO:
    pip install playwright psycopg2-binary beautifulsoup4
    playwright install chromium

    # Baixar tudo (retoma do checkpoint automaticamente):
    python scripts/scraping/run_1_harvest.py

    # Somente os primeiros 50 produtos (teste):
    python scripts/scraping/run_1_harvest.py --limite 50

    # Reprocessar produtos que falharam anteriormente:
    python scripts/scraping/run_1_harvest.py --refazer-falhas

    # Modo visível (debug):
    python scripts/scraping/run_1_harvest.py --visible --limite 5
"""

import os
import sys
import time
import sqlite3
import random
import argparse
import logging
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any

# ---------------------------------------------------------------------------
# UTF-8 no console Windows
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE_DIR    = Path(__file__).resolve().parent.parent.parent  # raiz do projeto
HTML_DIR    = BASE_DIR / "data" / "vetsmart_html"
CKPT_FILE   = BASE_DIR / "data" / "harvest_checkpoint.sqlite"
LOG_FILE    = BASE_DIR / "data" / "harvest.log"

BASE_URL    = "https://vetsmart.com.br"
LIST_URL    = f"{BASE_URL}/cg/produto/lista"
PRODUTO_URL = f"{BASE_URL}/cg/produto"
PAGINA_MAX  = 61          # Vetsmart tem ~61 páginas de listagem

DELAY_MIN   = 2.0         # segundos entre páginas (mínimo)
DELAY_MAX   = 5.0         # segundos entre páginas (máximo)
MAX_TENTATIVAS = 3

COOKIE_SELECTORS = [
    "button:has-text('Aceitar')", "button:has-text('Aceitar todos')",
    "button:has-text('Concordo')", "#onetrust-accept-btn-handler",
    ".cc-accept", ".cc-btn",
]

HTML_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Checkpoint SQLite
# ---------------------------------------------------------------------------
def abrir_checkpoint() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CKPT_FILE))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS produto (
            pid         INTEGER PRIMARY KEY,
            nome        TEXT,
            status      TEXT DEFAULT 'pendente',
            tentativas  INTEGER DEFAULT 0,
            html_hash   TEXT,
            atualizado  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lista_page (
            pagina  INTEGER PRIMARY KEY,
            status  TEXT DEFAULT 'pendente'
        )
    """)
    conn.commit()
    return conn


def marcar_produto(ckpt, pid: int, nome: str, status: str, html_hash: str = None):
    ckpt.execute("""
        INSERT INTO produto (pid, nome, status, tentativas, html_hash, atualizado)
        VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(pid) DO UPDATE SET
            nome        = excluded.nome,
            status      = excluded.status,
            tentativas  = tentativas + 1,
            html_hash   = COALESCE(excluded.html_hash, html_hash),
            atualizado  = CURRENT_TIMESTAMP
    """, (pid, nome, status, html_hash))
    ckpt.commit()


def pids_concluidos(ckpt, incluir_falhas: bool = False) -> set:
    if incluir_falhas:
        cur = ckpt.execute("SELECT pid FROM produto WHERE status = 'ok'")
    else:
        cur = ckpt.execute("SELECT pid FROM produto WHERE status IN ('ok','falha_definitiva')")
    return {r[0] for r in cur.fetchall()}


def listar_falhas(ckpt) -> List[Dict]:
    cur = ckpt.execute("""
        SELECT pid, nome FROM produto
        WHERE status NOT IN ('ok') AND tentativas < ?
    """, (MAX_TENTATIVAS,))
    return [{"id": r[0], "nome": r[1]} for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Helpers de browser
# ---------------------------------------------------------------------------
def aceitar_cookies(page) -> None:
    for sel in COOKIE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.5)
                return
        except Exception:
            pass


def _eh_cloudflare(html: str) -> bool:
    """Retorna True se o HTML é uma página de challenge do Cloudflare."""
    marcas = [
        "cf-browser-verification",
        "cloudflare",
        "ray id",
        "checking if the site connection is secure",
        "just a moment",
        "enable javascript and cookies",
    ]
    lower = html.lower()
    return sum(1 for m in marcas if m in lower) >= 2


def _eh_conteudo_valido(html: str) -> bool:
    """Verifica se o HTML contém o conteúdo esperado de um produto Vetsmart."""
    return ("container-content" in html or "side-nav-title" in html)


def _delay_aleatorio():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ---------------------------------------------------------------------------
# Scraping de lista
# ---------------------------------------------------------------------------
def _coletar_links_da_pagina(page, ids_vistos: set) -> List[Dict]:
    import re
    novos = []
    for a in page.query_selector_all("a[href*='/produto/']"):
        try:
            href = a.get_attribute("href") or ""
            m = re.search(r"/produto/(\d+)", href)
            if not m:
                continue
            pid = int(m.group(1))
            if pid in ids_vistos:
                continue
            nome = (a.inner_text() or f"Produto #{pid}").strip()[:120]
            ids_vistos.add(pid)
            url = BASE_URL + href if href.startswith("/") else href
            novos.append({"id": pid, "nome": nome, "url": url})
        except Exception:
            pass
    return novos


def scrape_lista_produtos(page, pagina_max: int = PAGINA_MAX) -> List[Dict]:
    produtos = []
    ids_vistos: set = set()
    cookies_aceitos = False

    for n in range(1, pagina_max + 1):
        url_pag = f"{LIST_URL}/{n}"
        log.info(f"Lista página {n}/{pagina_max}: {url_pag}")
        try:
            page.goto(url_pag, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("a[href*='/produto/']", timeout=8000)
            except Exception:
                pass
        except Exception as e:
            log.warning(f"  ! erro lista pág {n}: {e}")
            _delay_aleatorio()
            continue

        if not cookies_aceitos:
            aceitar_cookies(page)
            cookies_aceitos = True

        novos = _coletar_links_da_pagina(page, ids_vistos)
        produtos.extend(novos)
        log.info(f"  +{len(novos)} (total: {len(produtos)})")

        if not novos:
            log.info(f"  → pág {n} sem produtos novos — fim da lista")
            break

        _delay_aleatorio()

    log.info(f"Total na lista: {len(produtos)} produtos.")
    return produtos


# ---------------------------------------------------------------------------
# Download de produto individual
# ---------------------------------------------------------------------------
def baixar_produto(page, pid: int, url: str) -> Optional[str]:
    """Baixa o HTML do produto. Retorna HTML ou None em caso de falha."""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            try:
                page.wait_for_selector(
                    "h2.side-nav-title, section.container-content",
                    timeout=10000,
                )
            except Exception:
                pass
            aceitar_cookies(page)
            time.sleep(random.uniform(0.3, 0.8))
            html = page.content()

            if _eh_cloudflare(html):
                log.warning(f"  Cloudflare detectado em pid={pid} (tentativa {tentativa})")
                # Espera mais antes de tentar de novo
                time.sleep(random.uniform(8.0, 15.0))
                continue

            if not _eh_conteudo_valido(html):
                log.warning(f"  HTML sem conteúdo esperado em pid={pid} (tentativa {tentativa})")
                if tentativa < MAX_TENTATIVAS:
                    _delay_aleatorio()
                continue

            return html

        except Exception as e:
            log.warning(f"  Erro pid={pid} tentativa={tentativa}: {e}")
            if tentativa < MAX_TENTATIVAS:
                time.sleep(random.uniform(3.0, 7.0))

    return None


def salvar_html(pid: int, html: str) -> str:
    """Salva HTML em disco, retorna hash MD5."""
    caminho = HTML_DIR / f"{pid}.html"
    caminho.write_text(html, encoding="utf-8")
    return hashlib.md5(html.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Fase 1 — Baixar HTMLs do Vetsmart para disco."
    )
    parser.add_argument("--limite",         type=int, default=0,
                        help="Máximo de produtos a baixar (0 = todos).")
    parser.add_argument("--refazer-falhas", action="store_true",
                        help="Retenta produtos que falharam anteriormente.")
    parser.add_argument("--visible",        action="store_true",
                        help="Abre o browser visível (debug).")
    parser.add_argument("--paginas",        type=int, default=PAGINA_MAX,
                        help=f"Páginas de lista a percorrer (padrão {PAGINA_MAX}).")
    parser.add_argument("--apenas-lista",   action="store_true",
                        help="Só coleta a lista de produtos, sem baixar os detalhes.")
    args = parser.parse_args()

    ckpt = abrir_checkpoint()
    ja_feitos = pids_concluidos(ckpt, incluir_falhas=False)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Instale: pip install playwright && playwright install chromium")
        sys.exit(1)

    contadores = {"baixados": 0, "pulados": 0, "falhas": 0}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.visible,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Aceita cookies na home
        log.info("Abrindo home para aceitar cookies…")
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        aceitar_cookies(page)
        time.sleep(1.0)

        # Coleta lista de produtos
        lista = scrape_lista_produtos(page, pagina_max=args.paginas)

        # Adiciona falhas pendentes se solicitado
        if args.refazer_falhas:
            falhas = listar_falhas(ckpt)
            ids_ja = {p["id"] for p in lista}
            lista.extend(f for f in falhas if f["id"] not in ids_ja)
            log.info(f"  +{len(falhas)} produtos com falhas adicionados à fila.")

        if args.apenas_lista:
            log.info(f"--apenas-lista: {len(lista)} produtos coletados. Saindo.")
            browser.close()
            ckpt.close()
            return

        if args.limite > 0:
            lista = lista[:args.limite]

        total = len(lista)
        log.info(f"Iniciando download de {total} produtos (já feitos: {len(ja_feitos)}).")

        for i, info in enumerate(lista, 1):
            pid  = info["id"]
            nome = info.get("nome", f"Produto #{pid}")
            url  = info.get("url", f"{PRODUTO_URL}/{pid}")

            if pid in ja_feitos and not args.refazer_falhas:
                log.info(f"[{i}/{total}] (ok) {nome}")
                contadores["pulados"] += 1
                continue

            log.info(f"[{i}/{total}] {nome} (pid={pid})")
            html = baixar_produto(page, pid, url)

            if html:
                html_hash = salvar_html(pid, html)
                marcar_produto(ckpt, pid, nome, "ok", html_hash)
                contadores["baixados"] += 1
                log.info(f"  ✓ salvo {HTML_DIR / f'{pid}.html'} ({len(html)//1024} KB)")
            else:
                marcar_produto(ckpt, pid, nome, "falha_definitiva")
                contadores["falhas"] += 1
                log.warning(f"  ✗ falha definitiva pid={pid}")

            _delay_aleatorio()

        browser.close()

    ckpt.close()
    log.info(
        f"\nFase 1 concluída: "
        f"{contadores['baixados']} baixados, "
        f"{contadores['pulados']} pulados, "
        f"{contadores['falhas']} falhas. "
        f"HTMLs em: {HTML_DIR}"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
