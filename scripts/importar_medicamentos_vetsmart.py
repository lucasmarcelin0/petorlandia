"""
Script: importar_medicamentos_vetsmart.py  (v2 – Playwright)
=============================================================
Faz scraping completo do VetSmart (cães e gatos) usando Playwright
(renderiza JavaScript) e importa/enriquece os medicamentos no banco.

DEPENDÊNCIAS:
  pip install playwright psycopg2-binary
  playwright install chromium

FASES:
  1. Conecta ao banco e lista medicamentos já cadastrados.
  2. Faz scraping de TODOS os produtos do VetSmart (/cg/produto/lista).
  3. Para cada produto, acessa a página de detalhe e extrai os dados.
  4. Cruza pelo nome e enriquece campos vazios (não sobrescreve dados existentes).
  5. Adiciona medicamentos novos que ainda não existem no banco.

USO:
  # Instalar dependências:
  pip install playwright psycopg2-binary
  playwright install chromium

  # Modo simulação (não altera nada no banco):
  python scripts/importar_medicamentos_vetsmart.py --dry-run

  # Testar com os primeiros 10 produtos:
  python scripts/importar_medicamentos_vetsmart.py --limite 10 --dry-run

  # Executar de verdade:
  python scripts/importar_medicamentos_vetsmart.py

  # Usar cache JSON já gerado (sem refazer scraping):
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

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("importar_medicamentos.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
BASE_URL       = "https://vetsmart.com.br"
LIST_URL       = f"{BASE_URL}/cg/produto/lista"
DELAY_PAGINAS  = 1.0   # segundos entre páginas de detalhe
CACHE_FILE     = "vetsmart_produtos_cache.json"

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

CREATED_BY_USER_ID = 1  # ajuste para o ID de um admin real do seu banco


# ---------------------------------------------------------------------------
# Estrutura de dados
# ---------------------------------------------------------------------------
@dataclass
class ProdutoVetsmart:
    vetsmart_id: int
    nome: str
    classificacao:       Optional[str] = None
    principio_ativo:     Optional[str] = None
    via_administracao:   Optional[str] = None
    dosagem_recomendada: Optional[str] = None
    frequencia:          Optional[str] = None
    duracao_tratamento:  Optional[str] = None
    observacoes:         Optional[str] = None
    bula:                Optional[str] = None
    apresentacoes: List[Dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
def conectar_banco():
    log.info("Conectando ao banco PostgreSQL…")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=15)
    conn.autocommit = False
    log.info("Conexão OK.")
    return conn


def listar_medicamentos_banco(conn) -> List[Dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.id, m.nome, m.classificacao, m.principio_ativo,
                   m.via_administracao, m.dosagem_recomendada, m.frequencia,
                   m.duracao_tratamento, m.observacoes, m.bula,
                   COALESCE(
                       json_agg(json_build_object(
                           'forma', a.forma, 'concentracao', a.concentracao
                       )) FILTER (WHERE a.id IS NOT NULL), '[]'
                   ) AS apresentacoes
            FROM medicamento m
            LEFT JOIN apresentacao_medicamento a ON a.medicamento_id = m.id
            GROUP BY m.id ORDER BY m.nome
        """)
        return [dict(r) for r in cur.fetchall()]


def imprimir_medicamentos_banco(medicamentos: List[Dict]):
    if not medicamentos:
        print("\n⚠️  Nenhum medicamento no banco ainda.\n")
        return
    print(f"\n{'='*70}")
    print(f"  MEDICAMENTOS NO BANCO ({len(medicamentos)} registros)")
    print(f"{'='*70}")
    for m in medicamentos:
        print(f"\n  [{m['id']}] {m['nome']}")
        for label, key in [
            ("Classificação",   "classificacao"),
            ("Princípio ativo", "principio_ativo"),
            ("Via",             "via_administracao"),
            ("Dosagem",         "dosagem_recomendada"),
            ("Frequência",      "frequencia"),
            ("Duração",         "duracao_tratamento"),
        ]:
            v = m.get(key) or "— (vazio)"
            print(f"       {label:<20}: {v}")
    print(f"\n{'='*70}\n")


