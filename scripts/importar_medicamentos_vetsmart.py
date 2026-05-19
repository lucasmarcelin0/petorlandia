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
from psycopg2.extras import Json, RealDictCursor

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
    conteudo_estruturado: Dict[str, Any] = field(default_factory=dict)
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


def _texto_multilinha_limpo(texto: Optional[str]) -> Optional[str]:
    if not texto:
        return None
    texto = str(texto).replace('\r\n', '\n').replace('\r', '\n')
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    texto = texto.strip()
    return texto or None


def _split_lista_textual(texto: Optional[str]) -> List[str]:
    bruto = _texto_multilinha_limpo(texto)
    if not bruto:
        return []
    candidato = re.sub(r'\s*[•·●▪◦]\s*', '\n', bruto)
    candidato = re.sub(r'\s*;\s*', '\n', candidato)
    candidato = re.sub(r'\.\s+(?=[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ])', '.\n', candidato)
    itens: List[str] = []
    vistos: set[str] = set()
    for linha in candidato.split('\n'):
        linha = re.sub(r'^\s*[-–—]\s*', '', linha).strip(' .;:-')
        if len(linha) < 3:
            continue
        chave = re.sub(r'\s+', ' ', linha).casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        itens.append(linha)
    return itens


def _montar_secao_padrao(itens: Optional[List[str]] = None, texto: Optional[str] = None, resumo: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        'itens': itens or [],
        'texto': _texto_multilinha_limpo(texto),
        'resumo': resumo or [],
    }


def _normalizar_rotulo_secao(rotulo: Optional[str]) -> Optional[str]:
    if not rotulo:
        return None
    alvo = re.sub(r'\s+', ' ', rotulo).strip(' :').casefold()
    if 'contraindica' in alvo:
        return 'contraindicacoes'
    if any(token in alvo for token in ['advert', 'precau', 'cuidado']):
        return 'advertencias'
    if any(token in alvo for token in ['efeitos adversos', 'reacoes adversas', 'reações adversas', 'efeito colateral']):
        return 'efeitos_adversos'
    if 'indica' in alvo:
        return 'indicacoes'
    return None


def _classificar_item_clinico(item: str, categoria_padrao: str = 'indicacoes') -> str:
    alvo = (item or '').casefold()
    if any(token in alvo for token in [
        'contraind', 'não usar', 'nao usar', 'não administrar', 'nao administrar',
        'hipersens', 'evitar o uso', 'não indicado', 'nao indicado',
    ]):
        return 'contraindicacoes'
    if any(token in alvo for token in [
        'efeito advers', 'reação advers', 'reacao advers', 'vômit', 'vomit',
        'diarre', 'letarg', 'ataxia', 'sedaç', 'sedac', 'saliva', 'anorex',
    ]):
        return 'efeitos_adversos'
    if any(token in alvo for token in [
        'usar com cautela', 'monitor', 'gestant', 'lactant', 'prenhe',
        'filhote', 'idoso', 'nefropat', 'hepatopat', 'desidrat', 'doença renal',
        'doenca renal', 'insuficiência renal', 'insuficiencia renal',
    ]):
        return 'advertencias'
    return categoria_padrao


def _coletar_blocos_por_subtitulo(content_div) -> List[Dict[str, Any]]:
    blocos: List[Dict[str, Any]] = []
    atual = {'titulo': None, 'partes': []}

    def flush():
        nonlocal atual
        if atual['titulo'] or atual['partes']:
            blocos.append(atual)
        atual = {'titulo': None, 'partes': []}

    for child in getattr(content_div, 'children', []):
        if getattr(child, 'name', None) is None:
            continue
        nome_tag = child.name.lower()
        if nome_tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            flush()
            atual['titulo'] = child.get_text(' ', strip=True)
            continue

        if nome_tag in {'p', 'li'}:
            bold = child.find(['b', 'strong'])
            if bold:
                rotulo = bold.get_text(' ', strip=True).strip(' :')
                categoria = _normalizar_rotulo_secao(rotulo)
                texto_total = child.get_text(' ', strip=True)
                texto_sem_rotulo = re.sub(
                    rf'^\s*{re.escape(bold.get_text(" ", strip=True))}\s*:?\s*',
                    '',
                    texto_total,
                    flags=re.IGNORECASE,
                ).strip()
                if categoria and (texto_sem_rotulo or not atual['partes']):
                    flush()
                    atual['titulo'] = rotulo
                    if texto_sem_rotulo:
                        atual['partes'].append(texto_sem_rotulo)
                    continue

        texto = child.get_text(' ', strip=True)
        if texto:
            atual['partes'].append(texto)

    flush()
    return [bloco for bloco in blocos if bloco.get('titulo') or bloco.get('partes')]


def _parsear_linhas_com_rotulo(texto: Optional[str]) -> Dict[str, List[str]]:
    saida: Dict[str, List[str]] = {
        'indicacoes': [],
        'contraindicacoes': [],
        'advertencias': [],
        'efeitos_adversos': [],
    }
    bruto = _texto_multilinha_limpo(texto)
    if not bruto:
        return saida
    padrao = re.compile(
        r'(Indica(?:ç|c)ões?|Contraindica(?:ç|c)ões?|Advert(?:ê|e)ncias?|Precau(?:ç|c)ões?|'
        r'Efeitos adversos?|Rea(?:ç|c)ões adversas?)\s*:\s*',
        re.IGNORECASE,
    )
    matches = list(padrao.finditer(bruto))
    if not matches:
        saida['indicacoes'].append(bruto)
        return saida

    for idx, match in enumerate(matches):
        categoria = _normalizar_rotulo_secao(match.group(1)) or 'indicacoes'
        inicio = match.end()
        fim = matches[idx + 1].start() if idx + 1 < len(matches) else len(bruto)
        trecho = bruto[inicio:fim].strip(' \n\r\t:;.-')
        if trecho:
            saida[categoria].append(trecho)
    return saida


def _redistribuir_itens_clinicos(secoes: Dict[str, List[str]]) -> Dict[str, List[str]]:
    reorganizado: Dict[str, List[str]] = {
        'indicacoes': [],
        'contraindicacoes': [],
        'advertencias': [],
        'efeitos_adversos': [],
    }
    for categoria, itens in secoes.items():
        for item in itens:
            if categoria != 'indicacoes':
                destino = categoria
            else:
                destino = _classificar_item_clinico(item, categoria)
            reorganizado[destino].append(item)
    return reorganizado


def _inferir_grau_interacao(texto: str) -> str:
    alvo = texto.casefold()
    if any(token in alvo for token in ['contraindicado', 'evitar associação', 'evitar associacao', 'não associar', 'nao associar', 'grave', 'severa']):
        return 'Alta'
    if any(token in alvo for token in ['cautela', 'monitor', 'moderad', 'ajustar dose', 'ajuste de dose']):
        return 'Moderada'
    if any(token in alvo for token in ['leve', 'discreta', 'pouco relevante']):
        return 'Baixa'
    return 'Atenção'


def _inferir_conduta_interacao(texto: str) -> str:
    alvo = texto.casefold()
    if any(token in alvo for token in ['contraindicado', 'não associar', 'nao associar', 'evitar associação', 'evitar associacao']):
        return 'Evitar associação'
    if 'ajust' in alvo:
        return 'Ajustar dose'
    if any(token in alvo for token in ['monitor', 'acompanhar', 'vigiar']):
        return 'Monitorar de perto'
    if 'cautela' in alvo:
        return 'Usar com cautela'
    return 'Avaliar clinicamente'


def _parsear_item_interacao(texto: str) -> Dict[str, str]:
    agente = texto
    match = re.match(r"^(.*?)(?:\s*[-:]\s*|\s+)(aumenta|reduz|potencializa|pode|deve|evitar|contraindicado|usar|monitorar)", texto, re.IGNORECASE)
    if match:
        agente = match.group(1).strip(" -:")
    elif ':' in texto:
        agente = texto.split(':', 1)[0].strip(" -:")
    elif ' com ' in texto.casefold():
        agente = texto.split(' com ', 1)[0].strip(" -:")
    return {
        'agente': agente[:120],
        'grau': _inferir_grau_interacao(texto),
        'conduta': _inferir_conduta_interacao(texto),
        'descricao': texto,
    }


def _eh_item_interacao_ruido(texto: str) -> bool:
    alvo = (texto or '').casefold().strip()
    if not alvo:
        return True
    if 'o aplicativo vetsmart contém informações' in alvo:
        return True
    prefixos = [
        'tipo de interação',
        'tipo de interacao',
        'grau de interação',
        'grau de interacao',
        'efeito clínico',
        'efeito clinico',
        'mecanismo de ação',
        'mecanismo de acao',
        'conduta',
    ]
    return any(alvo.startswith(prefixo) for prefixo in prefixos)


def _parsear_interaction_wraps(content_div) -> List[Dict[str, str]]:
    itens: List[Dict[str, str]] = []
    for bloco in content_div.find_all('div', class_='interaction-wrap'):
        agente_tag = bloco.find(['h1', 'h2', 'h3', 'h4'])
        agente = _texto_multilinha_limpo(agente_tag.get_text(' ', strip=True) if agente_tag else None)
        if not agente or 'aviso legal' in agente.casefold():
            continue

        campos: Dict[str, str] = {}
        for p in bloco.find_all('p'):
            texto = _texto_multilinha_limpo(p.get_text(' ', strip=True))
            if not texto:
                continue
            bold = p.find(['b', 'strong'])
            if bold:
                rotulo = _texto_multilinha_limpo(bold.get_text(' ', strip=True))
                valor = re.sub(
                    rf'^\s*{re.escape(bold.get_text(" ", strip=True))}\s*[-:]\s*',
                    '',
                    texto,
                    flags=re.IGNORECASE,
                ).strip()
                if rotulo and valor:
                    campos[rotulo.casefold()] = valor

        descricao_partes = []
        if campos.get('tipo de interação') or campos.get('tipo de interacao'):
            descricao_partes.append(f"Tipo: {campos.get('tipo de interação') or campos.get('tipo de interacao')}")
        if campos.get('efeito clínico') or campos.get('efeito clinico'):
            descricao_partes.append(f"Efeito clínico: {campos.get('efeito clínico') or campos.get('efeito clinico')}")
        if campos.get('mecanismo de ação') or campos.get('mecanismo de acao'):
            descricao_partes.append(f"Mecanismo: {campos.get('mecanismo de ação') or campos.get('mecanismo de acao')}")

        descricao = '; '.join(descricao_partes) or agente
        grau = campos.get('grau de interação') or campos.get('grau de interacao') or _inferir_grau_interacao(descricao)
        conduta = campos.get('conduta') or _inferir_conduta_interacao(descricao)

        itens.append({
            'agente': agente[:120],
            'grau': grau,
            'conduta': conduta,
            'descricao': descricao,
        })
    return itens


def _consolidar_itens_interacao(itens_brutos: List[str]) -> List[str]:
    itens_limpos = [_texto_multilinha_limpo(item) for item in itens_brutos]
    itens_limpos = [item for item in itens_limpos if item and not _eh_item_interacao_ruido(item)]
    if not itens_limpos:
        return []

    consolidados: List[str] = []
    pendentes: Dict[str, str] = {}
    for item in itens_limpos:
        if ':' in item:
            agente, resto = item.split(':', 1)
            agente = agente.strip(" -:")
            resto = resto.strip()
            if agente and resto:
                pendentes[agente.casefold()] = agente
                consolidados.append(f"{agente}: {resto}")
                continue
        if re.match(r'^[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][\wÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇçãõéíóúêôâîûü\- ]{2,80}$', item):
            pendentes[item.casefold()] = item
            continue
        if consolidados and len(item) > 12:
            consolidados[-1] = f"{consolidados[-1]} {item}".strip()
        else:
            consolidados.append(item)
    return consolidados


