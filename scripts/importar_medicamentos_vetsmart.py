"""
Script: importar_medicamentos_vetsmart.py  (v3 – Playwright + cookie consent)
==============================================================================
Faz scraping completo do VetSmart (cães e gatos) usando Playwright,
aceitando o banner de cookies/privacidade antes de extrair os dados.

USO:
  pip install playwright psycopg2-binary
  playwright install chromium

  # Testar com 5 produtos (sem alterar banco):
  python scripts/importar_medicamentos_vetsmart.py --limite 5 --dry-run

  # Executar completo:
  python scripts/importar_medicamentos_vetsmart.py

  # Usar cache já gerado:
  python scripts/importar_medicamentos_vetsmart.py --usar-cache
"""

import os
import sys
import time
import re
import json
import argparse
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("importar_medicamentos.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BASE_URL      = "https://vetsmart.com.br"
LIST_URL      = f"{BASE_URL}/cg/produto/lista"
DELAY_PAGINAS = 1.5
CACHE_FILE    = "vetsmart_produtos_cache.json"

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

CREATED_BY_USER_ID = 1


@dataclass
class ProdutoVetsmart:
    vetsmart_id: int
    nome: str
    classificacao:        Optional[str] = None
    principio_ativo:      Optional[str] = None
    via_administracao:    Optional[str] = None
    dosagem_recomendada:  Optional[str] = None
    frequencia:           Optional[str] = None
    duracao_tratamento:   Optional[str] = None
    observacoes:          Optional[str] = None
    bula:                 Optional[str] = None
    fabricante:           Optional[str] = None
    apresentacoes: List[Dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def conectar_banco():
    log.info("Conectando ao banco…")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=15)
    conn.autocommit = False
    return conn


def listar_medicamentos_banco(conn) -> List[Dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.id, m.nome, m.classificacao, m.principio_ativo,
                   m.via_administracao, m.dosagem_recomendada, m.frequencia,
                   m.duracao_tratamento, m.observacoes, m.bula,
                   COALESCE(
                       json_agg(json_build_object('forma', a.forma, 'concentracao', a.concentracao))
                       FILTER (WHERE a.id IS NOT NULL), '[]'
                   ) AS apresentacoes
            FROM medicamento m
            LEFT JOIN apresentacao_medicamento a ON a.medicamento_id = m.id
            GROUP BY m.id ORDER BY m.nome
        """)
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Cookie / privacidade
# ---------------------------------------------------------------------------
COOKIE_SELECTORS = [
    "button:has-text('Aceitar')",
    "button:has-text('Aceitar todos')",
    "button:has-text('Concordo')",
    "button:has-text('OK')",
    "button:has-text('Entendi')",
    "button:has-text('Continuar')",
    "a:has-text('Aceitar')",
    "[id*='accept']",
    "[class*='accept']",
    "[id*='cookie'] button",
    "[class*='cookie'] button",
    "[id*='lgpd'] button",
    "[class*='lgpd'] button",
    "[class*='consent'] button",
    "#onetrust-accept-btn-handler",
    ".cc-accept",
    ".cc-btn",
    ".cookie-accept",
]


def aceitar_cookies(page) -> bool:
    for sel in COOKIE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                log.info(f"  Cookie aceito via: {sel}")
                page.wait_for_load_state("networkidle", timeout=5000)
                return True
        except Exception:
            pass
    return False


def aguardar_e_aceitar_cookies(page, timeout=8000):
    try:
        page.wait_for_selector(
            "[id*='cookie'], [class*='cookie'], [id*='lgpd'], [class*='lgpd'], "
            "button:has-text('Aceitar'), button:has-text('Concordo')",
            timeout=timeout
        )
        time.sleep(0.5)
        aceitar_cookies(page)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Scraping da lista
# ---------------------------------------------------------------------------
def scrape_lista_produtos(page) -> List[Dict[str, Any]]:
    log.info(f"Abrindo lista: {LIST_URL}")
    page.goto(LIST_URL, wait_until="networkidle", timeout=60000)
    aguardar_e_aceitar_cookies(page)

    produtos = []
    pagina = 1

    while True:
        log.info(f"  → Página {pagina}")
        try:
            page.wait_for_selector("a[href*='/produto/']", timeout=15000)
        except Exception:
            break

        links = page.query_selector_all("a[href*='/produto/']")
        encontrados = 0
        for link in links:
            href = link.get_attribute("href") or ""
            m = re.search(r"/(?:cg|CG)/produto/(\d+)", href, re.IGNORECASE)
            if not m:
                continue
            pid = int(m.group(1))
            if any(p["id"] == pid for p in produtos):
                continue
            nome_raw = (link.inner_text() or "").strip()
            nome = re.sub(r"^\s*(Avaliar|Ver|Detalhes)\s+", "", nome_raw, flags=re.IGNORECASE).strip()
            nome = nome or f"Produto #{pid}"
            url = BASE_URL + href if href.startswith("/") else href
            produtos.append({"id": pid, "nome": nome[:100], "url": url})
            encontrados += 1

        log.info(f"     +{encontrados} produtos (total: {len(produtos)})")
        if encontrados == 0:
            break

        proximo = page.query_selector(
            "a[rel='next'], .pagination .next, a:has-text('Próxima'), a:has-text('>')"
        )
        if not proximo:
            break
        proximo.click()
        page.wait_for_load_state("networkidle", timeout=15000)
        pagina += 1
        time.sleep(0.8)

    log.info(f"Total: {len(produtos)} produtos na lista.")
    return produtos


# ---------------------------------------------------------------------------
# Scraping do detalhe
# ---------------------------------------------------------------------------
def _texto(page, *seletores) -> Optional[str]:
    for sel in seletores:
        try:
            el = page.query_selector(sel)
            if el:
                t = (el.inner_text() or "").strip()
                if t:
                    return t
        except Exception:
            pass
    return None


def _extrair_rotulo(texto: str, *rotulos) -> Optional[str]:
    for rotulo in rotulos:
        pat = re.compile(
            rf"{re.escape(rotulo)}\s*[:\-]?\s*([^\n]{{3,300}})",
            re.IGNORECASE
        )
        m = pat.search(texto)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val and len(val) > 2 and "privacidade" not in val.lower():
                return val[:300]
    return None


def scrape_detalhe_produto(page, info: Dict) -> ProdutoVetsmart:
    pid       = info["id"]
    url       = info["url"]
    nome_base = info["nome"]

    page.goto(url, wait_until="networkidle", timeout=60000)
    aguardar_e_aceitar_cookies(page, timeout=4000)

    try:
        page.wait_for_selector("h1, .nome-produto, .product-title", timeout=10000)
    except Exception:
        pass

    time.sleep(1.0)

    try:
        texto = page.inner_text("body") or ""
    except Exception:
        texto = ""

    # Remove ruído do banner de privacidade do texto
    texto = re.sub(
        r"(política de privacidade|termos de uso|cookies?|lgpd).*?(aceitar|concordo|entendi)",
        " ", texto, flags=re.IGNORECASE | re.DOTALL
    )

    # Nome
    nome_raw = _texto(page, "h1.nome-produto", ".nome-produto", "h1") or nome_base
    nome = re.sub(r"^\s*(Avaliar|Ver)\s+", "", nome_raw, flags=re.IGNORECASE).strip()
    nome = (nome or nome_base)[:100]

    # Campos
    fabricante        = _extrair_rotulo(texto, "Fabricante", "Laboratório", "Empresa", "Marca")
    classificacao     = _extrair_rotulo(texto, "Classificação", "Categoria", "Grupo terapêutico", "Classe terapêutica")
    principio_ativo   = _extrair_rotulo(texto, "Princípio ativo", "Substância ativa", "Composição", "Componente ativo")
    via_administracao = _extrair_rotulo(texto, "Via de administração", "Via de administracao", "Administração")
    dosagem           = _extrair_rotulo(texto, "Dose recomendada", "Dosagem recomendada", "Dosagem", "Posologia", "Dose ")
    frequencia        = _extrair_rotulo(texto, "Frequência", "Frequencia", "Intervalo de administração")
    duracao           = _extrair_rotulo(texto, "Duração do tratamento", "Duração", "Período de tratamento")

    obs_partes = []
    for rot in ["Contraindicações", "Reações adversas", "Efeitos adversos", "Precauções", "Interações medicamentosas"]:
        val = _extrair_rotulo(texto, rot)
        if val:
            obs_partes.append(f"{rot}: {val}")
    observacoes = "\n".join(obs_partes) or None

    # Bula
    bula_el = page.query_selector(
        ".bula, .bula-texto, #bula, .farmacologia, "
        ".descricao-completa, .product-description, .conteudo-bula"
    )
    bula = None
    if bula_el:
        bula_txt = (bula_el.inner_text() or "").strip()
        if bula_txt and "privacidade" not in bula_txt.lower()[:100]:
            bula = bula_txt[:5000]

    # Apresentações
    apresentacoes = []
    for el in page.query_selector_all(".apresentacao, .apresentacoes li, .concentracao-item, .product-variant"):
        t = (el.inner_text() or "").strip()
        if not t or "privacidade" in t.lower():
            continue
        m = re.match(
            r"(comprimido|cápsula|capsula|ampola|frasco|solução|suspensão|"
            r"pomada|creme|gel|spray|injetável|líquido|sachê|gotas?)[^\d]*"
            r"([\d,.]+ ?(?:mg|g|ml|mL|UI|%)[/\w]*)?",
            t, re.IGNORECASE
        )
        if m:
            apresentacoes.append({"forma": m.group(1).capitalize(), "concentracao": (m.group(2) or t[:80]).strip()})
        else:
            apresentacoes.append({"forma": "N/A", "concentracao": t[:100]})

    return ProdutoVetsmart(
        vetsmart_id         = pid,
        nome                = nome,
        fabricante          = (fabricante or "")[:100] or None,
        classificacao       = (classificacao or "")[:100] or None,
        principio_ativo     = (principio_ativo or "")[:200] or None,
        via_administracao   = (via_administracao or "")[:50] or None,
        dosagem_recomendada = dosagem,
        frequencia          = (frequencia or "")[:100] or None,
        duracao_tratamento  = duracao,
        observacoes         = observacoes,
        bula                = bula,
        apresentacoes       = apresentacoes,
    )


# ---------------------------------------------------------------------------
# Banco – cruzar e atualizar
# ---------------------------------------------------------------------------
def _norm(texto: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", texto or "").encode("ASCII", "ignore").decode().lower().strip()


def cruzar_e_atualizar(conn, medicamentos_banco, produtos, dry_run=False):
    stats = {"atualizados": 0, "inseridos": 0, "sem_alteracao": 0}
    por_nome = {_norm(m["nome"]): m for m in medicamentos_banco}

    for p in produtos:
        existente = por_nome.get(_norm(p.nome))

        if existente:
            updates = {}
            for campo, valor in {
                "classificacao": p.classificacao,
                "principio_ativo": p.principio_ativo,
                "via_administracao": p.via_administracao,
                "dosagem_recomendada": p.dosagem_recomendada,
                "frequencia": p.frequencia,
                "duracao_tratamento": p.duracao_tratamento,
                "observacoes": p.observacoes,
                "bula": p.bula,
            }.items():
                if not existente.get(campo) and valor:
                    updates[campo] = valor

            if updates:
                log.info(f"  ATUALIZAR '{existente['nome']}': {list(updates.keys())}")
                if not dry_run:
                    set_clause = ", ".join(f"{k} = %s" for k in updates)
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE medicamento SET {set_clause} WHERE id = %s",
                            list(updates.values()) + [existente["id"]],
                        )
                stats["atualizados"] += 1
            else:
                stats["sem_alteracao"] += 1

            # Apresentações novas
            apres_existentes = {
                (_norm(a.get("forma", "")), _norm(a.get("concentracao", "")))
                for a in (existente.get("apresentacoes") or [])
            }
            for ap in p.apresentacoes:
                chave = (_norm(ap.get("forma", "")), _norm(ap.get("concentracao", "")))
                if chave not in apres_existentes and ap.get("forma") not in ("N/A", ""):
                    if not dry_run:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO apresentacao_medicamento (medicamento_id, forma, concentracao) VALUES (%s,%s,%s)",
                                (existente["id"], ap["forma"][:50], ap["concentracao"][:100])
                            )
                    apres_existentes.add(chave)
        else:
            log.info(f"  INSERIR: '{p.nome}'")
            if not dry_run:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO medicamento
                          (nome, classificacao, principio_ativo, via_administracao,
                           dosagem_recomendada, frequencia, duracao_tratamento,
                           observacoes, bula, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """, (
                        p.nome[:100],
                        (p.classificacao or "")[:100] or None,
                        (p.principio_ativo or "")[:200] or None,
                        (p.via_administracao or "")[:50] or None,
                        p.dosagem_recomendada, (p.frequencia or "")[:100] or None,
                        p.duracao_tratamento, p.observacoes, p.bula, CREATED_BY_USER_ID,
                    ))
                    novo_id = cur.fetchone()["id"]
                    for ap in p.apresentacoes:
                        if ap.get("forma") not in ("N/A", "", None):
                            cur.execute(
                                "INSERT INTO apresentacao_medicamento (medicamento_id, forma, concentracao) VALUES (%s,%s,%s)",
                                (novo_id, ap["forma"][:50], ap["concentracao"][:100])
                            )
            stats["inseridos"] += 1

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run",        action="store_true")
    p.add_argument("--somente-listar", action="store_true")
    p.add_argument("--limite",         type=int, default=0)
    p.add_argument("--usar-cache",     action="store_true")
    p.add_argument("--created-by",     type=int, default=CREATED_BY_USER_ID)
    p.add_argument("--visible",        action="store_true")
    args = p.parse_args()

    global CREATED_BY_USER_ID
    CREATED_BY_USER_ID = args.created_by

    conn = conectar_banco()
    medicamentos_banco = listar_medicamentos_banco(conn)
    log.info(f"Medicamentos no banco: {len(medicamentos_banco)}")

    if args.somente_listar:
        for m in medicamentos_banco:
            print(f"  [{m['id']}] {m['nome']}")
        conn.close()
        return

    produtos: List[ProdutoVetsmart] = []

    if args.usar_cache and os.path.exists(CACHE_FILE):
        log.info(f"Carregando cache '{CACHE_FILE}'…")
        with open(CACHE_FILE, encoding="utf-8") as f:
            for d in json.load(f):
                d.pop("fabricante", None)
                produtos.append(ProdutoVetsmart(**d))
        log.info(f"{len(produtos)} produtos do cache.")
    else:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Instale: pip install playwright && playwright install chromium")
            conn.close()
            sys.exit(1)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.visible)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="pt-BR",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            # Aceita cookies na home primeiro
            log.info("Abrindo home para aceitar cookies…")
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            aguardar_e_aceitar_cookies(page, timeout=8000)
            time.sleep(1)

            lista = scrape_lista_produtos(page)
            if args.limite > 0:
                lista = lista[:args.limite]

            total = len(lista)
            for i, info in enumerate(lista, 1):
                log.info(f"[{i}/{total}] {info['nome']}")
                try:
                    prod = scrape_detalhe_produto(page, info)
                    produtos.append(prod)
                    log.info(f"    ✓ pa={prod.principio_ativo!r} via={prod.via_administracao!r} apres={len(prod.apresentacoes)}")
                except Exception as exc:
                    log.warning(f"    ⚠ Erro: {exc}")
                    produtos.append(ProdutoVetsmart(vetsmart_id=info["id"], nome=info["nome"]))
                time.sleep(DELAY_PAGINAS)

            browser.close()

        # Salva cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([{
                "vetsmart_id": p.vetsmart_id, "nome": p.nome,
                "classificacao": p.classificacao, "principio_ativo": p.principio_ativo,
                "via_administracao": p.via_administracao, "dosagem_recomendada": p.dosagem_recomendada,
                "frequencia": p.frequencia, "duracao_tratamento": p.duracao_tratamento,
                "observacoes": p.observacoes, "bula": p.bula, "apresentacoes": p.apresentacoes,
            } for p in produtos], f, ensure_ascii=False, indent=2)
        log.info(f"Cache salvo em '{CACHE_FILE}'.")

    if args.dry_run:
        log.info("⚠️  DRY-RUN — sem alterações no banco.")

    stats = cruzar_e_atualizar(conn, medicamentos_banco, produtos, dry_run=args.dry_run)

    if not args.dry_run:
        conn.commit()

    conn.close()

    print(f"""
{'='*60}
  RESULTADO
{'='*60}
  Banco (antes):     {len(medicamentos_banco)}
  Scrapeados:        {len(produtos)}
  Atualizados:       {stats['atualizados']}
  Inseridos:         {stats['inseridos']}
  Sem alteração:     {stats['sem_alteracao']}
  Dry-run:           {'SIM' if args.dry_run else 'NÃO'}
{'='*60}
""")


if __name__ == "__main__":
    main()
