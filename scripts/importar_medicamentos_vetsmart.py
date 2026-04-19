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
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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
    doses: List[Dict[str, Optional[str]]] = field(default_factory=list)


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


def _limpar_dose(texto: Optional[str]) -> Optional[str]:
    """Remove ruído típico do campo dosagem do VetSmart."""
    if not texto:
        return None
    # Remove o placeholder "INDICAÇÃO: 0 unidade" (vem do input vazio de cálculo)
    texto = re.sub(r'\s*INDICAÇÃO:\s*0\s*\w*\s*', ' ', texto, flags=re.IGNORECASE)
    # Remove "Doses" e "Dosagem indicada" duplicados no início
    texto = re.sub(r'^\s*(Doses|Dosagem indicada)\s+', '', texto, flags=re.IGNORECASE)
    # Remove hífen e prefixo "- Cães/Gatos" inicial
    texto = re.sub(r'^[-–]\s*', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto[:300] if texto else None


def _itemprops(soup, prop: str) -> List[str]:
    """Coleta todos os textos/contents de elementos com itemprop=prop."""
    valores = []
    for tag in soup.find_all(attrs={'itemprop': prop}):
        v = tag.get('content') or tag.get_text(' ', strip=True)
        v = re.sub(r'\s+', ' ', v).strip() if v else ''
        if v and not _eh_vazio(v):
            valores.append(v)
    return valores


def _itemprop(soup, prop: str) -> Optional[str]:
    vals = _itemprops(soup, prop)
    return vals[0] if vals else None


def extrair_produto_do_html(html: str, pid: int, nome_fallback: str) -> ProdutoVetsmart:
    """Extrai todos os dados do produto a partir do HTML completo da página.

    Estratégia: Schema.org metadata (itemprop) como fonte primária,
    com fallback para parsing das seções textuais.
    """
    soup = BeautifulSoup(html, 'html.parser')

    # ── Nome ──────────────────────────────────────────────────────────────
    nome_el = soup.find('h2', class_='side-nav-title')
    nome = nome_el.get_text(strip=True) if nome_el else nome_fallback
    nome = nome[:100] or nome_fallback

    # ── Schema.org: campos diretos ────────────────────────────────────────
    fabricante         = _itemprop(soup, 'manufacturer')
    classificacao      = _itemprop(soup, 'drugClass')
    via_administracao  = _itemprop(soup, 'administrationRoute')
    farmacologia_meta  = _itemprop(soup, 'clinicalPharmacology')
    description_meta   = _itemprop(soup, 'description')
    warning_meta       = _itemprop(soup, 'warning')

    # Princípio ativo — pode ter múltiplos (combinações)
    principios = _itemprops(soup, 'activeIngredient')
    principio_ativo = ' + '.join(principios) if principios else None

    # Fallback: fabricante via side-nav-subtitle (caso schema.org falhe)
    if not fabricante:
        fab_el = soup.find(class_='side-nav-subtitle')
        if fab_el:
            fab_raw = fab_el.get_text(separator=' ', strip=True)
            fabricante = re.sub(r'^POR\s+', '', fab_raw, flags=re.IGNORECASE).strip() or None

    # ── Espécies (não tem schema.org, parse da seção Sobre) ──────────────
    especies = None
    for p in soup.find_all('p'):
        b = p.find('b')
        if not b:
            continue
        b_txt = b.get_text(strip=True)
        p_txt = p.get_text(separator=' ', strip=True)
        if 'Espécie' in b_txt and not especies:
            especies = re.sub(
                r'Espécies?\s*:\s*', '', p_txt, flags=re.IGNORECASE
            ).strip() or None
        # Fallback de classificação se schema falhou
        if not classificacao and 'Classifica' in b_txt:
            classificacao = re.sub(
                r'Classifica.{1,4}o\s*:\s*', '', p_txt, flags=re.IGNORECASE
            ).strip() or None

    # ── Coleta todas as seções textuais ──────────────────────────────────
    secoes: Dict[str, Optional[str]] = {}
    secoes_uls: Dict[str, Any] = {}

    for sec in soup.find_all('section', class_='container-content'):
        title_el = sec.find(class_='title-content')
        if not title_el:
            continue
        titulo = title_el.get_text(strip=True)

        disabled = sec.find('p', class_='disabled')
        if disabled:
            conteudo = disabled.get_text(strip=True)
            secoes[titulo] = None if _eh_vazio(conteudo) else conteudo
            continue

        content_div = sec.find(class_='content-comercial-info')
        if not content_div:
            secoes[titulo] = None
            continue

        for el in content_div.find_all(class_='title-content'):
            el.decompose()

        ul = content_div.find('ul')
        if ul:
            secoes_uls[titulo] = ul

        conteudo = content_div.get_text(separator='\n', strip=True)
        secoes[titulo] = None if _eh_vazio(conteudo) else conteudo

    # ── Apresentações (Schema.org availableStrength + dosageForm) ────────
    # Cada <li> tem o nome da apresentação + <span itemprop="dosageForm"> + (volume opcional)
    apresentacoes = []
    ul_apres = secoes_uls.get('Apresentações e concentrações')
    if ul_apres:
        for li in ul_apres.find_all('li'):
            forma_el = li.find('span', attrs={'itemprop': 'dosageForm'}) or li.find('span')
            forma = forma_el.get_text(strip=True) if forma_el else ''

            # Texto do <li> sem o span
            li_clone = BeautifulSoup(str(li), 'html.parser').find('li')
            for s in li_clone.find_all('span'):
                s.decompose()
            txt_resto = li_clone.get_text(' ', strip=True)
            # Limpa traço inicial e formata: "- Cefalexina, (250mg)" → "Cefalexina (250mg)"
            txt_resto = re.sub(r'^[-–]\s*', '', txt_resto).strip()
            txt_resto = re.sub(r',\s*$', '', txt_resto).strip()
            # Remove vírgula órfã antes do parêntese: "Cefalexina, (250mg)" → "Cefalexina (250mg)"
            txt_resto = re.sub(r',\s*\(', ' (', txt_resto).strip()

            # Se a "concentração" é só o princípio ativo sem volume, zera
            # (quando há volume, vem entre parênteses)
            if txt_resto and principios and txt_resto.lower().strip() == (principios[0] if principios else '').lower().strip():
                txt_resto = ''
            # Mesma coisa se for o nome do produto sem volume
            if txt_resto and txt_resto.lower().strip() == nome.lower().strip():
                txt_resto = ''

            if forma or txt_resto:
                ap = {
                    'forma': (forma or 'N/A')[:50],
                    'concentracao': txt_resto[:100],
                }
                # Campos numéricos para cálculo de dose
                ap.update(_estruturar_apresentacao_campos(forma or '', txt_resto or '', nome))
                apresentacoes.append(ap)

    # ── Administração e doses (texto, com cleanup) ───────────────────────
    admin_txt = secoes.get('Administração e doses') or ''
    admin = _parsear_admin_doses(admin_txt)

    if not via_administracao:
        via_administracao = admin['via']

    dosagem_recomendada = _limpar_dose(admin['dose'])
    frequencia          = admin['frequencia']
    duracao_tratamento  = admin['duracao']

    # Doses estruturadas (tabela) — agora com dose_min/dose_max numéricos
    doses_estruturadas = _extrair_doses_estruturadas(
        dose_linhas=admin.get('dose_linhas') or [],
        via=via_administracao,
        frequencia_texto=frequencia,
        duracao_texto=duracao_tratamento,
        especies_str=especies,
    )

    # ── Indicações / Interações / Farmacologia ───────────────────────────
    indicacoes  = _limpar(secoes.get('Indicações e contraindicações'), 800)
    interacoes  = _limpar(secoes.get('Interações medicamentosas'), 500)

    # Farmacologia: prefere schema.org (mais limpo), fallback para seção
    farmacologia = _limpar(farmacologia_meta or secoes.get('Farmacologia'), 2000)

    # Observações: indicações + interações + warnings
    obs_partes = []
    if indicacoes:
        obs_partes.append(f"Indicações/Contraindicações:\n{indicacoes}")
    if interacoes:
        obs_partes.append(f"Interações medicamentosas:\n{interacoes}")
    if warning_meta:
        obs_partes.append(f"Advertências:\n{_limpar(warning_meta, 600)}")
    observacoes = '\n\n'.join(obs_partes) or None

    # Bula: farmacologia (rica) → description schema.org → descritivo da seção Sobre
    sobre_txt = secoes.get('Sobre') or ''
    bula = _limpar(
        farmacologia or description_meta or _extrair_descritivo(sobre_txt),
        5000
    )

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
        doses               = doses_estruturadas,
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
        'dose_linhas': coleta['dose'],  # linhas brutas para parser estruturado
        'frequencia': _juntar(coleta['frequencia'][:2], 100),
        'duracao':   _juntar(coleta['duracao'][:2], 100),
        'obs':       _juntar(coleta['obs'][:4], 400),
    }


