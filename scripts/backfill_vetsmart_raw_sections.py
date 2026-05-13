"""
backfill_vetsmart_raw_sections.py
==================================
Re-scrapia as páginas públicas do Vetsmart (https://vetsmart.com.br/cg/produto/<id>)
apenas para atualizar o campo `raw_sections` dentro de `conteudo_estruturado`.

Não toca em doses, apresentações ou outros campos — apenas garante que todas
as 11 seções da página (Sobre, Apresentações e concentrações, ...,
Ref. bibliográficas) fiquem gravadas para exibição com atribuição.

Também funciona como melhoria de pipeline: com as seções brutas gravadas,
é possível re-parsear doses/indicações sem precisar bater no site de novo.

USO:
    pip install playwright psycopg2-binary beautifulsoup4
    playwright install chromium

    # Ver o que seria feito (dry-run):
    python scripts/backfill_vetsmart_raw_sections.py --dry-run

    # Rodar tudo:
    python scripts/backfill_vetsmart_raw_sections.py

    # Só medicamentos sem raw_sections já gravado:
    python scripts/backfill_vetsmart_raw_sections.py --apenas-faltantes

    # Limitar quantos processar por execução:
    python scripts/backfill_vetsmart_raw_sections.py --limite 50
"""

import os, sys, time, re, json, argparse, logging
from typing import Optional, Dict, List, Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Instale: pip install beautifulsoup4")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
except ImportError:
    print("Instale: pip install playwright && playwright install chromium")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backfill_raw_sections.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BASE_URL = "https://vetsmart.com.br"
PRODUTO_URL = f"{BASE_URL}/cg/produto"
DELAY_ENTRE_PAGINAS = 1.2  # segundos

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://u82pgjdcmkbq7v:p0204cb9289674b66bfcbb9248eaf9d6a71e2dece2722fe22d6bd976c77b411e6"
        "@c2hbg00ac72j9d.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d2nnmcuqa8ljli",
    ),
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SECOES_ESPERADAS = [
    'Sobre',
    'Apresentações e concentrações',
    'Indicações e contraindicações',
    'Administração e doses',
    'Interações medicamentosas',
    'Farmacologia',
    'Estudos',
    'Videos',
    'Avaliações',
    'Distribuidores',
    'Ref. bibliográficas',
]

FRASES_VAZIO = [
    "ainda não tem informações",
    "ainda não tem videos",
    "ainda não tem distribuidores",
    "não há nenhum estudo",
    "não contém interações",
    "ainda não foi preenchida",
    "não tem referências",
]

COOKIE_SELECTORS = [
    "button:has-text('Aceitar')", "button:has-text('Aceitar todos')",
    "button:has-text('Concordo')", "#onetrust-accept-btn-handler",
    ".cc-accept", ".cc-btn",
]


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def conectar():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=15)
    conn.autocommit = False
    return conn