# ---------------------------------------------------------------------------
# Scraping com Playwright
# ---------------------------------------------------------------------------

def _limpar_nome(texto: str) -> str:
    """Remove prefixos/sufixos indesejados que o VetSmart coloca em botões."""
    # Remove "Avaliar" que é um botão de avaliação na página
    texto = re.sub(r"^\s*Avaliar\s+", "", texto, flags=re.IGNORECASE)
    # Remove nome de fabricante colado ao final (ex: "Acepran® 0,2%Vetnil" → "Acepran® 0,2%")
    texto = re.sub(r"([a-záéíóúâêôãõçA-Z®°]{2,})\s*$", lambda m: "", texto).strip()
    return texto.strip()


def scrape_lista_produtos_playwright(page) -> List[Dict[str, Any]]:
    """Coleta todos os produtos da página de lista."""
    log.info(f"Abrindo lista: {LIST_URL}")
    page.goto(LIST_URL, wait_until="networkidle", timeout=60000)

    produtos = []
    pagina = 1

    while True:
        log.info(f"  → Página {pagina} da lista")
        # Aguarda os cards carregarem
        try:
            page.wait_for_selector("a[href*='/produto/']", timeout=15000)
        except Exception:
            log.warning("  Timeout aguardando cards. Tentando continuar…")

        # Coleta todos os links de produto
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
            # Nome: texto do link, removendo botões colados
            nome_raw = (link.inner_text() or "").strip()
            nome = _limpar_nome(nome_raw) or f"Produto #{pid}"
            url = BASE_URL + href if href.startswith("/") else href
            produtos.append({"id": pid, "nome": nome, "url": url})
            encontrados += 1

        log.info(f"     {encontrados} novos produtos nessa página (total: {len(produtos)})")

        if encontrados == 0:
            break

        # Verifica próxima página
        proximo = page.query_selector("a[rel='next'], .paginacao .proxima, .pagination .next, button.prox")
        if not proximo:
            break
        proximo.click()
        page.wait_for_load_state("networkidle", timeout=15000)
        pagina += 1
        time.sleep(0.5)

    log.info(f"Lista completa: {len(produtos)} produtos encontrados.")
    return produtos


def _texto_elemento(page, *seletores) -> Optional[str]:
    """Retorna o texto do primeiro seletor que encontrar um elemento."""
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


def _extrair_campo_tabela(page, *chaves_rotulo) -> Optional[str]:
    """
    Procura nas linhas de tabela/dl um rótulo que contenha alguma das chaves
    e retorna o valor correspondente.
    """
    # Tenta tabelas
    rows = page.query_selector_all("table tr, dl, .info-row")
    for row in rows:
        celulas = row.query_selector_all("td, dd, .value")
        rotulos = row.query_selector_all("th, dt, .label, strong")
        if not rotulos and not celulas:
            continue
        rotulo_txt = " ".join(
            (r.inner_text() or "").lower() for r in rotulos
        )
        if not rotulo_txt:
            tds = row.query_selector_all("td")
            if len(tds) >= 2:
                rotulo_txt = (tds[0].inner_text() or "").lower()
                celulas = [tds[1]]
        for chave in chaves_rotulo:
            if chave in rotulo_txt and celulas:
                valor = (celulas[0].inner_text() or "").strip()
                if valor and valor != "—" and valor != "-":
                    return valor

    # Tenta busca por texto no DOM inteiro
    texto_pagina = page.inner_text("body") or ""
    for chave in chaves_rotulo:
        pat = re.compile(
            rf"{re.escape(chave)}[:\s]+([^\n]{{4,120}})", re.IGNORECASE
        )
        m = pat.search(texto_pagina)
        if m:
            val = m.group(1).strip()
            if val:
                return val[:200]
    return None


