"""
Script: importar_medicamentos_vetsmart.py  (v4 – extração precisa com BeautifulSoup)
=====================================================================================
Usa Playwright para carregar as páginas (JS) e BeautifulSoup para extrair
os dados com base na estrutura real do DOM do VetSmart.

Estrutura real descoberta via diagnóstico:
  - Nome:          <h2 class="side-nav-title">
  - Fabricante:    <div class="side-nav-subtitle">  → "POR XYZ"
  - Classificação: <p><b>Classificaçāo:</b> valor</p>
  - Espécies:      <p><b>Espécies:</b> valor</p>
  - Seções:        <section class="container-content">
                     <h2 class="title-content"><strong>Título</strong></h2>
                     <div class="content-comercial-info"> ... </div>
                     <p class="disabled"> ← indica seção vazia
  - Apresentações: <ul><li>Nome, <span>forma</span>(qtd)</li></ul>
                   dentro da seção "Apresentações e concentrações"

USO:
  pip install playwright psycopg2-binary beautifulsoup4
  playwright install chromium

  python scripts/importar_medicamentos_vetsmart.py --limite 5 --dry-run --visible
  python scripts/importar_medicamentos_vetsmart.py
  python scripts/importar_medicamentos_vetsmart.py --usar-cache
"""

import os, sys, time, re, json, argparse, logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Instale: pip install beautifulsoup4")
    sys.exit(1)

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

# Frases que indicam seção vazia no VetSmart
FRASES_VAZIO = [
    "ainda não tem informações",
    "ainda não tem videos",
    "ainda não tem distribuidores",
    "não há nenhum estudo",
    "não contém interações",
    "ainda não foi preenchida",
    "não tem referências",
]


# ---------------------------------------------------------------------------
# Estrutura de dados
# ---------------------------------------------------------------------------
@dataclass
class ProdutoVetsmart:
    vetsmart_id: int
    nome: str
    fabricante:           Optional[str] = None
    classificacao:        Optional[str] = None
    especies:             Optional[str] = None
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
    "button:has-text('Aceitar')", "button:has-text('Aceitar todos')",
    "button:has-text('Concordo')", "button:has-text('OK')",
    "button:has-text('Entendi')", "button:has-text('Continuar')",
    "a:has-text('Aceitar')", "[id*='accept']", "[class*='accept']",
    "[id*='cookie'] button", "[class*='cookie'] button",
    "[id*='lgpd'] button", "[class*='lgpd'] button",
    "[class*='consent'] button", "#onetrust-accept-btn-handler",
    ".cc-accept", ".cc-btn",
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
            "[id*='cookie'], [class*='cookie'], [id*='lgpd'], "
            "button:has-text('Aceitar'), button:has-text('Concordo'), "
            "button:has-text('ENTENDI')",
            timeout=timeout
        )
        time.sleep(0.5)
        aceitar_cookies(page)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Extração via BeautifulSoup (estrutura real do VetSmart)
# ---------------------------------------------------------------------------
def _eh_vazio(texto: str) -> bool:
    """Verifica se o texto de uma seção indica conteúdo vazio."""
    t = texto.lower()
    return any(f in t for f in FRASES_VAZIO)


def _limpar(texto: Optional[str], max_len: int = 500) -> Optional[str]:
    if not texto:
        return None
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto[:max_len] if texto else None