def _extrair_secao_indicacoes_contraindicacoes(content_div) -> Dict[str, Any]:
    bruto = _texto_multilinha_limpo(content_div.get_text('\n', strip=True) if content_div else None)
    secoes: Dict[str, List[str]] = {
        'indicacoes': [],
        'contraindicacoes': [],
        'advertencias': [],
        'efeitos_adversos': [],
    }
    textos_brutos: Dict[str, List[str]] = {chave: [] for chave in secoes}

    for bloco in _coletar_blocos_por_subtitulo(content_div):
        categoria = _normalizar_rotulo_secao(bloco.get('titulo')) or 'indicacoes'
        bloco_texto = _texto_multilinha_limpo('\n'.join(bloco.get('partes') or []))
        if not bloco_texto:
            continue
        partes_rotuladas = _parsear_linhas_com_rotulo(bloco_texto)
        sem_rotulos_explicitos = (
            partes_rotuladas['indicacoes'] == [bloco_texto]
            and not partes_rotuladas['contraindicacoes']
            and not partes_rotuladas['advertencias']
            and not partes_rotuladas['efeitos_adversos']
        )
        if sem_rotulos_explicitos and categoria != 'indicacoes':
            partes_rotuladas = {
                'indicacoes': [],
                'contraindicacoes': [],
                'advertencias': [],
                'efeitos_adversos': [],
            }
            partes_rotuladas[categoria] = [bloco_texto]
        for chave, partes in partes_rotuladas.items():
            if not partes:
                continue
            textos_brutos[chave].extend(partes)
            for parte in partes:
                secoes[chave].extend(_split_lista_textual(parte))
        if not any(partes_rotuladas.values()):
            textos_brutos[categoria].append(bloco_texto)
            secoes[categoria].extend(_split_lista_textual(bloco_texto))

    if not any(secoes.values()) and bruto:
        partes_rotuladas = _parsear_linhas_com_rotulo(bruto)
        for chave, partes in partes_rotuladas.items():
            textos_brutos[chave].extend(partes)
            for parte in partes:
                secoes[chave].extend(_split_lista_textual(parte))

    secoes = _redistribuir_itens_clinicos(secoes)

    return {
        'indicacoes': _montar_secao_padrao(secoes['indicacoes'], '\n\n'.join(textos_brutos['indicacoes']) or None),
        'contraindicacoes': _montar_secao_padrao(
            secoes['contraindicacoes'],
            '\n\n'.join(textos_brutos['contraindicacoes']) or None,
            resumo=secoes['contraindicacoes'][:3],
        ),
        'advertencias': _montar_secao_padrao(secoes['advertencias'], '\n\n'.join(textos_brutos['advertencias']) or None),
        'efeitos_adversos': _montar_secao_padrao(secoes['efeitos_adversos'], '\n\n'.join(textos_brutos['efeitos_adversos']) or None),
        'texto_bruto': bruto,
    }


def _extrair_secao_interacoes(content_div) -> Dict[str, Any]:
    bruto = _texto_multilinha_limpo(content_div.get_text('\n', strip=True) if content_div else None)
    if not bruto or _eh_vazio(bruto):
        return {'itens': [], 'texto': None, 'texto_bruto': bruto}

    itens_wrap = _parsear_interaction_wraps(content_div)
    if itens_wrap:
        return {
            'itens': itens_wrap,
            'texto': bruto,
            'texto_bruto': bruto,
        }

    itens_brutos: List[str] = []
    for seletor in ['li', 'p', 'div']:
        for tag in content_div.find_all(seletor):
            texto = _texto_multilinha_limpo(tag.get_text(' ', strip=True))
            if not texto or _eh_vazio(texto):
                continue
            itens_brutos.append(texto)
        if itens_brutos:
            break

    if not itens_brutos:
        itens_brutos = _split_lista_textual(bruto)

    vistos: set[str] = set()
    itens: List[Dict[str, str]] = []
    for texto in _consolidar_itens_interacao(itens_brutos):
        for item in _split_lista_textual(texto) or [texto]:
            chave = item.casefold()
            if chave in vistos:
                continue
            vistos.add(chave)
            itens.append(_parsear_item_interacao(item))

    return {
        'itens': itens,
        'texto': bruto,
        'texto_bruto': bruto,
    }


def _extrair_secao_farmacologia(content_div) -> Dict[str, Any]:
    bruto = _texto_multilinha_limpo(content_div.get_text('\n', strip=True) if content_div else None)
    return {
        'texto': bruto,
        'texto_bruto': bruto,
    }


def _limpar_prefixos_apresentacao(texto: str, nome: Optional[str], principios: List[str]) -> str:
    saida = (texto or '').strip()
    candidatos = [nome or ''] + list(principios or [])
    for candidato in candidatos:
        candidato = candidato.strip()
        if not candidato:
            continue
        padrao = rf'^\s*{re.escape(candidato)}\s*[-,|:]?\s*'
        nova = re.sub(padrao, '', saida, flags=re.IGNORECASE).strip()
        if nova and re.search(r'\d', nova):
            saida = nova
    return saida


def _extrair_apresentacoes_estruturadas(ul_apres, principios: List[str], nome: str) -> List[Dict[str, Any]]:
    apresentacoes: List[Dict[str, Any]] = []
    if not ul_apres:
        return apresentacoes

    for li in ul_apres.find_all('li'):
        li_txt = li.get_text(' ', strip=True)
        tem_dosage_form = bool(li.find('span', attrs={'itemprop': 'dosageForm'}))
        eh_produto_relacionado = (
            not tem_dosage_form
            and re.search(r'empresa\s*:', li_txt, re.IGNORECASE)
            and re.search(r'princ[ií]pio', li_txt, re.IGNORECASE)
        )
        if eh_produto_relacionado:
            continue

        forma_el = li.find('span', attrs={'itemprop': 'dosageForm'}) or li.find('span')
        forma = forma_el.get_text(strip=True) if forma_el else ''

        li_clone = BeautifulSoup(str(li), 'html.parser').find('li')
        for s in li_clone.find_all('span'):
            s.decompose()
        txt_resto = li_clone.get_text(' ', strip=True)
        txt_resto = re.sub(r'^[-–]\s*', '', txt_resto).strip()
        txt_resto = re.sub(r',\s*$', '', txt_resto).strip()
        txt_resto = re.sub(r',\s*\(', ' (', txt_resto).strip()
        txt_resto = _limpar_prefixos_apresentacao(txt_resto, nome, principios)

        def _sem_numero(s: str) -> bool:
            return bool(s) and not re.search(r'\d', s)

        if _sem_numero(txt_resto):
            alvo = txt_resto.lower().strip()
            pa = (principios[0] if principios else '').lower().strip()
            nom = (nome or '').lower().strip()
            if (
                (pa and (alvo == pa or pa in alvo or alvo in pa))
                or (nom and (alvo == nom or alvo in nom or nom in alvo))
            ):
                txt_resto = ''
            elif len(alvo.split()) >= 2:
                txt_resto = ''

        if forma or txt_resto:
            ap = {
                'forma': (forma or 'N/A')[:50],
                'concentracao': txt_resto[:100],
            }
            ap.update(_estruturar_apresentacao_campos(forma or '', txt_resto or '', nome))
            apresentacoes.append(ap)
    return _deduplicar_apresentacoes_canonicas(apresentacoes)


def _montar_conteudo_estruturado_v2(
    secoes_clinicas: Dict[str, Any],
    interacoes_struct: Dict[str, Any],
    advertencias_extras: Optional[str] = None,
    raw_sections: Optional[Dict[str, Any]] = None,
    raw_sections_html: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    advertencias = dict(secoes_clinicas.get('advertencias') or _montar_secao_padrao())
    if advertencias_extras:
        extras = _split_lista_textual(advertencias_extras)
        advertencias['itens'] = list(dict.fromkeys((advertencias.get('itens') or []) + extras))
        advertencias['texto'] = _texto_multilinha_limpo('\n\n'.join(filter(None, [advertencias.get('texto'), advertencias_extras])))

    return {
        'indicacoes': secoes_clinicas.get('indicacoes') or _montar_secao_padrao(),
        'contraindicacoes': secoes_clinicas.get('contraindicacoes') or _montar_secao_padrao(),
        'advertencias': advertencias,
        'efeitos_adversos': secoes_clinicas.get('efeitos_adversos') or _montar_secao_padrao(),
        'interacoes': {
            'itens': interacoes_struct.get('itens') or [],
            'texto': interacoes_struct.get('texto'),
        },
        'raw_sections': raw_sections or {},
        'raw_sections_html': raw_sections_html or {},
        'metadata': {
            'parser_version': 'v3',
            'fonte': 'vetsmart',
            'secao_indicacoes_bruta': secoes_clinicas.get('texto_bruto'),
            'secao_interacoes_bruta': interacoes_struct.get('texto_bruto'),
        },
    }


_SECOES_CLINICAS_PRODUTO = [
    'Sobre',
    'ApresentaÃ§Ãµes e concentraÃ§Ãµes',
    'IndicaÃ§Ãµes e contraindicaÃ§Ãµes',
    'AdministraÃ§Ã£o e doses',
    'Dosagens',
    'Via',
    'FrequÃªncia',
    'DuraÃ§Ã£o do Tratamento',
    'ComposiÃ§Ã£o',
    'ObservaÃ§Ãµes',
    'Armazenamento',
    'InformaÃ§Ãµes ao Cliente',
    'InteraÃ§Ãµes medicamentosas',
    'Farmacologia',
]


def _produto_vetsmart_snapshot(prod: ProdutoVetsmart) -> Dict[str, Any]:
    """Preserva a camada de produto industrializado dentro do PA canonico."""
    conteudo = prod.conteudo_estruturado or {}
    raw_sections = conteudo.get('raw_sections') if isinstance(conteudo, dict) else {}
    raw_html = conteudo.get('raw_sections_html') if isinstance(conteudo, dict) else {}
    if not isinstance(raw_sections, dict):
        raw_sections = {}
    if not isinstance(raw_html, dict):
        raw_html = {}

    def _por_nome_secao(raw: Dict[str, Any], nome: str):
        if nome in raw:
            return raw.get(nome)
        nome_norm = _norm(nome)
        for chave, valor in raw.items():
            if _norm(chave) == nome_norm:
                return valor
        return None

    secoes = {}
    for nome in _SECOES_CLINICAS_PRODUTO:
        texto = _por_nome_secao(raw_sections, nome)
        html = _por_nome_secao(raw_html, nome)
        if texto or html:
            secoes[nome] = {
                'texto': _texto_multilinha_limpo(texto),
                'html': html,
            }
    for nome in [
        'Apresenta\u00e7\u00f5es e concentra\u00e7\u00f5es',
        'Indica\u00e7\u00f5es e contraindica\u00e7\u00f5es',
        'Administra\u00e7\u00e3o e doses',
        'Frequ\u00eancia',
        'Dura\u00e7\u00e3o do Tratamento',
        'Composi\u00e7\u00e3o',
        'Observa\u00e7\u00f5es',
        'Informa\u00e7\u00f5es ao Cliente',
        'Intera\u00e7\u00f5es medicamentosas',
    ]:
        if nome in secoes:
            continue
        texto = raw_sections.get(nome)
        html = raw_html.get(nome)
        if texto or html:
            secoes[nome] = {
                'texto': _texto_multilinha_limpo(texto),
                'html': html,
            }

    is_principio_ativo = not (prod.fabricante or '').strip()
    return {
        'vetsmart_produto_id': prod.vetsmart_id,
        'nome': prod.nome,
        'tipo': 'principio_ativo' if is_principio_ativo else 'produto',
        'fabricante': prod.fabricante,
        'classificacao': prod.classificacao,
        'principio_ativo': prod.principio_ativo,
        'especies': prod.especies,
        'via_administracao': prod.via_administracao,
        'dosagem_recomendada': prod.dosagem_recomendada,
        'frequencia': prod.frequencia,
        'duracao_tratamento': prod.duracao_tratamento,
        'observacoes': prod.observacoes,
        'apresentacoes': prod.apresentacoes or [],
        'doses': prod.doses or [],
        'secoes': secoes,
        'fonte': f"{BASE_URL}/cg/produto/{prod.vetsmart_id}",
    }


def _mesclar_produto_vetsmart(conteudo_atual: Optional[Dict[str, Any]], prod: ProdutoVetsmart) -> Dict[str, Any]:
    atual = dict(conteudo_atual or {})
    produtos = atual.get('produtos_vetsmart')
    if not isinstance(produtos, list):
        produtos = []

    snapshot = _produto_vetsmart_snapshot(prod)
    pid = snapshot['vetsmart_produto_id']
    produtos = [p for p in produtos if not (isinstance(p, dict) and p.get('vetsmart_produto_id') == pid)]
    produtos.append(snapshot)
    produtos.sort(key=lambda p: (0 if p.get('tipo') == 'principio_ativo' else 1, (p.get('nome') or '').lower()))
    atual['produtos_vetsmart'] = produtos
    metadata = atual.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}
    metadata['tem_produtos_vetsmart'] = True
    metadata['produtos_vetsmart_count'] = len(produtos)
    atual['metadata'] = metadata
    return atual


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

    # Fallback: tenta extrair princípio ativo de tags <p><b>Princípio Ativo:</b></p>
    if not principio_ativo:
        for p in soup.find_all('p'):
            b = p.find('b')
            if not b:
                continue
            b_txt = b.get_text(strip=True)
            if re.search(r'princ[ií]pio\s+ativ', b_txt, re.IGNORECASE):
                p_txt = p.get_text(separator=' ', strip=True)
                val = re.sub(r'princ[ií]pio\s+ativo\s*:\s*', '', p_txt, flags=re.IGNORECASE).strip()
                if val and not _eh_vazio(val):
                    principio_ativo = val[:200]
                break

    # Fallback: fabricante via side-nav-subtitle (caso schema.org falhe)
    if not fabricante:
        fab_el = soup.find(class_='side-nav-subtitle')
        if fab_el:
            fab_raw = fab_el.get_text(separator=' ', strip=True)
            fabricante = re.sub(r'^POR\s+', '', fab_raw, flags=re.IGNORECASE).strip() or None

    # "Princípio Ativo" não é um fabricante real — é o rótulo que a VetSmart
    # usa em páginas de PA genérico. Nesses casos, queremos fabricante NULL
    # (a "apresentação" da página de PA tb é filtrada em outro trecho).
    if fabricante and re.fullmatch(r'princ[ií]pio\s+ativo', fabricante.strip(), flags=re.IGNORECASE):
        fabricante = None

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
    secoes_content: Dict[str, Any] = {}

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
        secoes_content[titulo] = content_div

        for el in content_div.find_all(class_='title-content'):
            el.decompose()

        ul = content_div.find('ul')
        if ul:
            secoes_uls[titulo] = ul

        conteudo = content_div.get_text(separator='\n', strip=True)
        secoes[titulo] = None if _eh_vazio(conteudo) else conteudo

    # ── Apresentações (Schema.org availableStrength + dosageForm) ────────
    # Cada <li> tem o nome da apresentação + <span itemprop="dosageForm"> + (volume opcional)
    ul_apres = secoes_uls.get('Apresentações e concentrações')
    apresentacoes = _extrair_apresentacoes_estruturadas(ul_apres, principios, nome)

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
        indicacoes_texto=secoes.get('IndicaÃ§Ãµes e contraindicaÃ§Ãµes') or '',
        classificacao=classificacao,
    )
    doses_estruturadas = _pos_processar_doses_por_apresentacao(
        doses_estruturadas,
        apresentacoes,
    )

    # ── Indicações / Interações / Farmacologia ───────────────────────────
    indicacoes_struct = _extrair_secao_indicacoes_contraindicacoes(secoes_content.get('Indicações e contraindicações'))
    interacoes_struct = _extrair_secao_interacoes(secoes_content.get('Interações medicamentosas'))
    indicacoes = _limpar(
        indicacoes_struct['indicacoes'].get('texto')
        or secoes.get('Indicações e contraindicações'),
        1500,
    )
    interacoes = _limpar(interacoes_struct.get('texto') or secoes.get('Interações medicamentosas'), 1500)

    # Farmacologia: prefere schema.org (mais limpo), fallback para seção
    farmacologia_struct = _extrair_secao_farmacologia(secoes_content.get('Farmacologia'))
    farmacologia = _limpar(farmacologia_meta or farmacologia_struct.get('texto') or secoes.get('Farmacologia'), 5000)

    # Observações: indicações + interações + warnings
    obs_partes = []
    if indicacoes_struct['texto_bruto']:
        obs_partes.append(f"Indicações/Contraindicações:\n{indicacoes_struct['texto_bruto']}")
    if interacoes:
        obs_partes.append(f"Interações medicamentosas:\n{interacoes}")
    if warning_meta:
        obs_partes.append(f"Advertências:\n{_limpar(warning_meta, 600)}")
    observacoes = '\n\n'.join(obs_partes) or None

    # Todas as seções brutas da página para exibir com atribuição ao Vetsmart
    _SECOES_ORDEM = [
        'Sobre',
        'Apresentações e concentrações',
        'Indicações e contraindicações',
        'Administração e doses',
        'Dosagens',
        'Via',
        'Frequência',
        'Duração do Tratamento',
        'Composição',
        'Observações',
        'Armazenamento',
        'Informações ao Cliente',
        'Interações medicamentosas',
        'Farmacologia',
        'Estudos',
        'Videos',
        'Avaliações',
        'Distribuidores',
        'Ref. bibliográficas',
    ]
    raw_sections: Dict[str, Optional[str]] = {}
    raw_sections_html: Dict[str, str] = {}
    for sec_nome in _SECOES_ORDEM:
        valor = secoes.get(sec_nome)
        if valor and not _eh_vazio(valor):
            raw_sections[sec_nome] = _texto_multilinha_limpo(valor)
        html_secao = _html_secao_limpo(secoes_content.get(sec_nome))
        if html_secao:
            raw_sections_html[sec_nome] = html_secao

    conteudo_estruturado = _montar_conteudo_estruturado_v2(
        indicacoes_struct,
        interacoes_struct,
        advertencias_extras=_limpar(warning_meta, 1200),
        raw_sections=raw_sections,
        raw_sections_html=raw_sections_html,
    )

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
        conteudo_estruturado = conteudo_estruturado,
        apresentacoes       = apresentacoes,
        doses               = doses_estruturadas,
    )