# --- Parser estruturado de doses (com campos numéricos) ---------------------
_RE_DOSE_MGKG = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'(mg|mcg|ml|ui)\s*/\s*kg',
    re.IGNORECASE,
)
_RE_DOSE_ANIMAL = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'(mg|mcg|ml|pipeta|gotas?|comprimidos?|c[aá]psulas?)\s*/\s*animal',
    re.IGNORECASE,
)
_RE_FAIXA_ATE   = re.compile(r'at[eé]\s*(\d+(?:[,\.]\d+)?)\s*kg', re.IGNORECASE)
_RE_FAIXA_ACIMA = re.compile(r'acima\s+de\s+(\d+(?:[,\.]\d+)?)\s*kg', re.IGNORECASE)
_RE_FAIXA_ENTRE = re.compile(
    r'entre\s+(\d+(?:[,\.]\d+)?)\s*(?:e|-|–|a)\s*(\d+(?:[,\.]\d+)?)\s*kg',
    re.IGNORECASE,
)
# Ruído (word-boundary para "0 mg" NÃO casar com "50 mg")
_RE_RUIDO = re.compile(
    r'(?:^|\s)(?:indica[cç][aã]o:\s*0|0\s*(?:mg|ml)\b)(?:\s|$)',
    re.IGNORECASE,
)
_RE_ESPECIE_TXT = re.compile(
    r'\b(c[aã]es?\s*e\s*gatos?|c[aã]es?|gatos?|c[aã]o|gato|felinos?|caninos?)\b',
    re.IGNORECASE,
)