def extrair_produto_do_html(html: str, pid: int, nome_fallback: str) -> ProdutoVetsmart:
    """Extrai todos os dados do produto a partir do HTML completo da página."""
    soup = BeautifulSoup(html, 'html.parser')

    # ── Nome ──────────────────────────────────────────────────────────────
    nome_el = soup.find('h2', class_='side-nav-title')
    nome = nome_el.get_text(strip=True) if nome_el else nome_fallback
    nome = nome[:100] or nome_fallback

    # ── Fabricante ────────────────────────────────────────────────────────
    fab_el = soup.find(class_='side-nav-subtitle')
    fabricante = None
    if fab_el:
        # Usa separator=' ' para preservar espaços entre elementos filhos
        fab_raw = fab_el.get_text(separator=' ', strip=True)
        fabricante = re.sub(r'^POR\s+', '', fab_raw, flags=re.IGNORECASE).strip() or None

    # ── Classificação e Espécies ──────────────────────────────────────────
    classificacao = None
    especies = None
    for p in soup.find_all('p'):
        b = p.find('b')
        if not b:
            continue
        b_txt = b.get_text(strip=True)
        # Usa separator=' ' para não colapsar "Classificação:Valor" em uma string sem espaço
        p_txt = p.get_text(separator=' ', strip=True)
        if 'Classifica' in b_txt and not classificacao:
            # VetSmart usa 'ā' (mácron U+0101) em vez de 'ã', então usamos [\w\W]{1,3}
            classificacao = re.sub(
                r'Classifica.{1,4}o\s*:\s*', '', p_txt, flags=re.IGNORECASE
            ).strip() or None
        if 'Espécie' in b_txt and not especies:
            especies = re.sub(
                r'Espécies?\s*:\s*', '', p_txt, flags=re.IGNORECASE
            ).strip() or None

    # ── Coleta todas as seções ────────────────────────────────────────────
    secoes: Dict[str, Optional[str]] = {}
    secoes_uls: Dict[str, Any] = {}

    for sec in soup.find_all('section', class_='container-content'):
        title_el = sec.find(class_='title-content')
        if not title_el:
            continue
        titulo = title_el.get_text(strip=True)

        # Seção vazia?
        disabled = sec.find('p', class_='disabled')
        if disabled:
            conteudo = disabled.get_text(strip=True)
            secoes[titulo] = None if _eh_vazio(conteudo) else conteudo
            continue

        content_div = sec.find(class_='content-comercial-info')
        if not content_div:
            secoes[titulo] = None
            continue

        # Remove o título do conteúdo para não repetir
        for el in content_div.find_all(class_='title-content'):
            el.decompose()

        # Salva a <ul> para parsing especial das apresentações
        ul = content_div.find('ul')
        if ul:
            secoes_uls[titulo] = ul

        conteudo = content_div.get_text(separator='\n', strip=True)
        secoes[titulo] = None if _eh_vazio(conteudo) else conteudo

    # ── Apresentações ─────────────────────────────────────────────────────
    apresentacoes = []
    ul_apres = secoes_uls.get('Apresentações e concentrações')
    if ul_apres:
        for li in ul_apres.find_all('li'):
            forma_el = li.find('span')
            forma = forma_el.get_text(strip=True) if forma_el else ''
            # Concentração / embalagem = texto do li sem o span
            if forma_el:
                forma_el.extract()
            li_txt = li.get_text(separator=' ', strip=True)
            # Remove traço inicial e nome do produto
            conc = re.sub(r'^[-–]\s*' + re.escape(nome) + r'\s*,?\s*', '', li_txt, flags=re.I).strip()
            conc = re.sub(r'^,\s*', '', conc).strip()
            if forma or conc:
                apresentacoes.append({
                    'forma': forma[:50] if forma else 'N/A',
                    'concentracao': conc[:100] if conc else ''
                })

    # ── Administração e doses ─────────────────────────────────────────────
    admin_txt = secoes.get('Administração e doses') or ''
    admin = _parsear_admin_doses(admin_txt)

    via_administracao   = admin['via']
    dosagem_recomendada = admin['dose']
    frequencia          = admin['frequencia']
    duracao_tratamento  = admin['duracao']

    # ── Indicações / Observações / Interações / Farmacologia ─────────────
    indicacoes  = _limpar(secoes.get('Indicações e contraindicações'), 800)
    interacoes  = _limpar(secoes.get('Interações medicamentosas'), 500)
    farmacologia = _limpar(secoes.get('Farmacologia'), 800)

    # Observações = indicações + interações concatenadas
    obs_partes = []
    if indicacoes:
        obs_partes.append(f"Indicações/Contraindicações:\n{indicacoes}")
    if interacoes:
        obs_partes.append(f"Interações medicamentosas:\n{interacoes}")
    observacoes = '\n\n'.join(obs_partes) or None

    # Bula = farmacologia ou descritivo do produto (seção Sobre)
    sobre_txt = secoes.get('Sobre') or ''
    bula = _limpar(farmacologia or _extrair_descritivo(sobre_txt), 5000)

    # Princípio ativo — tenta extrair da seção Sobre
    principio_ativo = _extrair_campo(
        sobre_txt,
        'Princípio ativo', 'Princípio Ativo', 'Substância ativa',
        'Composição', 'Componente ativo', 'Fórmula'
    )
    # Fallback: classificação como princípio se não encontrou
    if not principio_ativo and especies:
        principio_ativo = None  # não força

    return ProdutoVetsmart(
        vetsmart_id         = pid,
        nome                = nome,
        fabricante          = fabricante,
        classificacao       = _limpar(classificacao, 100),
        especies            = _limpar(especies, 100),
        principio_ativo     = _limpar(principio_ativo, 200),
        via_administracao   = _limpar(via_administracao, 80),
        dosagem_recomendada = _limpar(dosagem_recomendada, 300),
        frequencia          = _limpar(frequencia, 100),
        duracao_tratamento  = _limpar(duracao_tratamento, 100),
        indicacoes          = indicacoes,
        observacoes         = observacoes,
        interacoes          = interacoes,
        farmacologia        = farmacologia,
        bula                = bula,
        apresentacoes       = apresentacoes,
    )