def _html_secao_limpo(content_div) -> Optional[str]:
    if not content_div:
        return None
    clone = BeautifulSoup(str(content_div), 'html.parser')
    raiz = clone.find(class_='content-comercial-info') or clone
    for el in raiz.find_all(['script', 'style', 'noscript']):
        el.decompose()
    for el in raiz.find_all(class_='title-content'):
        el.decompose()
    html = raiz.decode_contents().strip()
    return html or None


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
        'dosagem para felinos',
        'dosagem para caninos',
        'dosagem para felino',
        'dosagem para canino',
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
        if ln in RUIDO:
            continue
        # Prefixos de espécie como "Dosagem para Cães 1 comprimido / 10 kg":
        # em vez de descartar a linha inteira, passamos a linha COMPLETA adiante
        # para que _extrair_doses_estruturadas possa detectar a espécie via
        # _norm_especie_code E extrair o valor de dose via regex.
        # Somente descartamos se a linha for APENAS o prefixo (sem conteúdo).
        prefixo_matched = None
        for pr in PREFIXOS_RUIDO:
            if ln.startswith(pr):
                prefixo_matched = pr
                break
        if prefixo_matched:
            resto_norm = ln[len(prefixo_matched):].strip().lstrip('-–: ')
            if not resto_norm:
                continue  # linha era só o prefixo de espécie, descarta
            # Tem conteúdo após o prefixo: mantém a linha completa
            # (o parser de doses já ignora texto de espécie e extrai o valor)
        if atual and atual in coleta:
            coleta[atual].append(linha)

    if not coleta['dose']:
        for linha in texto.split('\n'):
            linha = linha.strip()
            if not linha:
                continue
            if any(regex.search(linha) for regex in [
                _RE_DOSE_MGKG,
                _RE_DOSE_ANIMAL,
                _RE_DOSE_CP_POR_PESO,
                _RE_DOSE_CP_PLANO,
                _RE_DOSE_PIPETA_POR_PESO,
                _RE_DOSE_LOCAL_GOTAS,
            ]):
                coleta['dose'].append(linha)
                continue
            if not coleta['frequencia'] and _intervalo_horas(linha):
                coleta['frequencia'].append(linha)

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
# Formato "1 comprimido / 10 kg" → dose normalizada por peso (COMPRIMIDOS_KG)
# Ex: "1 comprimido / 10 kg", "0,5 cp / 5 kg", "1 cápsula por 10 kg"
_RE_DOSE_CP_POR_PESO = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'(comprimidos?|c[aá]psulas?|cp)\s*(?:/|por)\s*(\d+(?:[,\.]\d+)?)\s*kg',
    re.IGNORECASE,
)
# Formato "0.5 comprimido / dia" ou "1 comprimido ao dia" → dose plana diária
# Ex: "0,5 comprimido / dia", "1 cp ao dia", "2 comprimidos por dia"
_RE_DOSE_CP_PLANO = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'(comprimidos?|c[aá]psulas?|cp)\s*(?:/|por|ao)\s*dia',
    re.IGNORECASE,
)
# Formato "1 pipeta / 10 kg" → PIPETA_KG
_RE_DOSE_PIPETA_POR_PESO = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'pipetas?\s*(?:/|por)\s*(\d+(?:[,\.]\d+)?)\s*kg',
    re.IGNORECASE,
)
_RE_DOSE_LOCAL_GOTAS = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'(gotas?)\s*(?:/|\bpor\b|\bem\b|\bno\b|\bnos\b|\bna\b|\bnas\b)?\s*'
    r'(?:cada\s+)?(olho(?:s)?|conduto(?:\s+auditivo)?|canal\s+auditivo|ouvido(?:s)?|narina(?:s)?)\b',
    re.IGNORECASE,
)
# Normaliza descrições de porte de raça para faixas de peso (kg)
_PORTE_PARA_KG = [
    (r'ra[cç]as?\s+gigantes?|gigante',     (50.0, None)),
    (r'ra[cç]as?\s+grandes?|grande',       (25.0, 50.0)),
    (r'ra[cç]as?\s+m[eé]dias?|m[eé]dio',  (10.0, 25.0)),
    (r'ra[cç]as?\s+pequenas?|pequeno',     (0.0,  10.0)),
    (r'ra[cç]as?\s+mini(?:atura)?|mini\b', (0.0,   5.0)),
]


def _porte_para_faixa(texto: str):
    """Retorna (peso_min_kg, peso_max_kg, faixa_str) para descrição de porte ou (None, None, None)."""
    t = texto.lower()
    for pat, (pmin, pmax) in _PORTE_PARA_KG:
        if re.search(pat, t, re.IGNORECASE):
            label = f"até {int(pmax)} kg" if pmin == 0 else (
                f"acima de {int(pmin)} kg" if pmax is None else
                f"{int(pmin)}–{int(pmax)} kg"
            )
            return pmin, pmax, label
    return None, None, None


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

# Indicações clínicas conhecidas. A ordem da lista resolve patterns que se
# sobrepõem: "dermatite atópica" vence "alergia", etc. Inclui typos comuns do
# VetSmart (ex.: "Imun**u**ssupressão").
_INDICACAO_PATTERNS = [
    # Dermato específicos têm prioridade sobre "alergia" genérica.
    (r'dermatite\s+at[oó]pica|atopia\b',                       'Dermatite atópica'),
    (r'dermatite\s+seborr[eé]ica|seborreia',                   'Dermatite seborreica'),
    (r'dermatopatia|dermatose',                                'Dermatopatia'),
    # Imunológicos / reumato.
    # Tolera typos da VetSmart nos dois 's' (imunosupressão, imunossupresão),
    # espaço/hífen entre 'imuno' e 'supressão', e no inglês "suppression".
    (r'imun[ouó]s{0,2}[\s-]?s?upres{1,2}[aã]o|imuno[\s-]?suppress?[aã]o|imun[ouó]s{0,2}[\s-]?s?upressor',
        'Imunossupressão'),
    (r'artrite\s+reumat[oó]ide|lupus|lúpus',                   'Autoimune'),
    (r'osteoartrite|osteoarticular|artrose',                   'Osteoarticular'),
    # Endócrino (Addison/Cushing são nomes próprios na literatura).
    (r'hipocort(?:icismo|isolismo)|addison',                   'Hipoadrenocorticismo'),
    (r'hipercort(?:icismo|isolismo)|cushing',                  'Hipercortisolismo'),
    (r'endocrinopat(?:ia|ias)',                                'Endocrinopatia'),
    # Outras sistêmicas.
    (r'neoplas(?:ia|ias|ico|icos)|tumor(?:es)?\b|\bc[aâ]ncer\b',
        'Neoplasia'),
    (r'choque\b',                                              'Choque'),
    (r'oftalmopat(?:ia|ias)|uve[ií]te|conjuntivite',           'Oftalmopatia'),
    (r'edema\s+cerebral|edema\s+(?:cranian|medular)',          'Edema do SNC'),
    # Uso / duração.
    (r'uso\s+prolongado|manuten[cç][aã]o\b',                   'Uso prolongado'),
    # Genéricos (ficam no fim porque perdem de patterns mais específicos).
    (r'anti[-\s]?inflamat[oó]rio',                             'Anti-inflamatório'),
    (r'analges?i[ao]|controle\s+da\s+dor|\bdor\b',             'Analgesia'),
    (r'asma|broncoespasmo|broncopat|bronqu',                   'Respiratório'),
    (r'infec[cç][aã]o|bacteri|infec[cç][oõ]es',                'Infecção'),
    (r'al[eé]rg(?:ia|ias|ico|icos|ica|icas)',                  'Alergia'),
    (r'prurido|coceira',                                       'Prurido'),
]