def _f(v: str) -> float:
    return float(str(v).replace(',', '.'))


def _norm_especie_code(txt: str) -> str:
    t = (txt or '').lower()
    ta = t.replace('ã', 'a').replace('ç', 'c')
    tem_cao = 'cao' in ta or 'canino' in ta or 'cães' in t
    tem_gato = 'gato' in ta or 'felino' in ta
    if tem_cao and tem_gato:
        return 'AMBOS'
    if tem_gato:
        return 'GATOS'
    if tem_cao:
        return 'CAES'
    return 'AMBOS'


def _intervalo_horas(freq_texto: str) -> Optional[int]:
    """Converte texto de frequência em intervalo em horas.
    Cobre: '12/12 horas', '12 em 12 horas', '2 vezes ao dia', 'a cada 8h'."""
    if not freq_texto:
        return None
    t = freq_texto.lower()
    if 'dose unica' in t.replace('ú', 'u') or 'dose única' in t:
        return None
    for pat in [
        r'(\d+)\s*/\s*\d+\s*horas?',
        r'(\d+)\s*em\s*\d+\s*horas?',          # "12 em 12 horas"
        r'a\s+cada\s+(\d+)\s*(?:h|horas?)\b',
        r'a\s+cada\s+(\d+)\s*dias?',           # vira *24
    ]:
        m = re.search(pat, t)
        if m:
            v = int(m.group(1))
            return v * 24 if 'dia' in pat else v
    m = re.search(r'(\d+)\s*(?:x|vezes?)\s*(?:ao|por)?\s*dia', t)
    if m:
        n = int(m.group(1))
        return 24 // n if n > 0 else None
    return None


def _duracao_dias(dur_texto: str):
    """Retorna (min, max) em dias. (None, None) se não detectou."""
    if not dur_texto:
        return (None, None)
    t = dur_texto.lower()
    m = re.search(r'(\d+)\s*(?:a|-|–|até)\s*(\d+)\s*dias?', t)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r'(?:até|ate)\s*(\d+)\s*dias?', t)
    if m:
        return (None, int(m.group(1)))
    m = re.search(r'(\d+)\s*dias?', t)
    if m:
        n = int(m.group(1))
        return (n, n)
    m = re.search(r'(\d+)\s*semanas?', t)
    if m:
        d = int(m.group(1)) * 7
        return (d, d)
    return (None, None)


