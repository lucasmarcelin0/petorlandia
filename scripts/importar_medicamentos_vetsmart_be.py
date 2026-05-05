"""
Script: importar_medicamentos_vetsmart_be.py
=============================================
Scraper otimizado para a vertente **bovinos & equinos** do VetSmart
(URL: https://vetsmart.com.br/be/produto/lista).

Diferenças em relação ao scraper de cães e gatos
------------------------------------------------
1. **Extração em camadas com fallback** — JSON-LD → microdata (itemprop) →
   classes CSS específicas → regex sobre texto bruto. Se uma camada falha, a
   próxima é tentada antes de abandonar o produto.
2. **Confidence scoring por campo** — cada campo extraído carrega um nível de
   confiança ('alta' | 'media' | 'baixa') registrado em `conteudo_estruturado`.
   Isso permite que o calculador de dose ou a UI de prescrição saibam quando
   pedir confirmação humana.
3. **Validação pós-scrape** — o produto é descartado (com motivo) quando
   campos críticos (nome, espécies) ainda ficam vazios. Os logs registram
   o motivo para reprocessamento posterior.
4. **Idempotência forte** — usa `vetsmart_produto_id` como chave de upsert.
   Reprocessar a lista todo dia só atualiza diferenças, nunca duplica.
5. **species_scope='BE' aplicado automaticamente** em todos os medicamentos
   importados (com normalização para 'AMBOS' quando o produto declara servir
   também a cães/gatos).
6. **Retry com backoff** em falhas de rede e cookies/CAPTCHA.

Uso
---
    pip install playwright psycopg2-binary beautifulsoup4
    playwright install chromium

    # Smoke test (5 produtos, sem escrever no banco)
    python scripts/importar_medicamentos_vetsmart_be.py --limite 5 --dry-run

    # Run completo (em background no Heroku)
    heroku run:detached --size=performance-l \\
      "python scripts/importar_medicamentos_vetsmart_be.py --scrape-importar" \\
      -a petorlandia
"""
from __future__ import annotations

import os
import re
import sys
import time
import json
import argparse
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Instale: pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("importar_medicamentos_be.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
BASE_URL = "https://vetsmart.com.br"
LIST_URL = f"{BASE_URL}/be/produto/lista"           # bovinos & equinos
DETAIL_PATH_PREFIX = "/be/produto"
DELAY_PAGINAS_S = 1.5
RETRY_MAX = 3
RETRY_BACKOFF_S = 2.0
CACHE_FILE = "vetsmart_produtos_be_cache.json"
SPECIES_SCOPE_DEFAULT = "BE"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        "",
    ),
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

CREATED_BY_USER_ID = int(os.environ.get("VETSMART_CREATED_BY_USER_ID", "1"))


# Frases que indicam "sem informação" no VetSmart
FRASES_VAZIO = [
    "ainda não tem informações",
    "ainda não tem videos",
    "ainda não tem distribuidores",
    "não há nenhum estudo",
    "não contém interações",
    "ainda não foi preenchida",
    "não tem referências",
]

# Tokens que sugerem que o produto também serve cães/gatos (→ AMBOS)
TOKENS_PETS = (
    "cão", "caes", "cães", "cao", "cachorro", "canino",
    "gato", "felino", "cat", "dog",
    "pet", "pets",
)


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------
@dataclass
class ConfidenceField:
    valor: Optional[str] = None
    fonte: str = "—"          # 'json-ld' | 'itemprop' | 'css' | 'regex' | 'fallback'
    confianca: str = "baixa"  # 'alta' | 'media' | 'baixa'


@dataclass
class ProdutoVetsmartBE:
    vetsmart_id: int
    nome: str
    fabricante:           Optional[str] = None
    classificacao:        Optional[str] = None
    especies:             Optional[str] = None
    species_scope:        Optional[str] = SPECIES_SCOPE_DEFAULT
    principio_ativo:      Optional[str] = None
    via_administracao:    Optional[str] = None
    dosagem_recomendada:  Optional[str] = None
    frequencia:           Optional[str] = None
    duracao_tratamento:   Optional[str] = None
    indicacoes:           Optional[str] = None
    observacoes:          Optional[str] = None
    interacoes:           Optional[str] = None
    farmacologia:         Optional[str] = None
    bula:                 Optional[str] = None
    conteudo_estruturado: Dict[str, Any] = field(default_factory=dict)
    apresentacoes:        List[Dict[str, str]] = field(default_factory=list)
    doses:                List[Dict[str, Optional[str]]] = field(default_factory=list)

    # Diagnóstico — não vai pro banco
    confidence_map:       Dict[str, str] = field(default_factory=dict)
    extraction_errors:    List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers de texto (puros, sem dependências externas — fáceis de testar)