def _parsear_admin_doses(texto: str) -> dict:
    """
    Parseia a seção 'Administração e doses' do VetSmart linha a linha.

    Estrutura real observada:
      Via(s)
        Oral / Tópica / Oftálmica ...
        Videos da(s) via(s)          ← ruído (botão)
      Frequência de utilização
        2 vezes ao dia
      Dosagem indicada
        Doses
        Dosagem para Cães e Gatos
        Recomendado 5 mg/kg
        Modo de usar ...
      Duração do tratamento
        7 dias
      Observações
        ...
    """
    TITULOS = {
        'via(s)':                    'via',
        'frequência de utilização':  'frequencia',
        'frequencia de utilizacao':  'frequencia',
        'dosagem indicada':          'dose',
        'duração do tratamento':     'duracao',
        'duracao do tratamento':     'duracao',
        'período de tratamento':     'duracao',
        'observações':               'obs',
        'observacoes':               'obs',
    }
    # Linhas que são ruído dentro das subseções
    RUIDO = {
        'videos da(s) via(s)',
        'doses',
        'dosagem para caes e gatos',
        'dosagem para caes',
        'dosagem para gatos',
        'dosagem para caes e gatos',
        'dosagem para cao',
        'dosagem para gato',
        'recomendado',
        'modo de usar',
        'dosagem indicada',
        'dosagem',
    }
    # Prefixos a remover mesmo que não sejam linha exata
    PREFIXOS_RUIDO = [
        'dosagem para caes e gatos',
        'dosagem para caes',
        'dosagem para gatos',
        'dosagem para cao',
        'dosagem para gato',
    ]

    import unicodedata
    def _norm_titulo(t):
        nfkd = unicodedata.normalize('NFKD', t.lower().strip())
        return nfkd.encode('ASCII', 'ignore').decode()

    coleta: Dict[str, list] = {'via': [], 'dose': [], 'frequencia': [], 'duracao': [], 'obs': []}
    atual = None

    for linha in texto.split('\n'):
        linha = linha.strip()
        if not linha:
            continue
        ln = _norm_titulo(linha)
        if ln in TITULOS:
            atual = TITULOS[ln]
            continue
        if ln in RUIDO or any(ln.startswith(r) for r in PREFIXOS_RUIDO):
            continue
        if atual and atual in coleta:
            coleta[atual].append(linha)

    def _juntar(linhas, max_len=300):
        if not linhas:
            return None
        txt = ' '.join(linhas).strip()
        return txt[:max_len] if len(txt) > 2 else None

    return {
        'via':       _juntar(coleta['via'][:2], 80),
        'dose':      _juntar(coleta['dose'][:6], 300),
        'frequencia': _juntar(coleta['frequencia'][:2], 100),
        'duracao':   _juntar(coleta['duracao'][:2], 100),
        'obs':       _juntar(coleta['obs'][:4], 400),
    }


def _extrair_campo(texto: str, *rotulos) -> Optional[str]:
    """Extrai o valor de um campo a partir de rótulos conhecidos no texto."""
    for rotulo in rotulos:
        pat = re.compile(
            rf'{re.escape(rotulo)}\s*[:\-]?\s*([^\n]{{3,250}})',
            re.IGNORECASE
        )
        m = pat.search(texto)
        if m:
            val = m.group(1).strip().rstrip('.')
            if val and len(val) > 2 and not _eh_vazio(val):
                return val[:250]
    return None