def _extrair_doses_estruturadas(
    dose_linhas: List[str],
    via: Optional[str],
    frequencia_texto: Optional[str],
    duracao_texto: Optional[str],
    especies_str: Optional[str],
) -> List[Dict[str, Any]]:
    """Monta registros de dose estruturados a partir das linhas brutas da
    seção 'Administração e doses'.

    Formato de saída (compatível com DoseMedicamento extendido):
      {especie, faixa_peso (string legível), via, dose (string legível),
       frequencia, duracao, observacao,
       -- numéricos --
       especie_code (CAES|GATOS|AMBOS|OUTRO),
       peso_min_kg, peso_max_kg,
       dose_min, dose_max, dose_unidade (MG_KG|...),
       intervalo_horas, duracao_min_dias, duracao_max_dias,
       dose_raw_text, fonte, confianca}
    """
    if not dose_linhas:
        return []

    intervalo = _intervalo_horas(frequencia_texto or '')
    dur_min, dur_max = _duracao_dias(duracao_texto or '')
    esp_default = _norm_especie_code(especies_str or '')

    # Linhas — usa o split existente + quebra adicional por "." e ";"
    texto_join = '\n'.join(dose_linhas)
    linhas = [l.strip() for l in re.split(r'[\n.;]+', texto_join) if l.strip()]

    registros: List[Dict[str, Any]] = []
    esp_ctx = esp_default
    peso_min_ctx, peso_max_ctx = None, None
    peso_faixa_str = None

    for linha in linhas:
        if _RE_RUIDO.search(linha):
            continue

        code_linha = _norm_especie_code(linha)
        if code_linha != esp_default and code_linha != 'AMBOS':
            esp_ctx = code_linha

        # Contexto de faixa de peso (só com preposição)
        m = _RE_FAIXA_ENTRE.search(linha)
        if m:
            peso_min_ctx, peso_max_ctx = _f(m.group(1)), _f(m.group(2))
            peso_faixa_str = f"Entre {m.group(1)} e {m.group(2)} kg"
        elif _RE_FAIXA_ATE.search(linha):
            m = _RE_FAIXA_ATE.search(linha)
            peso_min_ctx, peso_max_ctx = 0.0, _f(m.group(1))
            peso_faixa_str = f"Até {m.group(1)} kg"
        elif _RE_FAIXA_ACIMA.search(linha):
            m = _RE_FAIXA_ACIMA.search(linha)
            peso_min_ctx, peso_max_ctx = _f(m.group(1)), None
            peso_faixa_str = f"Acima de {m.group(1)} kg"

        # mg/kg (com espaços tolerados)
        m = _RE_DOSE_MGKG.search(linha)
        if m:
            dose_min, dose_max = _f(m.group(1)), (_f(m.group(2)) if m.group(2) else _f(m.group(1)))
            un_map = {'mg': 'MG_KG', 'mcg': 'MCG_KG', 'ml': 'ML_KG', 'ui': 'UI_KG'}
            unidade = un_map.get(m.group(3).lower(), 'MG_KG')
            dose_str = (f"{m.group(1)} - {m.group(2)} {m.group(3)}/kg"
                        if m.group(2) else f"{m.group(1)} {m.group(3)}/kg")
            registros.append({
                'especie':       _especie_label(esp_ctx),
                'especie_code':  esp_ctx,
                'faixa_peso':    peso_faixa_str,
                'peso_min_kg':   peso_min_ctx,
                'peso_max_kg':   peso_max_ctx,
                'via':           via,
                'dose':          dose_str,
                'dose_min':      dose_min,
                'dose_max':      dose_max,
                'dose_unidade':  unidade,
                'frequencia':    frequencia_texto,
                'intervalo_horas': intervalo,
                'duracao':       duracao_texto,
                'duracao_min_dias': dur_min,
                'duracao_max_dias': dur_max,
                'observacao':    linha[:500] if len(linha) > 30 else None,
                'dose_raw_text': linha,
                'fonte':         'SCRAPER',
                'confianca':     'MEDIA',
            })
            continue

        # X/animal
        m = _RE_DOSE_ANIMAL.search(linha)
        if m:
            dose_min, dose_max = _f(m.group(1)), (_f(m.group(2)) if m.group(2) else _f(m.group(1)))
            un_txt = m.group(3).lower()
            un_map = {
                'mg': 'MG_ANIMAL', 'mcg': 'MCG_ANIMAL', 'ml': 'ML_ANIMAL',
                'pipeta': 'PIPETA_ANIMAL',
                'gota': 'GOTAS_ANIMAL', 'gotas': 'GOTAS_ANIMAL',
                'comprimido': 'COMPRIMIDOS_ANIMAL', 'comprimidos': 'COMPRIMIDOS_ANIMAL',
                'capsula': 'COMPRIMIDOS_ANIMAL', 'capsulas': 'COMPRIMIDOS_ANIMAL',
                'cápsula': 'COMPRIMIDOS_ANIMAL', 'cápsulas': 'COMPRIMIDOS_ANIMAL',
            }
            unidade = un_map.get(un_txt, 'MG_ANIMAL')
            dose_str = (f"{m.group(1)} - {m.group(2)} {un_txt}/animal"
                        if m.group(2) else f"{m.group(1)} {un_txt}/animal")
            registros.append({
                'especie':       _especie_label(esp_ctx),
                'especie_code':  esp_ctx,
                'faixa_peso':    peso_faixa_str,
                'peso_min_kg':   peso_min_ctx,
                'peso_max_kg':   peso_max_ctx,
                'via':           via,
                'dose':          dose_str,
                'dose_min':      dose_min,
                'dose_max':      dose_max,
                'dose_unidade':  unidade,
                'frequencia':    frequencia_texto,
                'intervalo_horas': intervalo,
                'duracao':       duracao_texto,
                'duracao_min_dias': dur_min,
                'duracao_max_dias': dur_max,
                'observacao':    linha[:500] if len(linha) > 30 else None,
                'dose_raw_text': linha,
                'fonte':         'SCRAPER',
                'confianca':     'MEDIA',
            })

    # Dedup por (especie_code, peso_min, peso_max, dose_min, dose_max, unidade)
    vistos = set()
    unicos = []
    for r in registros:
        chave = (r['especie_code'], r['peso_min_kg'], r['peso_max_kg'],
                 r['dose_min'], r['dose_max'], r['dose_unidade'])
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(r)
    return unicos


def _especie_label(code: str) -> str:
    return {'CAES': 'Cães', 'GATOS': 'Gatos', 'AMBOS': 'Cães e Gatos'}.get(code, code)