_INDICACOES_GENERICAS_CORTICOIDE = {
    'Anti-inflamatório',
    'Uso prolongado',
}


def _extrair_indicacao(texto: str) -> Optional[str]:
    """Mapeia texto → nome canônico da indicação clínica, ou None.

    Entre múltiplas matches, vence a que aparece PRIMEIRO no texto
    (ex.: "Alergias e imunossupressão" → "Alergia"). Patterns específicos
    (dermatite atópica) ainda vencem genéricos (alergia) quando casam na
    MESMA posição, porque ordem-na-lista é o critério de desempate.
    """
    if not texto:
        return None
    melhor: Optional[tuple] = None  # (pos, prioridade_lista, nome)
    for prioridade, (pat, nome) in enumerate(_INDICACAO_PATTERNS):
        m = re.search(pat, texto, flags=re.IGNORECASE)
        if not m:
            continue
        chave = (m.start(), prioridade)
        if melhor is None or chave < melhor[0]:
            melhor = (chave, nome)
    return melhor[1] if melhor else None


def _extrair_indicacoes_multiplas(texto: str) -> List[str]:
    """Retorna indicações canônicas únicas na ordem em que aparecem no texto."""
    if not texto:
        return []
    achados: List[tuple[int, int, str]] = []
    for prioridade, (pat, nome) in enumerate(_INDICACAO_PATTERNS):
        for m in re.finditer(pat, texto, flags=re.IGNORECASE):
            achados.append((m.start(), prioridade, nome))
    if not achados:
        return []
    achados.sort()
    vistos: set[str] = set()
    resultado: List[str] = []
    for _, _, nome in achados:
        if nome in vistos:
            continue
        vistos.add(nome)
        resultado.append(nome)
    return resultado


def _eh_contexto_corticoide(classificacao: Optional[str], indicacoes_texto: Optional[str] = None) -> bool:
    alvo = ' '.join([classificacao or '', indicacoes_texto or '']).lower()
    return any(token in alvo for token in (
        'esteroidal', 'cortic', 'prednis', 'dexamet', 'hidrocortis', 'metilpred',
    ))


def _refinar_indicacao_dose(
    indicacao_base: Optional[str],
    *,
    linha: str,
    seg_txt: str,
    frequencia_texto: Optional[str],
    duracao_texto: Optional[str],
    indicacoes_texto: Optional[str],
    classificacao: Optional[str],
) -> Optional[str]:
    """Refina rótulos genéricos de dose para contextos clínicos mais úteis.

    Foco principal: corticosteroides, nos quais rótulos como "Anti-inflamatório"
    e "Uso prolongado" costumam ser pouco úteis para a prescrição assistida.
    """
    contexto_linha = ' '.join(filter(None, [linha, seg_txt]))
    contexto_local = ' '.join(filter(None, [
        contexto_linha, frequencia_texto or '', duracao_texto or '',
    ]))
    if not contexto_linha:
        return indicacao_base

    candidatas_locais = _extrair_indicacoes_multiplas(contexto_linha)

    if re.search(r'hipoadrenocortic|hipocort(?:icismo|isolismo)|addison|substitui[cç][aã]o|hipoadrenocortical', contexto_linha, re.IGNORECASE):
        return 'Hipoadrenocorticismo'

    if indicacao_base == 'Uso prolongado':
        for nome in candidatas_locais:
            if nome not in _INDICACOES_GENERICAS_CORTICOIDE:
                return nome

    if _eh_contexto_corticoide(classificacao, indicacoes_texto):
        if re.search(r'al[eé]rg|prurido|coceira|atopi|dermatite', contexto_linha, re.IGNORECASE):
            if 'Dermatite atópica' in candidatas_locais:
                return 'Dermatite atópica'
            return 'Alergia'
        if re.search(r'imun[ouó]s{0,2}[\s-]?s?upres|autoimun|lupus|lúpus', contexto_linha, re.IGNORECASE):
            return 'Imunossupressão'

        if indicacao_base in _INDICACOES_GENERICAS_CORTICOIDE or indicacao_base is None:
            for nome in candidatas_locais:
                if nome not in _INDICACOES_GENERICAS_CORTICOIDE:
                    return nome

    return indicacao_base or (candidatas_locais[0] if candidatas_locais else None)


def _splitar_por_indicacao(linha: str):
    """Quebra uma linha em segmentos [(indicacao, texto), ...].

    Exemplos:
      'Alergia VO, IM 0,5-1 mg/kg Imunossupressão VO, IM 2 mg/kg'
        → [('Alergia', 'VO, IM 0,5-1 mg/kg'),
           ('Imunossupressão', 'VO, IM 2 mg/kg')]

      'Alergias e imunossupressão: 12h'
        → [('Alergia', 'e imunossupressão: 12h')]  (a primeira vence, parser
           de dose a resolve sem ambiguidade)

      '0,5 mg/kg'  (sem indicação)
        → [(None, '0,5 mg/kg')]
    """
    if not linha:
        return [(None, linha)]
    positions = []
    for pat, nome in _INDICACAO_PATTERNS:
        for m in re.finditer(pat, linha, flags=re.IGNORECASE):
            positions.append((m.start(), m.end(), nome))
    if not positions:
        return [(None, linha)]
    # Dedup por posição (primeira match vence para patterns que se sobrepõem)
    positions.sort()
    merged = []
    for ini, fim, nome in positions:
        if merged and ini < merged[-1][1]:
            continue
        merged.append((ini, fim, nome))
    segmentos = []
    for i, (ini, fim, nome) in enumerate(merged):
        prox_ini = merged[i + 1][0] if i + 1 < len(merged) else len(linha)
        seg_texto = linha[fim:prox_ini].strip(' -:—,.')
        segmentos.append((nome, seg_texto))
    # Se texto antes da primeira indicação contém dose numérica, adicionamos
    # como segmento sem indicação (raro — normalmente indicação vem antes)
    pre = linha[:merged[0][0]].strip(' -:—,.')
    if pre and (_RE_DOSE_MGKG.search(pre) or _RE_DOSE_ANIMAL.search(pre)):
        segmentos.insert(0, (None, pre))
    return segmentos


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
    """Converte texto de frequência em intervalo em horas (valor único).
    Mantida para retrocompatibilidade — prefira _intervalo_horas_faixa."""
    mn, _ = _intervalo_horas_faixa(freq_texto)
    return mn


def _intervalo_horas_faixa(freq_texto: str) -> tuple:
    """Retorna (min_horas, max_horas) a partir do texto de frequência.

    Detecta faixas explícitas como 'a cada 8–12h', 'a cada 8 a 12 horas',
    'a cada 8h ou 12h'.  Quando há valor único, devolve (v, v).
    Devolve (None, None) quando não detecta nada.
    """
    if not freq_texto:
        return (None, None)
    t = freq_texto.lower()
    if 'dose unica' in t.replace('ú', 'u') or 'dose única' in t:
        return (None, None)

    # ── abreviações veterinárias latinas ────────────────────────────────────
    # SID/q24h=24h, BID/q12h=12h, TID/q8h=8h, QID/q6h=6h, EOD/q48h=48h
    _VET_ABBR = [
        (r'\bsid\b|q\s*24\s*h\b',         24),
        (r'\bbid\b|q\s*12\s*h\b',         12),
        (r'\btid\b|q\s*8\s*h\b',           8),
        (r'\bqid\b|q\s*6\s*h\b',           6),
        (r'\beod\b|q\s*48\s*h\b|every\s+other\s+day', 48),
    ]
    for pat, horas in _VET_ABBR:
        if re.search(pat, t):
            return (horas, horas)

    # ── faixa explícita ──────────────────────────────────────────────────────
    _h = r'(?:h|horas?|hrs?)'
    range_pats = [
        # "8/8 horas 12/12 horas" — dois valores VetSmart colados com espaço
        rf'(\d+)\s*/\s*\d+\s*{_h}\s+(\d+)\s*/\s*\d+\s*{_h}',
        # "a cada 8 a 12 horas" / "a cada 8-12h" / "a cada 8–12h"
        rf'a\s+cada\s+(\d+)\s*(?:{_h})?\s*(?:a|–|-|ou)\s*(\d+)\s*{_h}',
        # "8/8 a 12/12 horas" — com separador explícito
        rf'(\d+)\s*/\s*\d+\s*(?:a|–|-)\s*(\d+)\s*/\s*\d+\s*horas?',
        # "8-12h" / "8–12h" standalone (sem "a cada")
        rf'(\d+)\s*(?:–|-)\s*(\d+)\s*{_h}\b',
        # "de 8 a 12 horas" / "entre 8 e 12 horas"
        rf'(?:de|entre)\s+(\d+)\s*(?:{_h})?\s*(?:a|e)\s+(\d+)\s*{_h}',
    ]
    for pat in range_pats:
        m = re.search(pat, t)
        if m:
            v1, v2 = int(m.group(1)), int(m.group(2))
            return (min(v1, v2), max(v1, v2))

    # ── valor único ──────────────────────────────────────────────────────────
    for pat in [
        r'(\d+)\s*/\s*\d+\s*horas?',
        r'(\d+)\s*em\s*\d+\s*horas?',
        rf'a\s+cada\s+(\d+)\s*{_h}\b',
        r'a\s+cada\s+(\d+)\s*dias?',
    ]:
        m = re.search(pat, t)
        if m:
            v = int(m.group(1))
            v = v * 24 if 'dia' in pat else v
            return (v, v)
    m = re.search(r'(\d+)\s*(?:x|vezes?)\s*(?:ao|por)?\s*dia', t)
    if m:
        n = int(m.group(1))
        v = 24 // n if n > 0 else None
        return (v, v) if v else (None, None)
    # Fallback liberal
    m = re.search(r'(?<!\d)(?<![\.,])\b(\d{1,2})\s*(?:h|horas?|hrs?)\b', t)
    if m:
        v = int(m.group(1))
        if 2 <= v <= 72:
            return (v, v)
    return (None, None)


def _duracao_dias(dur_texto: str):
    """Retorna (min_dias, max_dias). (None, None) se não detectou.

    Cobre:
      Faixas em dias  : "7 a 14 dias", "7-14 dias", "7–14 dias"
      Faixas em semanas: "1 a 2 semanas", "2-3 semanas"
      Faixas em meses : "1 a 2 meses"
      Máximo em dias  : "até 14 dias", "no máximo 10 dias"
      Máximo em semanas: "até 3 semanas"
      Máximo em meses : "até 2 meses"
      Mínimo em dias  : "mínimo 7 dias", "pelo menos 5 dias", "no mínimo 10 dias"
      Valor único dias: "7 dias", "durante 14 dias", "por 10 dias"
      Valor único semanas: "2 semanas", "durante 3 semanas"
      Valor único meses: "1 mês", "2 meses"
    """
    if not dur_texto:
        return (None, None)
    t = dur_texto.lower().replace(',', '.')

    _sep = r'\s*(?:a|–|-|até|ate)\s*'

    # ── faixas ──────────────────────────────────────────────────────────────
    # dias
    m = re.search(rf'(\d+){_sep}(\d+)\s*dias?', t)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # semanas
    m = re.search(rf'(\d+){_sep}(\d+)\s*semanas?', t)
    if m:
        return (int(m.group(1)) * 7, int(m.group(2)) * 7)

    # meses
    m = re.search(rf'(\d+){_sep}(\d+)\s*m[eê]s(?:es)?', t)
    if m:
        return (int(m.group(1)) * 30, int(m.group(2)) * 30)

    # ── máximos ─────────────────────────────────────────────────────────────
    m = re.search(r'(?:até|ate|no\s+m[aá]ximo)\s*(\d+)\s*dias?', t)
    if m:
        return (None, int(m.group(1)))

    m = re.search(r'(?:até|ate|no\s+m[aá]ximo)\s*(\d+)\s*semanas?', t)
    if m:
        return (None, int(m.group(1)) * 7)

    m = re.search(r'(?:até|ate|no\s+m[aá]ximo)\s*(\d+)\s*m[eê]s(?:es)?', t)
    if m:
        return (None, int(m.group(1)) * 30)

    # ── mínimos ─────────────────────────────────────────────────────────────
    m = re.search(r'(?:m[ií]nimo|pelo\s+menos|no\s+m[ií]nimo)\s*(?:de\s*)?(\d+)\s*dias?', t)
    if m:
        return (int(m.group(1)), None)

    m = re.search(r'(?:m[ií]nimo|pelo\s+menos|no\s+m[ií]nimo)\s*(?:de\s*)?(\d+)\s*semanas?', t)
    if m:
        return (int(m.group(1)) * 7, None)

    # ── valores únicos ───────────────────────────────────────────────────────
    m = re.search(r'(\d+)\s*dias?', t)
    if m:
        n = int(m.group(1))
        return (n, n)

    m = re.search(r'(\d+)\s*semanas?', t)
    if m:
        d = int(m.group(1)) * 7
        return (d, d)

    m = re.search(r'(\d+)\s*m[eê]s(?:es)?', t)
    if m:
        d = int(m.group(1)) * 30
        return (d, d)

    return (None, None)