def scrape_detalhe_produto_playwright(page, info: Dict) -> ProdutoVetsmart:
    """Acessa a página de detalhe de um produto e extrai os campos."""
    pid  = info["id"]
    url  = info["url"]
    nome_base = info["nome"]

    log.debug(f"  Detalhe: {nome_base} ({url})")
    page.goto(url, wait_until="networkidle", timeout=60000)

    # Aguarda conteúdo principal
    try:
        page.wait_for_selector("h1, .nome-produto, .product-title, .drug-name", timeout=10000)
    except Exception:
        pass

    # ---- Nome ----
    nome_raw = (
        _texto_elemento(page,
            "h1.nome-produto", ".nome-produto", ".product-title",
            ".drug-name", "h1"
        ) or nome_base
    )
    # Remove "Avaliar" e fabricante colados
    nome = re.sub(r"^\s*Avaliar\s+", "", nome_raw, flags=re.IGNORECASE).strip()
    # Remove texto de fabricante que aparece colado ao final (ex: "Produto XyzVetnil")
    nome = re.sub(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)$", "", nome).strip()
    if not nome:
        nome = nome_base
    nome = nome[:100]

    # ---- Campos estruturados ----
    classificacao = _extrair_campo_tabela(page,
        "classifica", "categoria", "grupo terapêutico", "classe terapêutica",
        "tipo de produto"
    )
    principio_ativo = _extrair_campo_tabela(page,
        "princípio ativo", "principio ativo", "substância ativa",
        "substância", "ativo"
    )
    via_administracao = _extrair_campo_tabela(page,
        "via de administra", "via administra", "via:"
    )
    dosagem_recomendada = _extrair_campo_tabela(page,
        "dose recomendada", "dosagem recomendada", "dose:", "dosagem:"
    )
    frequencia = _extrair_campo_tabela(page,
        "frequência", "frequencia", "intervalo de administra", "posologia"
    )
    duracao_tratamento = _extrair_campo_tabela(page,
        "duração do tratamento", "duracao do tratamento",
        "tempo de tratamento", "período de tratamento"
    )

    # ---- Observações (contraindicações, interações) ----
    obs_partes = []
    for chave in ["contraindicaç", "interaç medicamentosa", "efeito adverso",
                  "precauç", "aviso", "advertência"]:
        val = _extrair_campo_tabela(page, chave)
        if val:
            obs_partes.append(val)
    observacoes = "\n".join(obs_partes) or None

    # ---- Bula ----
    bula_el = page.query_selector(
        ".bula, .bula-texto, #bula, .farmacologia, "
        ".descricao-completa, .product-description, article.content"
    )
    bula = None
    if bula_el:
        bula = (bula_el.inner_text() or "").strip() or None

    # ---- Apresentações ----
    apresentacoes = []
    apres_els = page.query_selector_all(
        ".apresentacao, .apresentacoes li, .concentracao-item, "
        ".product-variant, .forma-apresentacao"
    )
    for apres_el in apres_els:
        texto_ap = (apres_el.inner_text() or "").strip()
        if not texto_ap:
            continue
        m = re.match(
            r"(comprimido|cápsula|capsula|ampola|frasco|solução|solucao|"
            r"suspensão|suspensao|pomada|creme|gel|spray|injetável|injetavel|"
            r"oral|líquido|liquido|sachê|bisnaga|gotas?)[^\d]*"
            r"([\d,.]+ ?(?:mg|g|ml|mL|UI|IU|%)[/\w]*)?",
            texto_ap, re.IGNORECASE
        )
        if m:
            forma = m.group(1).capitalize()
            conc  = m.group(2) or texto_ap[:80]
            apresentacoes.append({"forma": forma, "concentracao": conc.strip()})
        else:
            apresentacoes.append({"forma": "N/A", "concentracao": texto_ap[:100]})

    return ProdutoVetsmart(
        vetsmart_id        = pid,
        nome               = nome,
        classificacao      = (classificacao  or "")[:100] or None,
        principio_ativo    = (principio_ativo or "")[:100] or None,
        via_administracao  = (via_administracao or "")[:50] or None,
        dosagem_recomendada= dosagem_recomendada,
        frequencia         = (frequencia or "")[:100] or None,
        duracao_tratamento = duracao_tratamento,
        observacoes        = observacoes,
        bula               = bula,
        apresentacoes      = apresentacoes,
    )