def _extrair_campo_estrito(texto: str, *rotulos) -> Optional[str]:
    """Como _extrair_campo, mas exige rótulo exato seguido de ':' para evitar falsos positivos."""
    for rotulo in rotulos:
        pat = re.compile(
            rf'^{re.escape(rotulo)}\s*:\s*(.{{3,250}})$',
            re.IGNORECASE | re.MULTILINE
        )
        m = pat.search(texto)
        if m:
            val = m.group(1).strip()
            if val and len(val) > 2 and not _eh_vazio(val):
                return val[:250]
    return None


# Padrões específicos para via de administração
_VIA_PATTERNS = [
    # "Via de administração: oral" ou "Via: oral" na mesma linha
    re.compile(r'Via\s+de\s+administra[çc][aã]o\s*:\s*([^\n]{2,80})', re.I),
    re.compile(r'\bVia\s*:\s*([^\n]{2,60})', re.I),
    # "administração oral" / "administração intravenosa" etc.
    re.compile(
        r'administra[çc][aã]o\s+(oral|intramuscular|intravenosa|subcutânea|tópica|'
        r'oftálmica|auricular|nasal|retal|IM|IV|SC|EV)\b',
        re.I
    ),
    # "via oral", "via IM", etc. em qualquer parte do texto
    re.compile(
        r'\bvia\s+(oral|intramuscular|intravenosa|subcutânea|tópica|'
        r'oftálmica|auricular|nasal|retal|IM|IV|SC|EV)\b',
        re.I
    ),
]

_VIA_INVALIDAS = {'(s)', 's', 'a', 'o', 'os', 'as'}


def _extrair_via(texto: str) -> Optional[str]:
    """Extrai a via de administração com padrões específicos."""
    for pat in _VIA_PATTERNS:
        m = pat.search(texto)
        if m:
            # Pega o grupo de captura (grupo 1) ou o match completo
            val = (m.group(1) if m.lastindex else m.group(0)).strip().rstrip('.,')
            if val.lower() not in _VIA_INVALIDAS and len(val) > 1:
                return val[:80]
    return None


# Padrões específicos para dosagem
_DOSE_PATTERNS = [
    # "X mg/kg" ou "X mL/kg" — captura a linha inteira com o valor numérico
    re.compile(r'(\d[\d,\.]*\s*(?:mg|mL|mcg|UI|g)/\s*kg[^\n]{0,80})', re.I),
    re.compile(r'(\d[\d,\.]*\s*(?:mg|mL|mcg|UI|g)/\s*(?:animal|dose|comprimido)[^\n]{0,80})', re.I),
    # "Dose: X" na mesma linha (precisa ter número ou unidade)
    re.compile(r'Dose\s*(?:recomendada|usual|terapêutica)?\s*:\s*([\d][^\n]{2,150})', re.I),
    re.compile(r'Posologia\s*:\s*([\d][^\n]{2,150})', re.I),
]

_DOSE_INVALIDAS = {'indicada', 'conforme', 'prescrita', 'recomendada pelo veterinário'}


def _extrair_dose(texto: str) -> Optional[str]:
    """Extrai dosagem com padrões específicos — evita frases genéricas."""
    for pat in _DOSE_PATTERNS:
        m = pat.search(texto)
        if m:
            val = m.group(1).strip().rstrip('.,')
            if val.lower().strip() not in _DOSE_INVALIDAS and len(val) > 3:
                return val[:300]
    return None