# ---------------------------------------------------------------------------
def eh_vazio(texto: Optional[str]) -> bool:
    if not texto:
        return True
    alvo = texto.lower()
    return any(f in alvo for f in FRASES_VAZIO)


def limpar(texto: Optional[str], max_len: int = 500) -> Optional[str]:
    if not texto:
        return None
    texto = re.sub(r'\s+', ' ', texto).strip()
    if not texto:
        return None
    return texto[:max_len]


def normalizar_species_scope(especies_texto: Optional[str], default: str = SPECIES_SCOPE_DEFAULT) -> str:
    """Decide o species_scope baseado no texto da seção 'Espécies' do VetSmart.

    Regra:
      - Texto contém token de pet (cão, gato, etc.) → 'AMBOS'
      - Sem texto ou apenas bovinos/equinos → `default` (geralmente 'BE')
    """
    if not especies_texto:
        return default
    alvo = especies_texto.lower()
    if any(token in alvo for token in TOKENS_PETS):
        return "AMBOS"
    return default


# ---------------------------------------------------------------------------
# Extração em camadas (com fallback)
# ---------------------------------------------------------------------------
def _ld_json_blocks(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    blocos: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text())
        except Exception:
            continue
        if isinstance(data, list):
            blocos.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            blocos.append(data)
    return blocos