# --- Parser numérico de apresentação -----------------------------------------
_RE_CONC_MGML = re.compile(r'(\d+(?:[,\.]\d+)?)\s*(mg|mcg|ui)\s*/\s*ml\b', re.IGNORECASE)
_RE_CONC_MG   = re.compile(r'(\d+(?:[,\.]\d+)?)\s*(mg|mcg|g|ui|%)\b', re.IGNORECASE)
_RE_VOL_PAREN = re.compile(r'\((\d+(?:[,\.]\d+)?)\s*(ml|un|g|kg|l)\b', re.IGNORECASE)
_RE_NOME_NUM_FINAL = re.compile(r'\b(\d+(?:[,\.]\d+)?)\s*$')  # "Rilexine palatável 75"


def _estruturar_apresentacao_campos(forma: str, conc_raw: str, nome_produto: str) -> Dict[str, Any]:
    """Extrai valores numéricos da string de concentração/nome da apresentação.

    Retorna dict com: nome_variante, concentracao_valor, concentracao_unidade,
    volume_valor, volume_unidade.
    """
    out: Dict[str, Any] = {
        'nome_variante':        None,
        'concentracao_valor':   None,
        'concentracao_unidade': None,
        'volume_valor':         None,
        'volume_unidade':       None,
    }
    if not conc_raw:
        # Pode ter número no nome da variante — precisa consultar contexto mais amplo
        return out

    # 1) Volume entre parênteses — "(10 un)", "(50 ml)"
    m = _RE_VOL_PAREN.search(conc_raw)
    if m:
        out['volume_valor'] = _f(m.group(1))
        out['volume_unidade'] = m.group(2).lower()

    # 2) Concentração mg/ml (checa antes de mg só)
    m = _RE_CONC_MGML.search(conc_raw)
    if m:
        out['concentracao_valor'] = _f(m.group(1))
        out['concentracao_unidade'] = f"{m.group(2).lower()}/ml"
    else:
        m = _RE_CONC_MG.search(conc_raw)
        if m:
            out['concentracao_valor'] = _f(m.group(1))
            out['concentracao_unidade'] = m.group(2).lower()

    # 3) Nome variante — texto antes da concentração/volume
    nv = conc_raw
    nv = re.sub(r'\s*\([^)]*\)\s*$', '', nv).strip()
    nv = re.sub(r'\s*\d+(?:[,\.]\d+)?\s*(mg|mcg|g|ui|%|ml)[\s/]*\w*\s*$', '', nv, flags=re.IGNORECASE).strip()
    if nv and nv.lower() != (nome_produto or '').lower():
        out['nome_variante'] = nv[:100]
    else:
        out['nome_variante'] = nome_produto[:100] if nome_produto else None

    # 4) Fallback: se não achou concentração, tenta pegar número no final do nome_variante
    # Ex.: "Rilexine palatável 75" → 75 mg (heurística, assume mg)
    if out['concentracao_valor'] is None and out['nome_variante']:
        m = _RE_NOME_NUM_FINAL.search(out['nome_variante'])
        if m:
            out['concentracao_valor'] = _f(m.group(1))
            out['concentracao_unidade'] = 'mg'  # presume mg

    return out


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
def _coletar_links_da_pagina(page, ids_vistos: set) -> List[Dict[str, Any]]:
    """Extrai todos os links de produto novos da página atual."""
    novos = []
    links = page.query_selector_all("a[href*='/produto/']")
    for link in links:
        href = link.get_attribute("href") or ""
        m = re.search(r"/(?:cg|CG)/produto/(\d+)", href, re.IGNORECASE)
        if not m:
            continue
        pid = int(m.group(1))
        if pid in ids_vistos:
            continue
        ids_vistos.add(pid)
        nome_raw = (link.inner_text() or "").strip()
        nome = re.sub(r"^\s*(Avaliar|Ver|Detalhes)\s+", "", nome_raw, flags=re.IGNORECASE).strip()
        # O <a> do card contém nome + fabricante em linhas separadas
        # (ex: "ACQUA Limp\nBIOFARM"). Pegamos só a primeira linha não vazia
        # para bater com o nome limpo que o detalhe retorna (e evitar duplicatas).
        for linha in nome.splitlines():
            linha = linha.strip()
            if linha:
                nome = linha
                break
        url = BASE_URL + href if href.startswith("/") else href
        novos.append({"id": pid, "nome": (nome or f"Produto #{pid}")[:100], "url": url})
    return novos