def listar_medicamentos_para_backfill(conn, apenas_faltantes: bool, limite: Optional[int]) -> List[Dict]:
    where_extra = ""
    if apenas_faltantes:
        # Filtra os que ainda não têm raw_sections gravado
        where_extra = """
            AND (
                conteudo_estruturado IS NULL
                OR (conteudo_estruturado->>'raw_sections') IS NULL
                OR conteudo_estruturado->>'raw_sections' = '{}'
            )
        """
    limite_sql = f"LIMIT {int(limite)}" if limite else ""
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT id, nome, vetsmart_produto_id,
                   conteudo_estruturado
            FROM medicamento
            WHERE vetsmart_produto_id IS NOT NULL
            {where_extra}
            ORDER BY id
            {limite_sql}
        """)
        return [dict(r) for r in cur.fetchall()]


def atualizar_raw_sections(conn, med_id: int, raw_sections: Dict[str, Any],
                           conteudo_atual, dry_run: bool) -> None:
    if dry_run:
        log.info(f"  [dry-run] id={med_id}: {len(raw_sections)} seções seriam gravadas")
        return

    # Merge em Python para evitar problemas com json vs jsonb no Postgres
    if isinstance(conteudo_atual, str):
        try:
            conteudo_atual = json.loads(conteudo_atual)
        except Exception:
            conteudo_atual = {}
    conteudo = dict(conteudo_atual or {})
    conteudo['raw_sections'] = raw_sections

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE medicamento SET conteudo_estruturado = %s WHERE id = %s",
            (json.dumps(conteudo, ensure_ascii=False), med_id),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Extração HTML
# ---------------------------------------------------------------------------
def _eh_vazio(texto: str) -> bool:
    t = texto.lower()
    return any(f in t for f in FRASES_VAZIO)


def _limpar_multilinha(texto: Optional[str]) -> Optional[str]:
    if not texto:
        return None
    texto = str(texto).replace('\r\n', '\n').replace('\r', '\n')
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    return texto.strip() or None


def extrair_raw_sections(html: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, 'html.parser')
    raw: Dict[str, Optional[str]] = {}

    for sec in soup.find_all('section', class_='container-content'):
        title_el = sec.find(class_='title-content')
        if not title_el:
            continue
        titulo = title_el.get_text(strip=True)

        disabled = sec.find('p', class_='disabled')
        if disabled:
            conteudo = disabled.get_text(strip=True)
            raw[titulo] = None if _eh_vazio(conteudo) else _limpar_multilinha(conteudo)
            continue

        content_div = sec.find(class_='content-comercial-info')
        if not content_div:
            raw[titulo] = None
            continue

        conteudo = _limpar_multilinha(content_div.get_text(separator='\n', strip=True))
        raw[titulo] = None if (not conteudo or _eh_vazio(conteudo)) else conteudo

    # Garante que apenas seções conhecidas e com conteúdo são gravadas
    return {k: v for k, v in raw.items() if k in SECOES_ESPERADAS and v}


def aceitar_cookies(page) -> None:
    for sel in COOKIE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                page.wait_for_load_state("networkidle", timeout=5000)
                return
        except Exception:
            pass


def carregar_pagina(page, pid: int) -> Optional[str]:
    url = f"{PRODUTO_URL}/{pid}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        aceitar_cookies(page)
        return page.content()
    except PWTimeoutError:
        log.warning(f"  Timeout ao carregar produto {pid}")
        return None
    except Exception as e:
        log.warning(f"  Erro ao carregar produto {pid}: {e}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apenas-faltantes", action="store_true",
                        help="Só processa medicamentos sem raw_sections gravado")
    parser.add_argument("--limite", type=int, default=None,
                        help="Máximo de medicamentos a processar")
    parser.add_argument("--visible", action="store_true",
                        help="Abre o browser visível (útil para debug)")
    args = parser.parse_args()

    conn = conectar()
    medicamentos = listar_medicamentos_para_backfill(conn, args.apenas_faltantes, args.limite)
    log.info(f"Medicamentos a processar: {len(medicamentos)}")

    if not medicamentos:
        log.info("Nada a fazer.")
        return

    ok = 0
    erros = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.visible,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 900})
        page = context.new_page()

        for i, med in enumerate(medicamentos, 1):
            pid = med['vetsmart_produto_id']
            nome = med['nome']
            log.info(f"[{i}/{len(medicamentos)}] {nome} (vetsmart_id={pid})")

            html = carregar_pagina(page, pid)
            if not html:
                erros += 1
                continue

            raw_sections = extrair_raw_sections(html)
            if not raw_sections:
                log.warning(f"  Nenhuma seção extraída para {nome}")
                erros += 1
            else:
                secoes_encontradas = list(raw_sections.keys())
                log.info(f"  Seções: {secoes_encontradas}")
                atualizar_raw_sections(
                    conn, med['id'], raw_sections,
                    med.get('conteudo_estruturado'), args.dry_run,
                )
                ok += 1

            if i < len(medicamentos):
                time.sleep(DELAY_ENTRE_PAGINAS)

        browser.close()

    conn.close()
    log.info(f"\nConcluído: {ok} ok, {erros} erros de {len(medicamentos)} total")
    if args.dry_run:
        log.info("(dry-run: nenhuma alteração foi salva)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