def _extrair_doses_estruturadas(
    dose_linhas: List[str],
    via: Optional[str],
    frequencia_texto: Optional[str],
    duracao_texto: Optional[str],
    especies_str: Optional[str],
    indicacoes_texto: Optional[str] = None,
    classificacao: Optional[str] = None,
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

    freq_min_h, freq_max_h = _intervalo_horas_faixa(frequencia_texto or '')
    intervalo = freq_min_h  # backward-compat: menor intervalo = mais frequente
    dur_min, dur_max = _duracao_dias(duracao_texto or '')
    # VetSmart costuma colar duração dentro do próprio texto de frequência:
    # "Dermatite atópica: 24hrs por 7 dias". Se a duração ficou vazia,
    # tenta extrair do campo de frequência.
    if dur_min is None and dur_max is None:
        dur_min_freq, dur_max_freq = _duracao_dias(frequencia_texto or '')
        if dur_min_freq is not None or dur_max_freq is not None:
            dur_min, dur_max = dur_min_freq, dur_max_freq
    esp_default = _norm_especie_code(especies_str or '')

    # Linhas — usa o split existente + quebra adicional por "." e ";"
    texto_join = '\n'.join(dose_linhas)
    # Divide em linhas por quebras de linha e ponto-e-vírgula.
    # IMPORTANTE: não dividir por "." pois isso quebra decimais como "0.5 mg/kg"
    # e "1,5 comprimido". Divide por ponto SOMENTE quando não está entre dígitos.
    linhas = [l.strip() for l in re.split(r'[\n;]|(?<!\d)\.(?!\d)', texto_join) if l.strip()]

    registros: List[Dict[str, Any]] = []
    esp_ctx = esp_default
    peso_min_ctx, peso_max_ctx = None, None
    peso_faixa_str = None
    indicacao_ctx: Optional[str] = None

    # Indicação vinda da frequência/texto geral serve como fallback quando a
    # linha da dose não tem uma indicação explícita adjacente. Ex.:
    # freq="Alergias e imunossupressão: 12h" → indicação default "Alergia".
    indicacao_freq = _extrair_indicacao(frequencia_texto or '')

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
        else:
            # Porte-based description: "raças pequenas", "raças grandes", etc.
            p_min, p_max, p_label = _porte_para_faixa(linha)
            if p_label:
                peso_min_ctx, peso_max_ctx = p_min, p_max
                peso_faixa_str = p_label

        # Atualiza (ou limpa) contexto de indicação.
        # Uma linha puramente textual sem números e sem indicação reconhecida
        # provavelmente é um cabeçalho de subseção (ex.: "Modo de usar",
        # "Observações") — nesse caso limpamos o contexto para não
        # "contaminar" doses de seções posteriores com indicações anteriores.
        ind_linha = _extrair_indicacao(linha)
        if ind_linha:
            indicacao_ctx = ind_linha
        elif (not re.search(r'\d', linha)
              and not _RE_ESPECIE_TXT.search(linha)
              and len(linha.split()) <= 6):
            indicacao_ctx = None

        # Quebra a linha em segmentos por indicação — se a mesma linha tem
        # duas indicações (ex.: "Alergia VO 0,5-1 mg/kg Imunossupressão VO 2 mg/kg")
        # cada uma vira um segmento próprio.
        segmentos = _splitar_por_indicacao(linha)

        for ind_seg, seg_txt in segmentos:
            # Resolve indicação para este segmento: segmento > linha > freq.
            indicacao_final = ind_seg or indicacao_ctx or indicacao_freq
            indicacao_final = _refinar_indicacao_dose(
                indicacao_final,
                linha=linha,
                seg_txt=seg_txt,
                frequencia_texto=frequencia_texto,
                duracao_texto=duracao_texto,
                indicacoes_texto=indicacoes_texto,
                classificacao=classificacao,
            )

            # mg/kg (com espaços tolerados)
            m = _RE_DOSE_MGKG.search(seg_txt)
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
                    'intervalo_min_horas': freq_min_h,
                    'intervalo_max_horas': freq_max_h,
                    'duracao':       duracao_texto,
                    'duracao_min_dias': dur_min,
                    'duracao_max_dias': dur_max,
                    'indicacao':     indicacao_final,
                    'observacao':    linha[:500] if len(linha) > 30 else None,
                    'dose_raw_text': linha,
                    'fonte':         'SCRAPER',
                    'confianca':     'MEDIA',
                })
                continue

            # X/animal
            m = _RE_DOSE_ANIMAL.search(seg_txt)
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
                    'intervalo_min_horas': freq_min_h,
                    'intervalo_max_horas': freq_max_h,
                    'duracao':       duracao_texto,
                    'duracao_min_dias': dur_min,
                    'duracao_max_dias': dur_max,
                    'indicacao':     indicacao_final,
                    'observacao':    linha[:500] if len(linha) > 30 else None,
                    'dose_raw_text': linha,
                    'fonte':         'SCRAPER',
                    'confianca':     'MEDIA',
                })
                continue

            # X gotas por olho / conduto auditivo / narina
            m = _RE_DOSE_LOCAL_GOTAS.search(seg_txt)
            if m:
                dose_min, dose_max = _f(m.group(1)), (_f(m.group(2)) if m.group(2) else _f(m.group(1)))
                local_txt = (m.group(4) or '').lower()
                if 'olho' in local_txt:
                    local_legivel = 'olho'
                elif 'narina' in local_txt:
                    local_legivel = 'narina'
                else:
                    local_legivel = 'conduto auditivo'
                dose_str = (f"{m.group(1)} - {m.group(2)} gotas/{local_legivel}"
                            if m.group(2) else f"{m.group(1)} gotas/{local_legivel}")
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
                    'dose_unidade':  'GOTAS_ANIMAL',
                    'frequencia':    frequencia_texto,
                    'intervalo_horas': intervalo,
                    'intervalo_min_horas': freq_min_h,
                    'intervalo_max_horas': freq_max_h,
                    'duracao':       duracao_texto,
                    'duracao_min_dias': dur_min,
                    'duracao_max_dias': dur_max,
                    'indicacao':     indicacao_final,
                    'observacao':    linha[:500] if len(linha) > 30 else None,
                    'dose_raw_text': linha,
                    'fonte':         'SCRAPER',
                    'confianca':     'MEDIA',
                })
                continue

            # "1 comprimido / 10 kg" → COMPRIMIDOS_KG (dose normalizada por peso)
            m = _RE_DOSE_CP_POR_PESO.search(seg_txt)
            if m:
                qtd_min = _f(m.group(1))
                qtd_max = _f(m.group(2)) if m.group(2) else qtd_min
                kg_base = _f(m.group(4))
                if kg_base and kg_base > 0:
                    dose_min = round(qtd_min / kg_base, 6)
                    dose_max = round(qtd_max / kg_base, 6)
                    cp_label = m.group(1) + (f' - {m.group(2)}' if m.group(2) else '')
                    dose_str = f"{cp_label} comprimido(s) / {int(kg_base) if kg_base == int(kg_base) else kg_base} kg"
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
                        'dose_unidade':  'COMPRIMIDOS_KG',
                        'frequencia':    frequencia_texto,
                        'intervalo_horas': intervalo,
                        'duracao':       duracao_texto,
                        'duracao_min_dias': dur_min,
                        'duracao_max_dias': dur_max,
                        'indicacao':     indicacao_final,
                        'observacao':    linha[:500] if len(linha) > 30 else None,
                        'dose_raw_text': linha,
                        'fonte':         'SCRAPER',
                        'confianca':     'MEDIA',
                    })
                    continue

            # "0.5 comprimido / dia" → COMPRIMIDOS_ANIMAL (dose plana diária)
            m = _RE_DOSE_CP_PLANO.search(seg_txt)
            if m:
                dose_min = _f(m.group(1))
                dose_max = _f(m.group(2)) if m.group(2) else dose_min
                cp_label = m.group(1) + (f' - {m.group(2)}' if m.group(2) else '')
                dose_str = f"{cp_label} comprimido(s)/dia"
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
                    'dose_unidade':  'COMPRIMIDOS_ANIMAL',
                    'frequencia':    frequencia_texto,
                    'intervalo_horas': intervalo,
                    'intervalo_min_horas': freq_min_h,
                    'intervalo_max_horas': freq_max_h,
                    'duracao':       duracao_texto,
                    'duracao_min_dias': dur_min,
                    'duracao_max_dias': dur_max,
                    'indicacao':     indicacao_final,
                    'observacao':    linha[:500] if len(linha) > 30 else None,
                    'dose_raw_text': linha,
                    'fonte':         'SCRAPER',
                    'confianca':     'MEDIA',
                })
                continue

            # "1 pipeta / 10 kg" → PIPETA_KG
            m = _RE_DOSE_PIPETA_POR_PESO.search(seg_txt)
            if m:
                qtd_min = _f(m.group(1))
                qtd_max = _f(m.group(2)) if m.group(2) else qtd_min
                kg_base = _f(m.group(3))
                if kg_base and kg_base > 0:
                    dose_min = round(qtd_min / kg_base, 6)
                    dose_max = round(qtd_max / kg_base, 6)
                    dose_str = f"{m.group(1)} pipeta(s) / {int(kg_base) if kg_base == int(kg_base) else kg_base} kg"
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
                        'dose_unidade':  'PIPETA_KG',
                        'frequencia':    frequencia_texto,
                        'intervalo_horas': intervalo,
                        'duracao':       duracao_texto,
                        'duracao_min_dias': dur_min,
                        'duracao_max_dias': dur_max,
                        'indicacao':     indicacao_final,
                        'observacao':    linha[:500] if len(linha) > 30 else None,
                        'dose_raw_text': linha,
                        'fonte':         'SCRAPER',
                        'confianca':     'MEDIA',
                    })
                    continue

    # Dedup por (especie_code, peso_min, peso_max, dose_min, dose_max, unidade, indicacao)
    vistos = set()
    unicos = []
    for r in registros:
        chave = (r['especie_code'], r['peso_min_kg'], r['peso_max_kg'],
                 r['dose_min'], r['dose_max'], r['dose_unidade'],
                 r.get('indicacao'))
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(r)
    return unicos


def _especie_label(code: str) -> str:
    return {'CAES': 'Cães', 'GATOS': 'Gatos', 'AMBOS': 'Cães e Gatos'}.get(code, code)


# --- Parser numérico de apresentação -----------------------------------------
_RE_CONC_MGML     = re.compile(r'(\d+(?:[,\.]\d+)?)\s*(mg|mcg|ui)\s*/\s*ml\b', re.IGNORECASE)
# "250 mg / 5 mL"  →  50 mg/mL  (numerador/denominador)
_RE_CONC_MG_VOL   = re.compile(r'(\d+(?:[,\.]\d+)?)\s*(mg|mcg|g|ui)\s*/\s*(\d+(?:[,\.]\d+)?)\s*ml\b', re.IGNORECASE)
_RE_CONC_MG       = re.compile(r'(\d+(?:[,\.]\d+)?)\s*(mg|mcg|g|ui)\b', re.IGNORECASE)
_RE_CONC_PERCENT  = re.compile(r'(\d+(?:[,\.]\d+)?)\s*%', re.IGNORECASE)
_RE_VOL_PAREN     = re.compile(r'\((\d+(?:[,\.]\d+)?)\s*(ml|un|g|kg|l)\b', re.IGNORECASE)
_RE_NOME_NUM_FINAL = re.compile(r'\b(\d+(?:[,\.]\d+)?)\s*$')  # "Rilexine palatável 75"