def scrape_lista_produtos(page, pagina_max: int = 61) -> List[Dict[str, Any]]:
    """Coleta todos os produtos percorrendo as páginas numeradas do VetSmart.

    URL: https://vetsmart.com.br/cg/produto/lista/{N}  (N de 1 a pagina_max)
    Última página conhecida (2026-04): 61 (56 produtos; páginas 1–60 têm 100 cada).
    """
    produtos: List[Dict[str, Any]] = []
    ids_vistos: set = set()
    cookies_aceitos = False

    for n in range(1, pagina_max + 1):
        url_pag = f"{LIST_URL}/{n}"
        log.info(f"Abrindo lista página {n}/{pagina_max}: {url_pag}")
        try:
            page.goto(url_pag, wait_until="networkidle", timeout=60000)
        except Exception as e:
            log.warning(f"  ! erro ao abrir página {n}: {e}")
            continue

        if not cookies_aceitos:
            aguardar_e_aceitar_cookies(page)
            cookies_aceitos = True

        try:
            page.wait_for_selector("a[href*='/produto/']", timeout=10000)
        except Exception:
            log.warning(f"  ! página {n} sem produtos — parando")
            break

        novos = _coletar_links_da_pagina(page, ids_vistos)
        produtos.extend(novos)
        log.info(f"  +{len(novos)} (total acumulado: {len(produtos)})")

        if not novos:
            # Nenhum produto novo → fim da paginação
            log.info(f"  → página {n} não trouxe produtos novos, encerrando")
            break

        time.sleep(DELAY_PAGINAS)

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
    """Normaliza nome para comparação idempotente: remove acentos, baixa,
    colapsa espaços/quebras internas em um único espaço, strip."""
    import unicodedata
    s = unicodedata.normalize("NFKD", texto or "").encode("ASCII", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _inserir_doses(cur, medicamento_id: int, doses: List[Dict[str, Optional[str]]]):
    """Insere doses estruturadas (campos legados + numéricos). Só roda se o
    medicamento ainda não tem doses cadastradas."""
    if not doses:
        return
    cur.execute("SELECT COUNT(*) AS c FROM dose_medicamento WHERE medicamento_id = %s", (medicamento_id,))
    row = cur.fetchone()
    existentes = row["c"] if isinstance(row, dict) else row[0]
    if existentes:
        return  # não sobrescreve doses já cadastradas

    def _trunc(v, n):
        """Trunca para caber em varchar(n); retorna None se v vier vazio/None."""
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return s[:n]

    for d in doses:
        cur.execute("""
            INSERT INTO dose_medicamento
              (medicamento_id, especie, faixa_peso, via, dose, frequencia, duracao, observacao,
               especie_code, peso_min_kg, peso_max_kg,
               dose_min, dose_max, dose_unidade,
               intervalo_horas, duracao_min_dias, duracao_max_dias,
               dose_raw_text, fonte, confianca)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s)
        """, (
            medicamento_id,
            _trunc(d.get("especie"),       80),
            _trunc(d.get("faixa_peso"),    80),
            _trunc(d.get("via"),           80),
            _trunc(d.get("dose"),         200),
            _trunc(d.get("frequencia"),   120),
            _trunc(d.get("duracao"),      120),
            (d.get("observacao") or None),  # TEXT — sem limite
            _trunc(d.get("especie_code"),  10),
            d.get("peso_min_kg"),
            d.get("peso_max_kg"),
            d.get("dose_min"),
            d.get("dose_max"),
            _trunc(d.get("dose_unidade"),  30),
            d.get("intervalo_horas"),
            d.get("duracao_min_dias"),
            d.get("duracao_max_dias"),
            (d.get("dose_raw_text") or None),  # TEXT — sem limite
            _trunc(d.get("fonte") or 'SCRAPER',     15),
            _trunc(d.get("confianca") or 'MEDIA',   10),
        ))


def cruzar_e_atualizar(conn, medicamentos_banco, produtos, dry_run=False):
    stats = {"atualizados": 0, "inseridos": 0, "sem_alteracao": 0, "doses_inseridas": 0}
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
                                """INSERT INTO apresentacao_medicamento
                                     (medicamento_id, forma, concentracao,
                                      nome_variante, concentracao_valor, concentracao_unidade,
                                      volume_valor, volume_unidade)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (existente["id"], ap["forma"][:50], ap["concentracao"][:100],
                                 (ap.get("nome_variante") or None) and ap.get("nome_variante")[:100],
                                 ap.get("concentracao_valor"),
                                 (ap.get("concentracao_unidade") or None) and ap.get("concentracao_unidade")[:20],
                                 ap.get("volume_valor"),
                                 (ap.get("volume_unidade") or None) and ap.get("volume_unidade")[:20])
                            )
                    apres_existentes.add(chave)

            # Doses estruturadas (não sobrescreve existentes)
            if p.doses and not dry_run:
                with conn.cursor() as cur:
                    antes = stats["doses_inseridas"]
                    _inserir_doses(cur, existente["id"], p.doses)
                    # checa quantas foram inseridas realmente
                    cur.execute("SELECT COUNT(*) AS c FROM dose_medicamento WHERE medicamento_id = %s", (existente["id"],))
                    row = cur.fetchone()
                    total = row["c"] if isinstance(row, dict) else row[0]
                    # Se bateu com len(p.doses), contabiliza
                    if total == len(p.doses) and antes == stats["doses_inseridas"]:
                        stats["doses_inseridas"] += len(p.doses)
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
                                """INSERT INTO apresentacao_medicamento
                                     (medicamento_id, forma, concentracao,
                                      nome_variante, concentracao_valor, concentracao_unidade,
                                      volume_valor, volume_unidade)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (novo_id, ap["forma"][:50], ap["concentracao"][:100],
                                 (ap.get("nome_variante") or None),
                                 ap.get("concentracao_valor"),
                                 (ap.get("concentracao_unidade") or None),
                                 ap.get("volume_valor"),
                                 (ap.get("volume_unidade") or None))
                            )
                    _inserir_doses(cur, novo_id, p.doses)
                    if p.doses:
                        stats["doses_inseridas"] += len(p.doses)
            stats["inseridos"] += 1

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global CREATED_BY_USER_ID

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run",        action="store_true",
                   help="Não grava no banco; só simula a importação.")
    p.add_argument("--somente-listar", action="store_true",
                   help="Apenas lista medicamentos já existentes no banco e sai.")
    p.add_argument("--somente-cache",  action="store_true",
                   help="Faz scraping e atualiza o cache, mas não importa nada para o banco.")
    p.add_argument("--limite",         type=int, default=0,
                   help="Limita ao N primeiro produtos da lista (0 = sem limite).")
    p.add_argument("--usar-cache",     action="store_true",
                   help="Usa o cache existente em vez de raspar do site.")
    p.add_argument("--resume",         action="store_true",
                   help="Continua um scraping interrompido — pula produtos já no cache.")
    p.add_argument("--scrape-importar", action="store_true",
                   help="Modo Heroku/streaming: scrape + INSERT direto no banco (sem depender "
                        "do cache em disco). Skipa produtos cujo nome já existe no DB. "
                        "Commita a cada 25 produtos, então é seguro contra crash de dyno.")
    p.add_argument("--created-by",     type=int, default=CREATED_BY_USER_ID)
    p.add_argument("--visible",        action="store_true",
                   help="Roda o navegador em modo visível (debug).")
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

    # ─── Modo streaming (Heroku-friendly, sem cache em disco) ─────────────
    if args.scrape_importar:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Instale: pip install playwright && playwright install chromium")
            conn.close()
            sys.exit(1)

        nomes_existentes = {_norm(m["nome"]) for m in medicamentos_banco}
        log.info(f"Modo --scrape-importar: {len(nomes_existentes)} nomes já no DB serão pulados.")

        COMMIT_EVERY = 25
        contador = {"scrapeados": 0, "inseridos": 0, "pulados": 0, "falhas": 0}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.visible)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="pt-BR",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            log.info("Abrindo home para aceitar cookies…")
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            aguardar_e_aceitar_cookies(page, timeout=8000)
            time.sleep(1)

            lista = scrape_lista_produtos(page)
            if args.limite > 0:
                lista = lista[:args.limite]

            total = len(lista)
            for i, info in enumerate(lista, 1):
                nome_norm = _norm(info["nome"])
                if nome_norm in nomes_existentes:
                    contador["pulados"] += 1
                    if i % 50 == 0:
                        log.info(f"[{i}/{total}] (pulado: já no DB) {info['nome']}")
                    continue

                log.info(f"[{i}/{total}] {info['nome']}")
                try:
                    prod = scrape_detalhe_produto(page, info)
                    contador["scrapeados"] += 1
                    log.info(
                        f"    ✓ class={prod.classificacao!r} "
                        f"pa={prod.principio_ativo!r} "
                        f"apres={len(prod.apresentacoes)} "
                        f"doses={len(prod.doses)}"
                    )

                    # INSERT imediato no DB (mas sem commit ainda)
                    try:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO medicamento
                                  (nome, classificacao, principio_ativo, via_administracao,
                                   dosagem_recomendada, frequencia, duracao_tratamento,
                                   observacoes, bula, created_by)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                            """, (
                                prod.nome[:100],
                                (prod.classificacao or "")[:100] or None,
                                (prod.principio_ativo or "")[:200] or None,
                                (prod.via_administracao or "")[:80] or None,
                                prod.dosagem_recomendada,
                                (prod.frequencia or "")[:100] or None,
                                prod.duracao_tratamento, prod.observacoes,
                                prod.bula, CREATED_BY_USER_ID,
                            ))
                            novo_id = cur.fetchone()["id"]
                            for ap in prod.apresentacoes:
                                if ap.get("forma") not in ("N/A", "", None):
                                    cur.execute(
                                        """INSERT INTO apresentacao_medicamento
                                             (medicamento_id, forma, concentracao,
                                              nome_variante, concentracao_valor, concentracao_unidade,
                                              volume_valor, volume_unidade)
                                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                        (novo_id, ap["forma"][:50], ap["concentracao"][:100],
                                         (ap.get("nome_variante") or None) and ap.get("nome_variante")[:100],
                                         ap.get("concentracao_valor"),
                                         (ap.get("concentracao_unidade") or None) and ap.get("concentracao_unidade")[:20],
                                         ap.get("volume_valor"),
                                         (ap.get("volume_unidade") or None) and ap.get("volume_unidade")[:20])
                                    )
                            _inserir_doses(cur, novo_id, prod.doses)
                        nomes_existentes.add(nome_norm)
                        contador["inseridos"] += 1
                    except Exception as e_db:
                        log.error(f"    ✗ ERRO INSERT '{prod.nome}': {e_db}")
                        conn.rollback()
                        contador["falhas"] += 1
                except Exception as exc:
                    log.warning(f"    ⚠ Erro scrape: {exc}")
                    contador["falhas"] += 1

                time.sleep(DELAY_PAGINAS)

                # Commit batched a cada COMMIT_EVERY produtos
                if i % COMMIT_EVERY == 0:
                    conn.commit()
                    log.info(f"  ↳ commit ({contador['inseridos']} inseridos, {contador['pulados']} pulados, {contador['falhas']} falhas)")

            conn.commit()  # commit final
            browser.close()

        conn.close()
        print(f"""
{'='*65}
  RESULTADO (modo streaming)
{'='*65}
  Total na lista:    {total}
  Scrapeados:        {contador['scrapeados']}
  Inseridos no DB:   {contador['inseridos']}
  Pulados (já no DB):{contador['pulados']}
  Falhas:            {contador['falhas']}
{'='*65}
""")
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
            d.setdefault('doses', [])
            d.setdefault('apresentacoes', [])
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

            # Resumo: pula produtos já no cache (modo --resume).
            ja_scrapeados_ids: set = set()
            if args.resume and os.path.exists(CACHE_FILE):
                try:
                    with open(CACHE_FILE, encoding='utf-8') as fh:
                        cache_prev = json.load(fh)
                    for d in cache_prev:
                        d.setdefault('doses', [])
                        d.setdefault('apresentacoes', [])
                        for campo_novo in ['fabricante', 'especies', 'indicacoes', 'interacoes', 'farmacologia']:
                            d.setdefault(campo_novo, None)
                        produtos.append(ProdutoVetsmart(**d))
                        ja_scrapeados_ids.add(d.get('vetsmart_id'))
                    log.info(f"Resume: {len(produtos)} produtos já no cache. Continuando…")
                except Exception as e:
                    log.warning(f"Resume: cache inválido ({e}); recomeçando do zero.")
                    produtos.clear()
                    ja_scrapeados_ids.clear()

            def _persistir_cache():
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump([{
                        "vetsmart_id":         pp.vetsmart_id,
                        "nome":                pp.nome,
                        "fabricante":          pp.fabricante,
                        "classificacao":       pp.classificacao,
                        "especies":            pp.especies,
                        "principio_ativo":     pp.principio_ativo,
                        "via_administracao":   pp.via_administracao,
                        "dosagem_recomendada": pp.dosagem_recomendada,
                        "frequencia":          pp.frequencia,
                        "duracao_tratamento":  pp.duracao_tratamento,
                        "indicacoes":          pp.indicacoes,
                        "observacoes":         pp.observacoes,
                        "interacoes":          pp.interacoes,
                        "farmacologia":        pp.farmacologia,
                        "bula":                pp.bula,
                        "apresentacoes":       pp.apresentacoes,
                        "doses":               pp.doses,
                    } for pp in produtos], f, ensure_ascii=False, indent=2)

            CACHE_EVERY = 25
            total = len(lista)
            for i, info in enumerate(lista, 1):
                if info["id"] in ja_scrapeados_ids:
                    log.info(f"[{i}/{total}] (cache) {info['nome']}")
                    continue
                log.info(f"[{i}/{total}] {info['nome']}")
                try:
                    prod = scrape_detalhe_produto(page, info)
                    produtos.append(prod)
                    ja_scrapeados_ids.add(info["id"])
                    log.info(
                        f"    ✓ fab={prod.fabricante!r} "
                        f"class={prod.classificacao!r} "
                        f"pa={prod.principio_ativo!r} "
                        f"via={prod.via_administracao!r} "
                        f"dose={prod.dosagem_recomendada!r} "
                        f"apres={len(prod.apresentacoes)} "
                        f"doses={len(prod.doses)}"
                    )
                except Exception as exc:
                    log.warning(f"    ⚠ Erro: {exc}")
                    produtos.append(ProdutoVetsmart(vetsmart_id=info["id"], nome=info["nome"]))
                    ja_scrapeados_ids.add(info["id"])
                time.sleep(DELAY_PAGINAS)
                # Persistência incremental — preserva progresso se o script for interrompido.
                if i % CACHE_EVERY == 0:
                    try:
                        _persistir_cache()
                        log.info(f"  ↳ cache parcial salvo ({len(produtos)} produtos)")
                    except Exception as e:
                        log.warning(f"  ⚠ Falha ao salvar cache parcial: {e}")

            browser.close()

        # Salva cache final
        _persistir_cache()
        log.info(f"Cache salvo em '{CACHE_FILE}'.")

    if args.somente_cache:
        log.info(f"--somente-cache: {len(produtos)} produtos no cache; sem importar para o banco.")
        conn.close()
        return

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