# ---------------------------------------------------------------------------
# Cruzar e atualizar banco
# ---------------------------------------------------------------------------
def _normalizar(texto: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return nfkd.encode("ASCII", "ignore").decode("ASCII").lower().strip()


def cruzar_e_atualizar(conn, medicamentos_banco, produtos_vetsmart, dry_run=False):
    stats = {"atualizados": 0, "inseridos": 0}
    banco_por_nome = {_normalizar(m["nome"]): m for m in medicamentos_banco}

    for produto in produtos_vetsmart:
        nome_norm  = _normalizar(produto.nome)
        existente  = banco_por_nome.get(nome_norm)

        if existente:
            updates = {}
            mapa = {
                "classificacao":       produto.classificacao,
                "principio_ativo":     produto.principio_ativo,
                "via_administracao":   produto.via_administracao,
                "dosagem_recomendada": produto.dosagem_recomendada,
                "frequencia":          produto.frequencia,
                "duracao_tratamento":  produto.duracao_tratamento,
                "observacoes":         produto.observacoes,
                "bula":                produto.bula,
            }
            for campo_db, valor_novo in mapa.items():
                if not existente.get(campo_db) and valor_novo:
                    updates[campo_db] = valor_novo

            if updates:
                log.info(f"  ATUALIZAR '{existente['nome']}' → {list(updates.keys())}")
                if not dry_run:
                    set_clause = ", ".join(f"{k} = %s" for k in updates)
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE medicamento SET {set_clause} WHERE id = %s",
                            list(updates.values()) + [existente["id"]],
                        )
                stats["atualizados"] += 1

            # Apresentações novas
            apres_existentes = set()
            apres_atual = existente.get("apresentacoes") or []
            if isinstance(apres_atual, str):
                apres_atual = json.loads(apres_atual)
            for ap in apres_atual:
                apres_existentes.add((
                    _normalizar(ap.get("forma", "")),
                    _normalizar(ap.get("concentracao", ""))
                ))
            for ap in produto.apresentacoes:
                chave_ap = (
                    _normalizar(ap.get("forma", "")),
                    _normalizar(ap.get("concentracao", ""))
                )
                if chave_ap not in apres_existentes and ap.get("forma") != "N/A":
                    log.info(f"    + Apresentação: {ap['forma']} {ap['concentracao']}")
                    if not dry_run:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO apresentacao_medicamento "
                                "(medicamento_id, forma, concentracao) VALUES (%s,%s,%s)",
                                (existente["id"], ap["forma"][:50], ap["concentracao"][:100])
                            )
                    apres_existentes.add(chave_ap)
        else:
            log.info(f"  INSERIR '{produto.nome}' (novo)")
            if not dry_run:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO medicamento
                          (nome, classificacao, principio_ativo, via_administracao,
                           dosagem_recomendada, frequencia, duracao_tratamento,
                           observacoes, bula, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                    """, (
                        produto.nome[:100],
                        (produto.classificacao  or "")[:100] or None,
                        (produto.principio_ativo or "")[:100] or None,
                        (produto.via_administracao or "")[:50] or None,
                        produto.dosagem_recomendada,
                        (produto.frequencia or "")[:100] or None,
                        produto.duracao_tratamento,
                        produto.observacoes,
                        produto.bula,
                        CREATED_BY_USER_ID,
                    ))
                    novo_id = cur.fetchone()["id"]
                    for ap in produto.apresentacoes:
                        if ap.get("forma") and ap["forma"] != "N/A":
                            cur.execute(
                                "INSERT INTO apresentacao_medicamento "
                                "(medicamento_id, forma, concentracao) VALUES (%s,%s,%s)",
                                (novo_id, ap["forma"][:50], ap["concentracao"][:100])
                            )
            stats["inseridos"] += 1

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run",      action="store_true", help="Simula sem alterar o banco.")
    p.add_argument("--somente-listar", action="store_true", help="Lista banco e sai.")
    p.add_argument("--limite",       type=int, default=0, help="Limita nº de produtos (0=todos).")
    p.add_argument("--usar-cache",   action="store_true", help=f"Usa {CACHE_FILE} já existente.")
    p.add_argument("--created-by",   type=int, default=CREATED_BY_USER_ID)
    p.add_argument("--headless",     action="store_true", default=True,
                   help="Executa navegador sem interface gráfica (padrão: True).")
    p.add_argument("--visible",      action="store_true",
                   help="Abre o navegador visível (útil para depurar).")
    return p.parse_args()


def main():
    args   = parse_args()
    global CREATED_BY_USER_ID
    CREATED_BY_USER_ID = args.created_by
    headless = not args.visible

    # -----------------------------------------------------------------------
    # Fase 1 – Banco
    # -----------------------------------------------------------------------
    conn = conectar_banco()
    medicamentos_banco = listar_medicamentos_banco(conn)
    imprimir_medicamentos_banco(medicamentos_banco)

    if args.somente_listar:
        conn.close()
        return

    # -----------------------------------------------------------------------
    # Fase 2 – Scraping
    # -----------------------------------------------------------------------
    produtos_scrapeados: List[ProdutoVetsmart] = []

    if args.usar_cache and os.path.exists(CACHE_FILE):
        log.info(f"Carregando cache de '{CACHE_FILE}'…")
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache_data = json.load(f)
        for d in cache_data:
            p = ProdutoVetsmart(**d)
            produtos_scrapeados.append(p)
        log.info(f"{len(produtos_scrapeados)} produtos carregados do cache.")
    else:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error(
                "Playwright não instalado. Execute:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )
            conn.close()
            sys.exit(1)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
            )
            page = context.new_page()

            # Lista de produtos
            lista_produtos = scrape_lista_produtos_playwright(page)
            if args.limite > 0:
                lista_produtos = lista_produtos[: args.limite]
                log.info(f"Limitado a {args.limite} produtos.")

            total = len(lista_produtos)
            for i, info in enumerate(lista_produtos, 1):
                log.info(f"[{i}/{total}] {info['nome']}")
                try:
                    produto = scrape_detalhe_produto_playwright(page, info)
                    produtos_scrapeados.append(produto)
                except Exception as exc:
                    log.warning(f"  ⚠ Erro em {info['id']}: {exc}")
                time.sleep(DELAY_PAGINAS)

            browser.close()

        log.info(f"Scraping concluído: {len(produtos_scrapeados)}/{total} produtos.")

        # Salva cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([
                {
                    "vetsmart_id":        p.vetsmart_id,
                    "nome":               p.nome,
                    "classificacao":      p.classificacao,
                    "principio_ativo":    p.principio_ativo,
                    "via_administracao":  p.via_administracao,
                    "dosagem_recomendada":p.dosagem_recomendada,
                    "frequencia":         p.frequencia,
                    "duracao_tratamento": p.duracao_tratamento,
                    "observacoes":        p.observacoes,
                    "bula":               p.bula,
                    "apresentacoes":      p.apresentacoes,
                }
                for p in produtos_scrapeados
            ], f, ensure_ascii=False, indent=2)
        log.info(f"Cache salvo em '{CACHE_FILE}'.")

    # -----------------------------------------------------------------------
    # Fase 3 – Cruzar e atualizar
    # -----------------------------------------------------------------------
    if args.dry_run:
        log.info("\n⚠️  MODO DRY-RUN — nenhuma alteração será feita.\n")

    stats = cruzar_e_atualizar(conn, medicamentos_banco, produtos_scrapeados, dry_run=args.dry_run)

    if not args.dry_run:
        conn.commit()
        log.info("Commit realizado.")

    conn.close()

    print(f"""
{'='*60}
  RESULTADO FINAL
{'='*60}
  Medicamentos no banco (antes):  {len(medicamentos_banco)}
  Produtos coletados VetSmart:    {len(produtos_scrapeados)}
  Registros atualizados:          {stats['atualizados']}
  Registros inseridos (novos):    {stats['inseridos']}
  Modo dry-run:                   {'SIM' if args.dry_run else 'NÃO'}
{'='*60}
""")


if __name__ == "__main__":
    main()