def _norm_ascii_lower(texto: str) -> str:
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", texto or "")
    return nfkd.encode("ASCII", "ignore").decode().lower()


_FORMAS_LIQUIDAS = (
    'suspens', 'solucao oral', 'solucao', 'xarope', 'elixir', 'emuls',
    'liquido', 'gotas', 'gota',
)
_FORMAS_SOLIDAS = (
    'comprim', 'capsul', 'tablete', 'drage', 'petisco', 'biscoito',
)
_FORMAS_INJETAVEIS = ('injet', 'ampola', 'frasco ampola', 'frasco-ampola')
_FORMAS_TOPICAS = ('pomada', 'creme', 'gel', 'spray', 'locao', 'shampoo', 'xampu')
_FORMAS_OFTALMICAS = ('colirio', 'oftalm')
_FORMAS_OTICAS = ('otolog', 'auric', 'ouvido')
_FABRICANTE_MANIPULADO = (
    'manipul', 'farmacia', 'ligvet', 'animalia farma', 'animaliapharma',
    'formula animal',
)


def _forma_categoria_apresentacao(forma: Optional[str], conc_raw: Optional[str] = None) -> str:
    texto = _norm_ascii_lower(f"{forma or ''} {conc_raw or ''}")
    if any(t in texto for t in _FORMAS_OFTALMICAS):
        return 'oftalmico'
    if any(t in texto for t in _FORMAS_OTICAS):
        return 'otico'
    if any(t in texto for t in _FORMAS_INJETAVEIS):
        return 'injetavel'
    if any(t in texto for t in _FORMAS_TOPICAS):
        return 'topico'
    if any(t in texto for t in ('suspens',)):
        return 'suspensao_oral'
    if any(t in texto for t in _FORMAS_LIQUIDAS):
        return 'liquido_oral'
    if any(t in texto for t in _FORMAS_SOLIDAS):
        return 'solido_oral'
    if any(t in texto for t in ('cartucho', 'blister', 'display', 'caixa', 'cartela')):
        return 'solido_oral'
    return 'outros'


def _unidade_pratica_canonica(forma: Optional[str], categoria: Optional[str] = None) -> str:
    texto = _norm_ascii_lower(forma or '')
    cat = categoria or _forma_categoria_apresentacao(forma)
    if 'gota' in texto or cat in {'oftalmico', 'otico'}:
        return 'gota'
    if cat in {'suspensao_oral', 'liquido_oral', 'injetavel'}:
        return 'mL'
    if 'capsul' in texto:
        return 'capsula'
    if any(t in texto for t in ('comprim', 'tablete', 'drage', 'cartucho', 'blister', 'display', 'caixa', 'cartela')):
        return 'comprimido'
    if 'petisco' in texto or 'biscoito' in texto:
        return 'petisco'
    if cat == 'topico':
        return 'aplicacao'
    return 'unidade'


def _fabricante_eh_manipulado(fabricante: Optional[str]) -> bool:
    texto = _norm_ascii_lower(fabricante or '')
    return any(t in texto for t in _FABRICANTE_MANIPULADO)


def _chave_canonica_apresentacao(ap: Dict[str, Any], fabricante: Optional[str] = None) -> tuple:
    categoria = ap.get('forma_categoria') or _forma_categoria_apresentacao(ap.get('forma'), ap.get('concentracao'))
    unidade_pratica = ap.get('unidade_pratica') or _unidade_pratica_canonica(ap.get('forma'), categoria)
    valor = ap.get('concentracao_valor')
    try:
        valor_key = round(float(valor), 4) if valor is not None else None
    except (TypeError, ValueError):
        valor_key = None
    unidade = _norm_ascii_lower(str(ap.get('concentracao_unidade') or ''))
    tipo_origem = 'manipulado' if _fabricante_eh_manipulado(fabricante) else 'comercial'
    # Dedupe by clinical/admin intent. Manufacturer is kept as provenance, not
    # as a visual multiplier.
    return (categoria, valor_key, unidade, unidade_pratica, tipo_origem)


def _enriquecer_apresentacao_canonica(ap: Dict[str, Any], fabricante: Optional[str] = None) -> Dict[str, Any]:
    categoria = _forma_categoria_apresentacao(ap.get('forma'), ap.get('concentracao'))
    ap['forma_categoria'] = categoria
    ap['unidade_pratica'] = _unidade_pratica_canonica(ap.get('forma'), categoria)
    ap['tipo_origem'] = 'manipulado' if _fabricante_eh_manipulado(fabricante) else 'comercial'
    return ap


def _deduplicar_apresentacoes_canonicas(apresentacoes: List[Dict[str, Any]], fabricante: Optional[str] = None) -> List[Dict[str, Any]]:
    unicas: Dict[tuple, Dict[str, Any]] = {}
    for ap in apresentacoes or []:
        ap = _enriquecer_apresentacao_canonica(dict(ap), fabricante)
        chave = _chave_canonica_apresentacao(ap, fabricante)
        atual = unicas.get(chave)
        if not atual:
            unicas[chave] = ap
            continue
        # Prefer the row with richer original text while preserving the same
        # canonical clinical option.
        if len(str(ap.get('concentracao') or '')) > len(str(atual.get('concentracao') or '')):
            unicas[chave] = ap
    return list(unicas.values())


def _apresentacao_eh_solida(ap: Dict[str, Any]) -> bool:
    forma = _norm_ascii_lower(str(ap.get('forma') or ''))
    unidade = _norm_ascii_lower(str(ap.get('concentracao_unidade') or ''))
    if not ap.get('concentracao_valor') or not unidade:
        return False
    if unidade in {'mg/ml', 'mcg/ml'}:
        return False
    if any(token in forma for token in ('suspens', 'solucao', 'xarope', 'colirio', 'gota', 'spray', 'gel', 'pomada', 'creme', 'pasta', 'locao')):
        return False
    return True


def _dose_tem_forca_explicita_registro(reg: Dict[str, Any]) -> bool:
    for texto in (reg.get('dose'), reg.get('dose_raw_text'), reg.get('observacao')):
        norm = _norm_ascii_lower(str(texto or ''))
        if re.search(r'\b\d+(?:[.,]\d+)?\s*(mg|mcg|g|ui)\b', norm):
            return True
    return False