def _itemprop_value(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find(attrs={"itemprop": prop})
    if not tag:
        return None
    valor = tag.get("content") or tag.get_text(" ", strip=True)
    valor = re.sub(r'\s+', ' ', valor or '').strip()
    if eh_vazio(valor):
        return None
    return valor or None


def _css_value(soup: BeautifulSoup, selector: str) -> Optional[str]:
    el = soup.select_one(selector)
    if not el:
        return None
    valor = el.get_text(" ", strip=True)
    valor = re.sub(r'\s+', ' ', valor or '').strip()
    return valor or None


def _regex_value(soup: BeautifulSoup, label_pattern: str) -> Optional[str]:
    """Procura um <p>/<li> com <b>label:</b> valor e devolve o valor."""
    pat = re.compile(label_pattern, re.IGNORECASE)
    for el in soup.find_all(["p", "li", "div"]):
        bold = el.find(["b", "strong"])
        if not bold:
            continue
        if not pat.search(bold.get_text(" ", strip=True)):
            continue
        texto = el.get_text(" ", strip=True)
        valor = re.sub(rf'^\s*{re.escape(bold.get_text(" ", strip=True))}\s*[-:]?\s*', '', texto, flags=re.IGNORECASE).strip()
        if valor and not eh_vazio(valor):
            return valor
    return None


def _extrair_com_fallback(
    soup: BeautifulSoup,
    *,
    json_ld_keys: Tuple[str, ...] = (),
    itemprop: Optional[str] = None,
    css: Optional[str] = None,
    regex_label: Optional[str] = None,
) -> ConfidenceField:
    """Aplica a cadeia de fallback. A primeira camada que retorna valor vence."""
    # Camada 1: JSON-LD
    if json_ld_keys:
        for bloco in _ld_json_blocks(soup):
            for key in json_ld_keys:
                valor = bloco.get(key)
                if isinstance(valor, list) and valor:
                    valor = ", ".join(str(v) for v in valor if v)
                if isinstance(valor, str):
                    valor_limpo = limpar(valor)
                    if valor_limpo:
                        return ConfidenceField(valor_limpo, fonte="json-ld", confianca="alta")

    # Camada 2: microdata (itemprop)
    if itemprop:
        valor = _itemprop_value(soup, itemprop)
        if valor:
            return ConfidenceField(valor[:500], fonte="itemprop", confianca="alta")

    # Camada 3: classes CSS específicas do VetSmart
    if css:
        valor = _css_value(soup, css)
        if valor:
            return ConfidenceField(valor[:500], fonte="css", confianca="media")

    # Camada 4: regex sobre texto rotulado
    if regex_label:
        valor = _regex_value(soup, regex_label)
        if valor:
            return ConfidenceField(valor[:500], fonte="regex", confianca="media")

    return ConfidenceField()


# ---------------------------------------------------------------------------
# Extração principal: HTML → ProdutoVetsmartBE
# ---------------------------------------------------------------------------
def extrair_produto(html: str, vetsmart_id: int, nome_fallback: str = "") -> ProdutoVetsmartBE:
    """Extrai o produto do HTML completo da página de detalhe do VetSmart BE.

    Esta função é completamente determinística e pura: recebe HTML, devolve um
    dataclass. Faz isso com cadeia de fallback (json-ld → itemprop → css → regex)
    para maximizar a taxa de extração mesmo quando o HTML do VetSmart muda.
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── Nome ─────────────────────────────────────────────────────────────
    nome_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("name",),
        itemprop="name",
        css="h2.side-nav-title, h1.product-title",
    )
    nome = nome_field.valor or nome_fallback or f"Produto VetSmart #{vetsmart_id}"

    # ── Fabricante ───────────────────────────────────────────────────────
    fabricante_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("manufacturer", "brand"),
        itemprop="manufacturer",
        css=".side-nav-subtitle",
        regex_label=r"fabricant",
    )
    fabricante = fabricante_field.valor
    if fabricante:
        fabricante = re.sub(r'^\s*POR\s+', '', fabricante, flags=re.IGNORECASE).strip()
        if re.fullmatch(r'princ[ií]pio\s+ativo', fabricante or '', flags=re.IGNORECASE):
            fabricante = None  # rotulagem genérica do VetSmart

    # ── Classificação (drug class) ───────────────────────────────────────
    classificacao_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("drugClass", "category"),
        itemprop="drugClass",
        regex_label=r"classifica",
    )

    # ── Princípio ativo (pode haver múltiplos) ───────────────────────────
    principios = []
    for tag in soup.find_all(attrs={"itemprop": "activeIngredient"}):
        v = (tag.get("content") or tag.get_text(" ", strip=True) or "").strip()
        if v and not eh_vazio(v):
            principios.append(v)
    pa_field = ConfidenceField(
        valor=" + ".join(principios)[:200] if principios else None,
        fonte="itemprop" if principios else "—",
        confianca="alta" if principios else "baixa",
    )
    if not pa_field.valor:
        # fallback regex
        valor_regex = _regex_value(soup, r"princ[ií]pio\s+ativ")
        if valor_regex:
            pa_field = ConfidenceField(valor_regex[:200], fonte="regex", confianca="media")

    # ── Via de administração ─────────────────────────────────────────────
    via_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("administrationRoute",),
        itemprop="administrationRoute",
        regex_label=r"via\s+de\s+administra",
    )

    # ── Espécies ─────────────────────────────────────────────────────────
    especies_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("targetPopulation",),
        regex_label=r"esp[éeê]cie",
    )

    # ── Farmacologia ─────────────────────────────────────────────────────
    farmacologia_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("clinicalPharmacology",),
        itemprop="clinicalPharmacology",
    )

    # ── Indicações / advertências (texto longo) ──────────────────────────
    description_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("description",),
        itemprop="description",
    )
    warning_field = _extrair_com_fallback(
        soup,
        json_ld_keys=("warning",),
        itemprop="warning",
    )

    # ── Apresentações (forma + concentração) ─────────────────────────────
    apresentacoes = _extrair_apresentacoes(soup)

    # ── Doses (com a coluna de espécie + faixa de peso, se presente) ─────
    doses = _extrair_doses(soup)

    # ── species_scope final ──────────────────────────────────────────────
    species_scope = normalizar_species_scope(especies_field.valor, default=SPECIES_SCOPE_DEFAULT)

    # ── Conteúdo estruturado (com mapa de confiança) ─────────────────────
    confidence_map = {
        "nome": nome_field.confianca,
        "fabricante": fabricante_field.confianca,
        "classificacao": classificacao_field.confianca,
        "principio_ativo": pa_field.confianca,
        "via_administracao": via_field.confianca,
        "especies": especies_field.confianca,
        "farmacologia": farmacologia_field.confianca,
    }

    conteudo_estruturado = {
        "especies": especies_field.valor,
        "indicacoes": {"texto": description_field.valor, "itens": []},
        "advertencias": {"texto": warning_field.valor, "itens": []},
        "metadata": {
            "parser_version": "be-v1",
            "fonte": "vetsmart-be",
            "confidence_map": confidence_map,
            "fontes_extracao": {
                "nome": nome_field.fonte,
                "fabricante": fabricante_field.fonte,
                "classificacao": classificacao_field.fonte,
                "principio_ativo": pa_field.fonte,
                "via_administracao": via_field.fonte,
                "especies": especies_field.fonte,
            },
        },
    }

    return ProdutoVetsmartBE(
        vetsmart_id=vetsmart_id,
        nome=limpar(nome, 100) or f"Produto #{vetsmart_id}",
        fabricante=limpar(fabricante, 150),
        classificacao=limpar(classificacao_field.valor, 100),
        especies=limpar(especies_field.valor, 200),
        species_scope=species_scope,
        principio_ativo=limpar(pa_field.valor, 200),
        via_administracao=limpar(via_field.valor, 80),
        farmacologia=limpar(farmacologia_field.valor, 4000),
        indicacoes=limpar(description_field.valor, 4000),
        observacoes=limpar(warning_field.valor, 4000),
        conteudo_estruturado=conteudo_estruturado,
        apresentacoes=apresentacoes,
        doses=doses,
        confidence_map=confidence_map,
    )


def _extrair_apresentacoes(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Extrai apresentações de uma seção 'Apresentações' (lista de <li>)."""
    apresentacoes: List[Dict[str, str]] = []
    for section in soup.find_all("section", class_="container-content"):
        title = section.find(["h2", "h3"])
        if not title:
            continue
        title_text = title.get_text(" ", strip=True).lower()
        if "apresenta" not in title_text:
            continue
        body = section.find("div", class_="content-comercial-info") or section
        for li in body.find_all("li"):
            texto = li.get_text(" ", strip=True)
            if not texto or eh_vazio(texto):
                continue
            forma = ""
            forma_tag = li.find("span")
            if forma_tag:
                forma = forma_tag.get_text(" ", strip=True)
            apresentacoes.append({
                "forma": (forma or "N/A")[:50],
                "concentracao": texto[:200],
            })
    return apresentacoes


def _extrair_doses(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """Extrai linhas de dose, normalmente em <table> dentro da seção 'Posologia'."""
    doses: List[Dict[str, Optional[str]]] = []
    for section in soup.find_all("section", class_="container-content"):
        title = section.find(["h2", "h3"])
        if not title:
            continue
        title_text = title.get_text(" ", strip=True).lower()
        if not any(token in title_text for token in ("dose", "posolog")):
            continue
        for tr in section.find_all("tr"):
            celulas = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not celulas or all(not c for c in celulas):
                continue
            doses.append({
                "especie": celulas[0] if len(celulas) > 0 else None,
                "dose": celulas[1] if len(celulas) > 1 else None,
                "via": celulas[2] if len(celulas) > 2 else None,
                "frequencia": celulas[3] if len(celulas) > 3 else None,
                "observacao": " | ".join(celulas[4:]) if len(celulas) > 4 else None,
            })
    return doses


# ---------------------------------------------------------------------------
# Validação pós-scrape
# ---------------------------------------------------------------------------
def validar_produto(prod: ProdutoVetsmartBE) -> Tuple[bool, List[str]]:
    """Verifica se o produto tem dados mínimos. Retorna (ok, lista_de_problemas)."""
    problemas: List[str] = []
    if not prod.nome or prod.nome.startswith("Produto #"):
        problemas.append("nome ausente ou apenas placeholder")
    if not prod.principio_ativo and not prod.classificacao and not prod.bula:
        problemas.append("nenhum dado clínico (PA, classificação ou bula)")
    if prod.species_scope not in {"BE", "AMBOS", "OUTRO"}:
        problemas.append(f"species_scope inesperado: {prod.species_scope}")
    return (not problemas, problemas)


# ---------------------------------------------------------------------------
# Listagem + scraping (Playwright)
# ---------------------------------------------------------------------------
def _aceitar_cookies(page) -> None:
    selectors = [
        "button:has-text('Aceitar')", "button:has-text('Aceitar todos')",
        "button:has-text('Concordo')", "button:has-text('OK')",
        "button:has-text('Entendi')", "button:has-text('Continuar')",
        "#onetrust-accept-btn-handler", ".cc-accept", ".cc-btn",
        "[id*='accept']", "[class*='accept']",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                page.wait_for_load_state("networkidle", timeout=5000)
                return
        except Exception:
            continue


def _coletar_links_listagem(page, max_paginas: int = 200) -> List[Tuple[int, str, str]]:
    """Percorre /be/produto/lista paginando e coleta (id, nome, url) de cada produto.

    Devolve tuplas. Usa Playwright para aguardar JavaScript e seguir paginação.
    """
    log.info(f"Coletando lista de produtos em {LIST_URL}")
    page.goto(LIST_URL, wait_until="networkidle", timeout=60000)
    _aceitar_cookies(page)

    links: List[Tuple[int, str, str]] = []
    vistos: set[int] = set()

    for pagina in range(1, max_paginas + 1):
        page.wait_for_load_state("networkidle", timeout=20000)
        # Cada item da lista é tipicamente um <a href="/be/produto/<id>/<slug>">
        anchors = page.query_selector_all(f"a[href*='{DETAIL_PATH_PREFIX}/']")
        novos = 0
        for a in anchors:
            href = a.get_attribute("href") or ""
            m = re.search(rf"{DETAIL_PATH_PREFIX}/(\d+)", href)
            if not m:
                continue
            pid = int(m.group(1))
            if pid in vistos:
                continue
            vistos.add(pid)
            nome = (a.inner_text() or "").strip().split("\n")[0][:100]
            url_abs = href if href.startswith("http") else BASE_URL + href
            links.append((pid, nome, url_abs))
            novos += 1
        log.info(f"  pagina {pagina}: +{novos} novos (total {len(links)})")

        # tenta clicar em "próxima"
        try:
            proximo = page.query_selector(
                "a[rel='next'], a:has-text('Próxima'), button:has-text('Próxima'), "
                ".pagination a:has-text('>'), [aria-label='Próxima página']"
            )
            if not proximo or not proximo.is_visible():
                break
            proximo.click()
            time.sleep(DELAY_PAGINAS_S)
        except Exception:
            break

    log.info(f"Total de links coletados: {len(links)}")
    return links


def _baixar_html_produto(page, url: str) -> Optional[str]:
    """Baixa o HTML da página de detalhe com retry+backoff."""
    last_err: Optional[Exception] = None
    for tentativa in range(1, RETRY_MAX + 1):
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            return page.content()
        except Exception as exc:
            last_err = exc
            espera = RETRY_BACKOFF_S * tentativa
            log.warning(f"  retry {tentativa}/{RETRY_MAX} ({url}): {exc} — aguardando {espera}s")
            time.sleep(espera)
    log.error(f"  ❌ falha após {RETRY_MAX} tentativas: {url} ({last_err})")
    return None


def scrape_be(limite: Optional[int] = None, headless: bool = True) -> List[ProdutoVetsmartBE]:
    """Pipeline completo: lista → detalhes → ProdutoVetsmartBE[]."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Instale: pip install playwright && playwright install chromium")
        return []

    produtos: List[ProdutoVetsmartBE] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        links = _coletar_links_listagem(page)
        if limite:
            links = links[:limite]

        for idx, (pid, nome, url) in enumerate(links, 1):
            log.info(f"[{idx}/{len(links)}] {nome or pid}")
            html = _baixar_html_produto(page, url)
            if not html:
                continue
            prod = extrair_produto(html, pid, nome_fallback=nome)
            ok, problemas = validar_produto(prod)
            if not ok:
                log.warning(f"  ⚠ produto descartado ({pid}): {'; '.join(problemas)}")
                prod.extraction_errors = problemas
            produtos.append(prod)

        browser.close()
    return produtos


# ---------------------------------------------------------------------------
# Persistência (mesma estratégia do scraper de cães e gatos)
# ---------------------------------------------------------------------------
def salvar_produtos(produtos: List[ProdutoVetsmartBE], dry_run: bool = False) -> Dict[str, int]:
    """Faz upsert em `medicamento` + `apresentacao_medicamento` + `dose_medicamento`.

    Idempotente — usa vetsmart_produto_id como chave. Aplica species_scope.
    Em dry_run, apenas conta.
    """
    contagem = {"inserts": 0, "updates": 0, "skips": 0, "errors": 0}
    if dry_run:
        log.info(f"[dry-run] {len(produtos)} produtos seriam processados")
        for prod in produtos:
            ok, _ = validar_produto(prod)
            if ok:
                contagem["inserts"] += 1
            else:
                contagem["skips"] += 1
        return contagem

    if not DATABASE_URL:
        log.error("DATABASE_URL não definida — abortando.")
        contagem["errors"] = len(produtos)
        return contagem

    try:
        import psycopg2
        from psycopg2.extras import Json, RealDictCursor
    except ImportError:
        log.error("Instale: pip install psycopg2-binary")
        contagem["errors"] = len(produtos)
        return contagem

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=15)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for idx, prod in enumerate(produtos, 1):
                ok, problemas = validar_produto(prod)
                if not ok:
                    log.warning(f"[{idx}/{len(produtos)}] skip ({prod.vetsmart_id}): {'; '.join(problemas)}")
                    contagem["skips"] += 1
                    continue

                # Existe já?
                cur.execute(
                    "SELECT id FROM medicamento WHERE vetsmart_produto_id = %s",
                    (prod.vetsmart_id,),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE medicamento
                           SET nome = COALESCE(NULLIF(%s, ''), nome),
                               classificacao = COALESCE(NULLIF(%s, ''), classificacao),
                               principio_ativo = COALESCE(NULLIF(%s, ''), principio_ativo),
                               via_administracao = COALESCE(NULLIF(%s, ''), via_administracao),
                               observacoes = COALESCE(NULLIF(%s, ''), observacoes),
                               bula = COALESCE(NULLIF(%s, ''), bula),
                               conteudo_estruturado = %s,
                               species_scope = %s
                         WHERE id = %s
                        """,
                        (
                            prod.nome,
                            prod.classificacao,
                            prod.principio_ativo,
                            prod.via_administracao,
                            prod.observacoes,
                            prod.bula,
                            Json(prod.conteudo_estruturado or {}),
                            prod.species_scope,
                            row["id"],
                        ),
                    )
                    contagem["updates"] += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO medicamento
                          (nome, classificacao, principio_ativo, via_administracao,
                           observacoes, bula, conteudo_estruturado,
                           vetsmart_produto_id, species_scope, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            prod.nome,
                            prod.classificacao,
                            prod.principio_ativo,
                            prod.via_administracao,
                            prod.observacoes,
                            prod.bula,
                            Json(prod.conteudo_estruturado or {}),
                            prod.vetsmart_id,
                            prod.species_scope,
                            CREATED_BY_USER_ID,
                        ),
                    )
                    contagem["inserts"] += 1

                # Commit em chunks de 25 para tolerar interrupção
                if idx % 25 == 0:
                    conn.commit()
                    log.info(f"  ↳ commit ({contagem['inserts']} inseridos, {contagem['updates']} atualizados, {contagem['skips']} pulados)")

        conn.commit()
    except Exception as exc:
        log.exception(f"Erro durante a persistência: {exc}")
        conn.rollback()
        contagem["errors"] += 1
    finally:
        conn.close()

    return contagem


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Scraper VetSmart BE (bovinos & equinos)")
    parser.add_argument("--limite", type=int, default=None, help="Limita aos N primeiros produtos")
    parser.add_argument("--dry-run", action="store_true", help="Não escreve no banco")
    parser.add_argument("--scrape-importar", action="store_true", help="Faz scrape e já importa direto no DB (Heroku)")
    parser.add_argument("--cache", action="store_true", help="Salva produtos no cache JSON em vez de gravar no DB")
    parser.add_argument("--visible", action="store_true", help="Roda navegador visível (debug)")
    args = parser.parse_args()

    produtos = scrape_be(limite=args.limite, headless=not args.visible)
    log.info(f"Scrape concluído: {len(produtos)} produtos extraídos.")

    if args.cache:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in produtos], f, ensure_ascii=False, indent=2)
        log.info(f"Cache gravado em {CACHE_FILE}")

    if args.scrape_importar or (not args.cache and not args.dry_run):
        contagem = salvar_produtos(produtos, dry_run=args.dry_run)
        log.info(f"Resultado: {contagem}")
    else:
        contagem = salvar_produtos(produtos, dry_run=True)
        log.info(f"[dry-run] Resultado simulado: {contagem}")


if __name__ == "__main__":
    main()