def _extrair_descritivo(sobre_txt: str) -> Optional[str]:
    """Extrai o 'Descritivo do Produto' da seção Sobre."""
    m = re.search(
        r'Descritivo do Produto\s*\n([\s\S]{20,2000}?)(?:\n[A-Z]{3,}|\Z)',
        sobre_txt, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Scraping da lista de produtos
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
            url = BASE_URL + href if href.startswith("/") else href
            produtos.append({"id": pid, "nome": (nome or f"Produto #{pid}")[:100], "url": url})
            encontrados += 1

        log.info(f"     +{encontrados} (total: {len(produtos)})")
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

    log.info(f"Total na lista: {len(produtos)} produtos.")
    return produtos


# ---------------------------------------------------------------------------
# Scraping de detalhe — usa BS4 no HTML completo
# ---------------------------------------------------------------------------
def scrape_detalhe_produto(page, info: Dict) -> ProdutoVetsmart:
    pid       = info["id"]
    url       = info["url"]
    nome_base = info["nome"]

    page.goto(url, wait_until="networkidle", timeout=60000)
    aguardar_e_aceitar_cookies(page, timeout=4000)

    # Aguarda o conteúdo principal carregar
    try:
        page.wait_for_selector("h2.side-nav-title, section.container-content", timeout=10000)
    except Exception:
        pass

    time.sleep(1.0)

    html = page.content()
    return extrair_produto_do_html(html, pid, nome_base)


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
            mapa = {
                "classificacao":        p.classificacao,
                "principio_ativo":      p.principio_ativo,
                "via_administracao":    p.via_administracao,
                "dosagem_recomendada":  p.dosagem_recomendada,
                "frequencia":           p.frequencia,
                "duracao_tratamento":   p.duracao_tratamento,
                "observacoes":          p.observacoes,
                "bula":                 p.bula,
            }
            for campo, valor in mapa.items():
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
                if chave not in apres_existentes and ap.get("forma") not in ("N/A", "", None):
                    if not dry_run:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO apresentacao_medicamento (medicamento_id, forma, concentracao) VALUES (%s,%s,%s)",
                                (existente["id"], ap["forma"][:50], ap["concentracao"][:100])
                            )
                    apres_existentes.add(chave)
        else:
            log.info(f"  INSERIR: '{p.nome}'  [{p.classificacao or '—'}]")
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
                        (p.via_administracao or "")[:80] or None,
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
    global CREATED_BY_USER_ID

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run",        action="store_true")
    p.add_argument("--somente-listar", action="store_true")
    p.add_argument("--limite",         type=int, default=0)
    p.add_argument("--usar-cache",     action="store_true")
    p.add_argument("--created-by",     type=int, default=CREATED_BY_USER_ID)
    p.add_argument("--visible",        action="store_true")
    args = p.parse_args()
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
            raw = json.load(f)
        for d in raw:
            # Compatibilidade com caches antigos
            for campo_novo in ['fabricante', 'especies', 'indicacoes', 'interacoes', 'farmacologia']:
                d.setdefault(campo_novo, None)
            produtos.append(ProdutoVetsmart(**d))
        log.info(f"{len(produtos)} produtos carregados do cache.")
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

            # Aceita cookies na home
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
                    log.info(
                        f"    ✓ fab={prod.fabricante!r} "
                        f"class={prod.classificacao!r} "
                        f"pa={prod.principio_ativo!r} "
                        f"via={prod.via_administracao!r} "
                        f"dose={prod.dosagem_recomendada!r} "
                        f"apres={len(prod.apresentacoes)}"
                    )
                except Exception as exc:
                    log.warning(f"    ⚠ Erro: {exc}")
                    produtos.append(ProdutoVetsmart(vetsmart_id=info["id"], nome=info["nome"]))
                time.sleep(DELAY_PAGINAS)

            browser.close()

        # Salva cache
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump([{
                "vetsmart_id":         p.vetsmart_id,
                "nome":                p.nome,
                "fabricante":          p.fabricante,
                "classificacao":       p.classificacao,
                "especies":            p.especies,
                "principio_ativo":     p.principio_ativo,
                "via_administracao":   p.via_administracao,
                "dosagem_recomendada": p.dosagem_recomendada,
                "frequencia":          p.frequencia,
                "duracao_tratamento":  p.duracao_tratamento,
                "indicacoes":          p.indicacoes,
                "observacoes":         p.observacoes,
                "interacoes":          p.interacoes,
                "farmacologia":        p.farmacologia,
                "bula":                p.bula,
                "apresentacoes":       p.apresentacoes,
            } for p in produtos], f, ensure_ascii=False, indent=2)
        log.info(f"Cache salvo em '{CACHE_FILE}'.")

    if args.dry_run:
        log.info("⚠️  DRY-RUN — sem alterações no banco.")

    stats = cruzar_e_atualizar(conn, medicamentos_banco, produtos, dry_run=args.dry_run)

    if not args.dry_run:
        conn.commit()

    conn.close()

    print(f"""
{'='*65}
  RESULTADO
{'='*65}
  Banco (antes):     {len(medicamentos_banco)}
  Scrapeados:        {len(produtos)}
  Atualizados:       {stats['atualizados']}
  Inseridos:         {stats['inseridos']}
  Sem alteração:     {stats['sem_alteracao']}
  Dry-run:           {'SIM' if args.dry_run else 'NÃO'}
{'='*65}
""")


if __name__ == "__main__":
    main()