def _pos_processar_doses_por_apresentacao(
    doses: List[Dict[str, Any]],
    apresentacoes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Enriquece ou descarta doses por comprimido sem força explícita.

    Regra de segurança:
      - se a página tem uma única força sólida conhecida, anexa essa força ao
        texto da dose;
      - se a página tem múltiplas forças sólidas e a dose não diz qual é,
        descarta a linha por ambiguidade.
    """
    forcas = []
    vistos: set[tuple[float, str]] = set()
    for ap in apresentacoes or []:
        if not _apresentacao_eh_solida(ap):
            continue
        chave = (float(ap['concentracao_valor']), str(ap['concentracao_unidade']).lower())
        if chave in vistos:
            continue
        vistos.add(chave)
        forcas.append(chave)

    if not forcas:
        return doses

    saida: List[Dict[str, Any]] = []
    unica_forca = None
    if len(forcas) == 1:
        valor, unidade = forcas[0]
        valor_txt = str(int(valor)) if float(valor).is_integer() else str(valor).replace('.', ',')
        unica_forca = f'{valor_txt} {unidade}'

    for reg in doses:
        unidade = (reg.get('dose_unidade') or '').upper()
        if unidade not in {'COMPRIMIDOS_ANIMAL', 'COMPRIMIDOS_KG'} or _dose_tem_forca_explicita_registro(reg):
            saida.append(reg)
            continue

        if len(forcas) > 1:
            continue

        if unica_forca:
            dose_txt = str(reg.get('dose') or '')
            if ' de ' not in dose_txt.lower():
                dose_txt = re.sub(r'(comprimido\(s\)|comprimidos?|c[aá]psulas?)', rf'\1 de {unica_forca}', dose_txt, count=1, flags=re.IGNORECASE)
                reg['dose'] = dose_txt
        saida.append(reg)
    return saida


def _percentual_equivale_mg_ml(forma: str, conc_raw: str) -> bool:
    """Converte % para mg/mL apenas quando a apresentação é líquida.

    Em soluções, suspensões, colírios e injetáveis, a convenção prática é
    1% = 10 mg/mL. Em formas não líquidas mantemos '%' para não assumir uma
    equivalência inadequada.
    """
    texto = _norm_ascii_lower(f"{forma} {conc_raw}")
    hints = (
        'colirio', 'oftalm', 'conta-gotas', 'gota', 'solucao',
        'suspens', 'xarope', 'elixir', 'emuls', 'frasco ampola',
        'frasco-ampola', 'injet', 'oral',
    )
    return any(h in texto for h in hints)


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

    # 2) Concentração — ordem: "X mg/Y mL" > "X mg/mL" > "X%" > "X mg"
    # Tenta "250 mg / 5 mL" → 50 mg/mL antes das outras formas
    m = _RE_CONC_MG_VOL.search(conc_raw)
    if not m:
        # Também busca no nome do produto (ex: "Cefalexina 250 mg / 5 ml, solução")
        m = _RE_CONC_MG_VOL.search(nome_produto or '')
    if m:
        num   = _f(m.group(1))
        unit  = m.group(2).lower()
        denom = _f(m.group(3))
        if num is not None and denom and denom > 0:
            factor = 1000.0 if unit == 'g' else (0.001 if unit == 'mcg' else 1.0)
            out['concentracao_valor']   = round((num * factor) / denom, 4)
            out['concentracao_unidade'] = 'mg/ml'
    else:
        m = _RE_CONC_MGML.search(conc_raw)
        if m:
            out['concentracao_valor'] = _f(m.group(1))
            out['concentracao_unidade'] = f"{m.group(2).lower()}/ml"
        else:
            m = _RE_CONC_PERCENT.search(conc_raw)
            if m:
                percentual = _f(m.group(1))
                if percentual is not None:
                    if _percentual_equivale_mg_ml(forma, conc_raw):
                        out['concentracao_valor'] = percentual * 10.0
                        out['concentracao_unidade'] = 'mg/ml'
                    else:
                        out['concentracao_valor'] = percentual
                        out['concentracao_unidade'] = '%'
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
# Helpers de links / opções veterinárias
# ---------------------------------------------------------------------------
_RE_HREF_PRODUTO = re.compile(r"/(?:cg|CG|index\.php)?/produto/(\d+)", re.IGNORECASE)
_RE_OPCOES_VETERINARIAS = re.compile(r"opc[oõ]es veterin[aá]rias com", re.IGNORECASE)


def _href_produto_para_info(href: str, nome: Optional[str] = None) -> Optional[Dict[str, Any]]:
    href = (href or "").strip()
    m = _RE_HREF_PRODUTO.search(href)
    if not m:
        return None
    pid = int(m.group(1))
    nome_limpo = re.sub(r"^\s*(Avaliar|Ver|Detalhes)\s+", "", (nome or "").strip(), flags=re.IGNORECASE).strip()
    url = BASE_URL + href if href.startswith("/") else href
    return {"id": pid, "nome": (nome_limpo or f"Produto #{pid}")[:100], "url": url}


def _coletar_links_produto_html(
    html: str,
    ids_vistos: Optional[set] = None,
    excluir_pid: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Extrai links `/produto/` de um HTML arbitrário."""
    soup = BeautifulSoup(html, "html.parser")
    vistos = ids_vistos if ids_vistos is not None else set()
    links: List[Dict[str, Any]] = []
    for a in soup.select("a[href*='/produto/']"):
        info = _href_produto_para_info(a.get("href") or "", a.get_text(" ", strip=True))
        if not info:
            continue
        if excluir_pid is not None and info["id"] == excluir_pid:
            continue
        if info["id"] in vistos:
            continue
        vistos.add(info["id"])
        links.append(info)
    return links


def _extrair_links_opcoes_veterinarias(
    html: str,
    excluir_pid: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Extrai opções veterinárias ligadas a uma página canônica do princípio ativo."""
    soup = BeautifulSoup(html, "html.parser")
    vistos: set = set()
    saida: List[Dict[str, Any]] = []

    marcadores = [
        no.parent for no in soup.find_all(
            string=lambda s: bool(s and _RE_OPCOES_VETERINARIAS.search(s))
        )
    ]
    for marcador in marcadores:
        no = marcador
        while no is not None:
            no = no.find_next_sibling()
            if no is None:
                break
            if getattr(no, "name", None) in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                break
            saida.extend(
                _coletar_links_produto_html(
                    str(no),
                    ids_vistos=vistos,
                    excluir_pid=excluir_pid,
                )
            )

    if saida:
        return saida

    return _coletar_links_produto_html(html, ids_vistos=vistos, excluir_pid=excluir_pid)


# ---------------------------------------------------------------------------
# Scraping da lista de produtos
# ---------------------------------------------------------------------------
def _coletar_links_da_pagina(page, ids_vistos: set) -> List[Dict[str, Any]]:
    """Extrai todos os links de produto novos da página atual."""
    novos = []
    links = page.query_selector_all("a[href*='/produto/']")
    for link in links:
        nome_raw = (link.inner_text() or "").strip()
        info = _href_produto_para_info(link.get_attribute("href") or "", nome_raw)
        if not info:
            continue
        pid = info["id"]
        if pid in ids_vistos:
            continue
        ids_vistos.add(pid)
        nome = info["nome"]
        # O <a> do card contém nome + fabricante em linhas separadas
        # (ex: "ACQUA Limp\nBIOFARM"). Pegamos só a primeira linha não vazia
        # para bater com o nome limpo que o detalhe retorna (e evitar duplicatas).
        for linha in nome.splitlines():
            linha = linha.strip()
            if linha:
                nome = linha
                break
        info["nome"] = (nome or f"Produto #{pid}")[:100]
        novos.append(info)
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
            page.goto(url_pag, wait_until="domcontentloaded", timeout=60000)
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
def scrape_detalhe_produto(page, info: Dict, return_html: bool = False):
    pid       = info["id"]
    url       = info["url"]
    nome_base = info["nome"]

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("h2.side-nav-title, section.container-content", timeout=12000)
    except Exception:
        pass
    aguardar_e_aceitar_cookies(page, timeout=4000)
    time.sleep(0.5)

    html = page.content()
    prod = extrair_produto_do_html(html, pid, nome_base)
    if return_html:
        return prod, html
    return prod


# ---------------------------------------------------------------------------
# Banco – cruzar e atualizar
# ---------------------------------------------------------------------------
def _norm(texto: str) -> str:
    """Normaliza nome para comparação idempotente: remove acentos, baixa,
    colapsa espaços/quebras internas em um único espaço, strip."""
    import unicodedata
    s = unicodedata.normalize("NFKD", texto or "").encode("ASCII", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _trunc(v, n):
    """Trunca para caber em varchar(n); retorna None se v vier vazio/None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:n]


def _atualizar_medicamento_existente(cur, medicamento_id: int, prod: 'ProdutoVetsmart') -> None:
    """Atualiza apenas lacunas úteis do medicamento canônico."""
    cur.execute("""
        UPDATE medicamento SET
          classificacao       = COALESCE(NULLIF(classificacao,''), %s),
          principio_ativo     = COALESCE(NULLIF(principio_ativo,''), %s),
          via_administracao   = COALESCE(NULLIF(via_administracao,''), %s),
          vetsmart_produto_id = COALESCE(vetsmart_produto_id, %s),
          bula                = COALESCE(NULLIF(bula,''), %s),
          observacoes         = COALESCE(NULLIF(observacoes,''), %s),
          conteudo_estruturado = CASE
            WHEN %s::json IS NULL OR %s::json::jsonb = '{}'::jsonb THEN conteudo_estruturado
            WHEN conteudo_estruturado IS NULL OR conteudo_estruturado::jsonb = '{}'::jsonb THEN %s
            WHEN COALESCE(conteudo_estruturado->'metadata'->>'parser_version', '') != 'v3' THEN %s
            WHEN ((conteudo_estruturado::jsonb->'raw_sections') IS NULL
                  OR (conteudo_estruturado::jsonb->'raw_sections') = '{}'::jsonb)
                 AND (%s::json->'raw_sections') IS NOT NULL
                 AND (%s::json->>'raw_sections') != '{}' THEN %s
            ELSE conteudo_estruturado
          END
         WHERE id = %s
    """, (
        _trunc(prod.classificacao, 100),           # classificacao COALESCE
        _trunc(prod.principio_ativo, 200),         # principio_ativo COALESCE
        _trunc(prod.via_administracao, 80),        # via_administracao COALESCE
        prod.vetsmart_id,                          # vetsmart_produto_id COALESCE
        prod.bula,                                 # bula COALESCE
        prod.observacoes,                          # observacoes COALESCE
        Json(prod.conteudo_estruturado or {}),     # CASE WHEN NULL check
        Json(prod.conteudo_estruturado or {}),     # CASE WHEN empty check
        Json(prod.conteudo_estruturado or {}),     # THEN empty-DB branch
        Json(prod.conteudo_estruturado or {}),     # THEN version-upgrade branch
        Json(prod.conteudo_estruturado or {}),     # WHEN raw_sections absent check 1
        Json(prod.conteudo_estruturado or {}),     # WHEN raw_sections absent check 2
        Json(prod.conteudo_estruturado or {}),     # THEN raw_sections-upgrade branch
        medicamento_id,                            # WHERE id
    ))

    cur.execute(
        "SELECT conteudo_estruturado FROM medicamento WHERE id = %s",
        (medicamento_id,),
    )
    row = cur.fetchone()
    conteudo_atual = row.get("conteudo_estruturado") if isinstance(row, dict) else (row[0] if row else None)
    conteudo_com_produto = _mesclar_produto_vetsmart(conteudo_atual or prod.conteudo_estruturado or {}, prod)
    cur.execute(
        "UPDATE medicamento SET conteudo_estruturado = %s WHERE id = %s",
        (Json(conteudo_com_produto), medicamento_id),
    )


def _encontrar_ou_criar_medicamento_por_pa(cur, prod: 'ProdutoVetsmart') -> int:
    """Garante que existe exatamente 1 Medicamento para o princípio ativo de
    `prod`. Retorna o medicamento_id.

    Estratégia:
      1. Se prod tem `principio_ativo` → busca medicamento com
         principio_ativo normalizado igual. Se achou, retorna esse.
      2. Senão, busca medicamento com `nome` normalizado igual a
         `prod.principio_ativo` (ex.: nome = "Prednisona").
      3. Senão, cria novo com nome = `prod.principio_ativo` ou `prod.nome`.

    Também atualiza campos faltantes do medicamento canônico com dados do
    prod (fabricante não é copiado — ele vive nas apresentações).
    """
    pa = (prod.principio_ativo or '').strip()
    pa_norm = _norm(pa) if pa else ''

    medicamento_id: Optional[int] = None
    if pa_norm:
        # Match por principio_ativo (pode haver várias linhas com mesmo PA;
        # pega a mais antiga/com maior número de apresentações já pelo id asc)
        cur.execute("""
            SELECT id, nome, classificacao, principio_ativo, via_administracao,
                   dosagem_recomendada, frequencia, duracao_tratamento,
                   observacoes, bula, vetsmart_produto_id
              FROM medicamento
             WHERE LOWER(REGEXP_REPLACE(
                     TRANSLATE(principio_ativo,
                               'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                               'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'),
                     '\\s+', ' ', 'g')) = %s
             ORDER BY id ASC
             LIMIT 1
        """, (pa_norm,))
        row = cur.fetchone()
        if row:
            medicamento_id = row["id"] if isinstance(row, dict) else row[0]

    if medicamento_id is None:
        # Cria novo medicamento usando PA como nome (ou o nome bruto como fallback)
        nome_final = pa if pa else prod.nome
        cur.execute("""
            INSERT INTO medicamento
              (nome, classificacao, principio_ativo, via_administracao,
               dosagem_recomendada, frequencia, duracao_tratamento,
               observacoes, bula, conteudo_estruturado, vetsmart_produto_id, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (
            nome_final[:100],
            _trunc(prod.classificacao, 100),
            _trunc(prod.principio_ativo, 200),
            _trunc(prod.via_administracao, 80),
            prod.dosagem_recomendada,
            _trunc(prod.frequencia, 100),
            prod.duracao_tratamento,
            prod.observacoes,
            prod.bula,
            Json(_mesclar_produto_vetsmart(prod.conteudo_estruturado or {}, prod)),
            prod.vetsmart_id,
            CREATED_BY_USER_ID,
        ))
        medicamento_id = cur.fetchone()["id"]
    else:
        # Atualiza campos vazios/faltantes com dados novos do prod (se úteis)
        _atualizar_medicamento_existente(cur, medicamento_id, prod)

    return medicamento_id


def _inserir_apresentacoes_consolidado(
    cur, medicamento_id: int, prod: 'ProdutoVetsmart',
) -> int:
    """Insere apresentações de `prod` sob o medicamento consolidado, evitando
    duplicatas (dedupe por forma+concentracao+fabricante).

    Retorna quantas foram efetivamente inseridas.
    """
    if not prod.apresentacoes:
        return 0

    # Carrega apresentações já existentes
    cur.execute("""
        SELECT id, forma, concentracao, fabricante,
               concentracao_valor, concentracao_unidade,
               volume_valor, volume_unidade
          FROM apresentacao_medicamento
         WHERE medicamento_id = %s
    """, (medicamento_id,))
    rows_existentes = list(cur.fetchall())
    keep_por_chave: Dict[tuple, Dict[str, Any]] = {}
    ids_remover: List[int] = []
    for r in rows_existentes:
        chave = _chave_canonica_apresentacao({
            "forma": r.get("forma") or '',
            "concentracao": r.get("concentracao") or '',
            "concentracao_valor": r.get("concentracao_valor"),
            "concentracao_unidade": r.get("concentracao_unidade"),
            "volume_valor": r.get("volume_valor"),
            "volume_unidade": r.get("volume_unidade"),
        }, r.get("fabricante") or '')
        atual = keep_por_chave.get(chave)
        if not atual:
            keep_por_chave[chave] = dict(r)
            continue
        atual_tem_conc = atual.get("concentracao_valor") is not None
        novo_tem_conc = r.get("concentracao_valor") is not None
        if novo_tem_conc and not atual_tem_conc:
            ids_remover.append(atual["id"])
            keep_por_chave[chave] = dict(r)
        else:
            ids_remover.append(r["id"])
    if ids_remover:
        cur.execute(
            "DELETE FROM apresentacao_medicamento WHERE id = ANY(%s)",
            (ids_remover,),
        )
        rows_existentes = [r for r in rows_existentes if r["id"] not in set(ids_remover)]

    existentes = {
        _chave_canonica_apresentacao({
            "forma": r.get("forma") or '',
            "concentracao": r.get("concentracao") or '',
            "concentracao_valor": r.get("concentracao_valor"),
            "concentracao_unidade": r.get("concentracao_unidade"),
            "volume_valor": r.get("volume_valor"),
            "volume_unidade": r.get("volume_unidade"),
        }, r.get("fabricante") or ''): r["id"]
        for r in rows_existentes
    }

    inseridas = 0
    for ap in _deduplicar_apresentacoes_canonicas(prod.apresentacoes or [], prod.fabricante):
        forma = ap.get("forma")
        if forma in ("N/A", "", None):
            continue
        chave = _chave_canonica_apresentacao(ap, prod.fabricante)
        if chave in existentes:
            continue  # já tem essa apresentação/fabricante
        cur.execute(
            """INSERT INTO apresentacao_medicamento
                 (medicamento_id, forma, concentracao,
                  nome_variante, concentracao_valor, concentracao_unidade,
                  volume_valor, volume_unidade,
                  fabricante, vetsmart_produto_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                medicamento_id,
                forma[:50],
                (ap.get("concentracao") or '')[:100],
                _trunc(ap.get("nome_variante"), 100),
                ap.get("concentracao_valor"),
                _trunc(ap.get("concentracao_unidade"), 20),
                ap.get("volume_valor"),
                _trunc(ap.get("volume_unidade"), 20),
                _trunc(prod.fabricante, 150),
                prod.vetsmart_id,
            ),
        )
        existentes[chave] = -1  # marca como inserida
        inseridas += 1
    return inseridas


def _inserir_doses_consolidado(
    cur, medicamento_id: int, doses: List[Dict[str, Optional[str]]],
) -> int:
    """Insere doses novas sob o medicamento consolidado.

    Faz dedup por (especie_code, peso_min, peso_max, dose_min, dose_max,
    dose_unidade, intervalo_horas, indicacao). Doses existentes com as mesmas
    chaves numéricas são preservadas.

    Retorna quantas foram efetivamente inseridas.
    """
    if not doses:
        return 0

    # Carrega doses já existentes pro dedup
    cur.execute("""
        SELECT id, especie_code, peso_min_kg, peso_max_kg,
               dose_min, dose_max, dose_unidade,
               intervalo_horas, indicacao
          FROM dose_medicamento
         WHERE medicamento_id = %s
    """, (medicamento_id,))
    def _dec(v):
        # Normaliza Decimal → float para comparação com o parser
        return float(v) if v is not None else None
    rows_doses = list(cur.fetchall())
    keep_doses: Dict[tuple, Dict[str, Any]] = {}
    ids_doses_remover: List[int] = []
    for r in rows_doses:
        chave = (
            (r.get("especie_code") or '').upper() or None,
            _dec(r.get("peso_min_kg")),
            _dec(r.get("peso_max_kg")),
            _dec(r.get("dose_min")),
            _dec(r.get("dose_max")),
            (r.get("dose_unidade") or '').upper() or None,
            r.get("intervalo_horas"),
            (r.get("indicacao") or '').strip() or None,
        )
        if chave in keep_doses:
            ids_doses_remover.append(r["id"])
        else:
            keep_doses[chave] = dict(r)
    if ids_doses_remover:
        cur.execute(
            "DELETE FROM dose_medicamento WHERE id = ANY(%s)",
            (ids_doses_remover,),
        )
        rows_doses = [r for r in rows_doses if r["id"] not in set(ids_doses_remover)]

    existentes = {
        (
            (r.get("especie_code") or '').upper() or None,
            _dec(r.get("peso_min_kg")),
            _dec(r.get("peso_max_kg")),
            _dec(r.get("dose_min")),
            _dec(r.get("dose_max")),
            (r.get("dose_unidade") or '').upper() or None,
            r.get("intervalo_horas"),
            (r.get("indicacao") or '').strip() or None,
        )
        for r in rows_doses
    }

    inseridas = 0
    for d in doses:
        chave = (
            (d.get("especie_code") or '').upper() or None,
            _dec(d.get("peso_min_kg")),
            _dec(d.get("peso_max_kg")),
            _dec(d.get("dose_min")),
            _dec(d.get("dose_max")),
            (d.get("dose_unidade") or '').upper() or None,
            d.get("intervalo_horas"),
            (d.get("indicacao") or '').strip() or None,
        )
        if chave in existentes:
            continue
        cur.execute("""
            INSERT INTO dose_medicamento
              (medicamento_id, especie, faixa_peso, via, dose, frequencia, duracao, observacao,
               especie_code, peso_min_kg, peso_max_kg,
               dose_min, dose_max, dose_unidade,
               intervalo_horas, intervalo_min_horas, intervalo_max_horas,
               duracao_min_dias, duracao_max_dias,
               dose_raw_text, fonte, confianca, indicacao)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,
                    %s,%s,
                    %s,%s,%s,%s)
        """, (
            medicamento_id,
            _trunc(d.get("especie"),       80),
            _trunc(d.get("faixa_peso"),    80),
            _trunc(d.get("via"),           80),
            _trunc(d.get("dose"),         200),
            _trunc(d.get("frequencia"),   120),
            _trunc(d.get("duracao"),      120),
            (d.get("observacao") or None),
            _trunc(d.get("especie_code"),  10),
            d.get("peso_min_kg"),
            d.get("peso_max_kg"),
            d.get("dose_min"),
            d.get("dose_max"),
            _trunc(d.get("dose_unidade"),  30),
            d.get("intervalo_horas"),
            d.get("intervalo_min_horas"),
            d.get("intervalo_max_horas"),
            d.get("duracao_min_dias"),
            d.get("duracao_max_dias"),
            (d.get("dose_raw_text") or None),
            _trunc(d.get("fonte") or 'SCRAPER',     15),
            _trunc(d.get("confianca") or 'MEDIA',   10),
            _trunc(d.get("indicacao"),    120),
        ))
        existentes.add(chave)
        inseridas += 1
    return inseridas


# Preservado apenas como alias defensivo para código legado — chamadas novas
# devem usar `_inserir_doses_consolidado`.
def _inserir_doses(cur, medicamento_id: int, doses):
    return _inserir_doses_consolidado(cur, medicamento_id, doses)


def cruzar_e_atualizar(conn, medicamentos_banco, produtos, dry_run=False):
    """Importa `produtos` do cache consolidando-os por princípio ativo.

    Para cada produto do VetSmart:
      1. Encontra (ou cria) UM único Medicamento com o mesmo principio_ativo.
      2. Faz merge das apresentações (dedup por forma+concentração+fabricante).
      3. Faz merge das doses (dedup por chave numérica+indicação).

    Resultado: "Prednisona Ligvet" + "Prednisona Animalia" + "Prednisona (PA)"
    viram um único Medicamento "Prednisona" com várias apresentações e doses.
    """
    stats = {
        "novos_medicamentos": 0,
        "medicamentos_atualizados": 0,
        "apres_inseridas": 0,
        "doses_inseridas": 0,
    }

    if dry_run:
        # Modo simulação: apenas loga o que seria feito
        for p in produtos:
            log.info(f"  [dry-run] '{p.nome}' PA={p.principio_ativo!r} "
                     f"fab={p.fabricante!r} "
                     f"apres={len(p.apresentacoes)} doses={len(p.doses)}")
        return stats

    for p in produtos:
        with conn.cursor() as cur:
            # Verifica se o PA já existe ANTES de criar (pra contabilizar)
            pa_norm = _norm(p.principio_ativo or '')
            existia = False
            if pa_norm:
                cur.execute("""
                    SELECT 1 FROM medicamento
                     WHERE LOWER(REGEXP_REPLACE(
                             TRANSLATE(principio_ativo,
                                       'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                                       'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'),
                             '\\s+', ' ', 'g')) = %s
                     LIMIT 1
                """, (pa_norm,))
                existia = cur.fetchone() is not None

            med_id = _encontrar_ou_criar_medicamento_por_pa(cur, p)

            if existia:
                stats["medicamentos_atualizados"] += 1
            else:
                stats["novos_medicamentos"] += 1

            n_apres = _inserir_apresentacoes_consolidado(cur, med_id, p)
            n_doses = _inserir_doses_consolidado(cur, med_id, p.doses or [])
            stats["apres_inseridas"] += n_apres
            stats["doses_inseridas"] += n_doses

            acao = "ATUALIZAR" if existia else "CRIAR"
            log.info(
                f"  {acao} PA={p.principio_ativo!r} (med_id={med_id}) "
                f"+{n_apres} apres (fab={p.fabricante!r}) "
                f"+{n_doses} doses"
            )

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
    p.add_argument("--filtro-nome",    type=str, default=None,
                   help="Só processa produtos cujo nome (normalizado) contém esta substring. "
                        "Útil para testar um medicamento específico (ex: --filtro-nome prednisona).")
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

        # No modo consolidado não pulamos por nome: um produto "Prednisona Ligvet"
        # é válido mesmo que já exista "Prednisona" no DB — suas apresentações
        # e doses serão mergeadas no medicamento consolidado.
        COMMIT_EVERY = 25
        contador = {
            "scrapeados": 0, "medicamentos_novos": 0, "medicamentos_atualizados": 0,
            "apres_inseridas": 0, "doses_inseridas": 0, "falhas": 0,
        }

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.visible)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="pt-BR",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            log.info("Abrindo home para aceitar cookies…")
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            aguardar_e_aceitar_cookies(page, timeout=8000)
            time.sleep(1)

            lista = scrape_lista_produtos(page)
            if args.filtro_nome:
                alvo = _norm(args.filtro_nome)
                antes = len(lista)
                lista = [it for it in lista if alvo in _norm(it["nome"])]
                log.info(f"Filtro por nome {args.filtro_nome!r}: {antes} → {len(lista)} produtos.")
            if args.limite > 0:
                lista = lista[:args.limite]

            total = len(lista)
            for i, info in enumerate(lista, 1):
                log.info(f"[{i}/{total}] {info['nome']}")
                try:
                    prod = scrape_detalhe_produto(page, info)
                    contador["scrapeados"] += 1
                    log.info(
                        f"    ✓ PA={prod.principio_ativo!r} "
                        f"fab={prod.fabricante!r} "
                        f"apres={len(prod.apresentacoes)} "
                        f"doses={len(prod.doses)}"
                    )

                    # Consolidação por PA + merge de apresentações/doses
                    try:
                        with conn.cursor() as cur:
                            # Verifica se o PA já existia antes do upsert (pra contabilizar)
                            pa_norm = _norm(prod.principio_ativo or '')
                            existia = False
                            if pa_norm:
                                cur.execute("""
                                    SELECT 1 FROM medicamento
                                     WHERE LOWER(REGEXP_REPLACE(
                                             TRANSLATE(principio_ativo,
                                                       'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                                                       'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'),
                                             '\\s+', ' ', 'g')) = %s
                                     LIMIT 1
                                """, (pa_norm,))
                                existia = cur.fetchone() is not None

                            med_id = _encontrar_ou_criar_medicamento_por_pa(cur, prod)
                            n_apres = _inserir_apresentacoes_consolidado(cur, med_id, prod)
                            n_doses = _inserir_doses_consolidado(cur, med_id, prod.doses or [])

                            if existia:
                                contador["medicamentos_atualizados"] += 1
                            else:
                                contador["medicamentos_novos"] += 1
                            contador["apres_inseridas"] += n_apres
                            contador["doses_inseridas"] += n_doses
                            log.info(f"    → med_id={med_id} +{n_apres}ap +{n_doses}doses")
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
                    log.info(
                        f"  ↳ commit ("
                        f"{contador['medicamentos_novos']} novos, "
                        f"{contador['medicamentos_atualizados']} atualizados, "
                        f"{contador['apres_inseridas']} apres, "
                        f"{contador['doses_inseridas']} doses, "
                        f"{contador['falhas']} falhas)"
                    )

            conn.commit()  # commit final
            browser.close()

        conn.close()
        print(f"""
{'='*65}
  RESULTADO (modo streaming — consolidado por PA)
{'='*65}
  Total na lista:        {total}
  Scrapeados:            {contador['scrapeados']}
  Medicamentos novos:    {contador['medicamentos_novos']}
  Medicamentos updtd:    {contador['medicamentos_atualizados']}
  Apresentações inser.:  {contador['apres_inseridas']}
  Doses inseridas:       {contador['doses_inseridas']}
  Falhas:                {contador['falhas']}
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
            for campo_novo in ['fabricante', 'especies', 'indicacoes', 'interacoes', 'farmacologia', 'conteudo_estruturado']:
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
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            aguardar_e_aceitar_cookies(page, timeout=8000)
            time.sleep(1)

            lista = scrape_lista_produtos(page)
            if args.filtro_nome:
                alvo = _norm(args.filtro_nome)
                antes = len(lista)
                lista = [it for it in lista if alvo in _norm(it["nome"])]
                log.info(f"Filtro por nome {args.filtro_nome!r}: {antes} → {len(lista)} produtos.")
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
                        for campo_novo in ['fabricante', 'especies', 'indicacoes', 'interacoes', 'farmacologia', 'conteudo_estruturado']:
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
                        "conteudo_estruturado": pp.conteudo_estruturado,
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
  RESULTADO (cache → consolidado por PA)
{'='*65}
  Banco (antes):          {len(medicamentos_banco)}
  Produtos scrapeados:    {len(produtos)}
  Medicamentos novos:     {stats['novos_medicamentos']}
  Medicamentos updtd:     {stats['medicamentos_atualizados']}
  Apresentações inser.:   {stats['apres_inseridas']}
  Doses inseridas:        {stats['doses_inseridas']}
  Dry-run:                {'SIM' if args.dry_run else 'NÃO'}
{'='*65}
""")


if __name__ == "__main__":
    main()
