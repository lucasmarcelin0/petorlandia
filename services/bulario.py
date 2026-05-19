"""Serviço de sugestão de dose a partir do bulário.

Usado pelo endpoint /api/bulario/sugerir-dose e por qualquer outro caller
que precise propor uma dose para um animal específico.
"""
from __future__ import annotations
import os
import re
import importlib.util
import unicodedata
from typing import Optional, Dict, Any, List, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

# Normalizador de posologia carregado relativo a este arquivo — funciona tanto
# importado como pacote (services.bulario) quanto carregado standalone via
# importlib (como fazem os testes), sem disparar services/__init__.py.
_pn_spec = importlib.util.spec_from_file_location(
    "posologia_normalizacao",
    os.path.join(os.path.dirname(__file__), "posologia_normalizacao.py"),
)
_pn = importlib.util.module_from_spec(_pn_spec)
_pn_spec.loader.exec_module(_pn)
normalizar_frequencia = _pn.normalizar_frequencia
normalizar_duracao = _pn.normalizar_duracao
consolidar_linhas = _pn.consolidar_linhas


def _strip_accents(s: str) -> str:
    """Remove acentos: 'Antibiótico' → 'Antibiotico'. Assim os regex dos
    macro-grupos podem usar ASCII simples sem lidar com cada variante."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ──────────────────────────────────────────────────────────────────────────
# Macro-grupos de classificação farmacológica
# ──────────────────────────────────────────────────────────────────────────
# Razão: o bulário tem >170 classificações distintas vindas da VetSmart —
# e.g. "Vacina V10", "Vacina V8", "Vacina Antirrábica" contam como 3. Para o
# veterinário isso vira um seletor inutilizável. Agrupamos em 10 macros
# clínicos e deixamos a UI fazer drill-down.
#
# Cada macro tem regex patterns (case-insensitive, sem acento). A primeira
# correspondência vence — ordem importa. O macro "Outros" é catch-all.
#
# Como adicionar uma classe nova: veja se algum pattern existente já pega
# (muitas vezes sim). Se não, acrescente ao macro mais clínico-próximo.
MACRO_GRUPOS: List[Dict[str, Any]] = [
    {
        "key": "antimicrobiano",
        "label": "Antimicrobiano",
        "icon": "fa-bacteria",
        "patterns": [
            r"antibi", r"antibact", r"antimicrobia", r"antifung",
            r"antiviral", r"antivira", r"antissep", r"antisep",
            r"sulf", r"quinolon", r"cefalospor", r"penicil", r"macrolid",
            r"tetracicl", r"aminoglic", r"nitroimida",
        ],
    },
    {
        "key": "antiparasitario",
        "label": "Antiparasitário",
        "icon": "fa-bug",
        "patterns": [
            r"antiparas", r"endectoc", r"ectoparas", r"endoparas",
            r"carrapatic", r"pulguicid", r"vermifug", r"verm[ií]fug",
            r"anti[- ]?helm[ií]nt", r"leishmanic", r"giardic",
            r"coccidios", r"acaricid", r"inseticid",
        ],
    },
    {
        "key": "anti_inflamatorio",
        "label": "Anti-inflamatório / Analgésico",
        "icon": "fa-fire-flame-curved",
        "patterns": [
            r"anti[- ]?inflamat", r"antiinflamat", r"aine",
            r"analg[eé]s", r"opioid", r"antip[ií]r[ée]t",
            r"esteroid", r"corticoster", r"glucocortic",
        ],
    },
    {
        "key": "vacina",
        "label": "Vacina / Imunobiológico",
        "icon": "fa-syringe",
        "patterns": [
            r"vacina", r"imunobio", r"imuno[- ]?modul",
            r"\bsoro\b", r"antitet[aâ]n", r"antirrab", r"antirr[áa]b",
        ],
    },
    {
        "key": "cardiovascular",
        "label": "Cardiovascular / Renal",
        "icon": "fa-heart-pulse",
        "patterns": [
            r"cardiot[oô]n", r"cardiova", r"cardiol",
            r"antiarr[ií]tm", r"anti[- ]?hipertens", r"antihipertens",
            r"diur[eé]t", r"vasodil", r"vasopress",
            r"ieca", r"bra\b", r"beta[- ]?bloq", r"nefro",
        ],
    },
    {
        "key": "endocrino",
        "label": "Endócrino / Hormonal",
        "icon": "fa-dna",
        "patterns": [
            r"horm[oô]n", r"insulin", r"antidiab[eé]t", r"hipoglic",
            r"tireoid", r"tiroxin", r"anticoncep", r"contracep",
            r"progester", r"estrog", r"androg",
        ],
    },
    {
        "key": "gastrointestinal",
        "label": "Gastrointestinal / Hepático",
        "icon": "fa-pills",
        "patterns": [
            r"antiem[eé]t", r"antidiarr", r"antiac", r"antiulc",
            r"procin[eé]t", r"laxat", r"hepatoprot", r"hepat",
            r"g[aá]stric", r"digest", r"pancre",
        ],
    },
    {
        "key": "respiratorio",
        "label": "Respiratório",
        "icon": "fa-lungs",
        "patterns": [
            r"broncodil", r"broncop", r"mucol[ií]t", r"expector",
            r"antituss", r"respir",
        ],
    },
    {
        "key": "snc",
        "label": "SNC / Comportamento / Anestesia",
        "icon": "fa-brain",
        "patterns": [
            r"anticonvul", r"antiepil", r"ansiol[ií]t", r"antidepress",
            r"sedat", r"anest[eé]s", r"tranquiliz", r"neurol[eé]pt",
            r"psicotr[oó]p", r"hipn[oó]t", r"relaxant[e ]*muscul",
        ],
    },
    # Catch-all: tópicos (derm/oftal/otol), suplementos, e qualquer
    # classificação sem match nos grupos anteriores.
    {
        "key": "outros",
        "label": "Tópicos / Suplementos / Outros",
        "icon": "fa-spray-can-sparkles",
        "patterns": [
            r"dermatol", r"oftalmol", r"otol[oó]g",
            r"cicatriz", r"suplem", r"vitamin", r"probiot", r"prebi[oó]t",
            r"fluidoter", r"nutric", r"t[oó]pic",
        ],
    },
]


def classificar_em_macro_grupo(classificacao: Optional[str]) -> str:
    """Retorna a `key` do macro-grupo que a classificação pertence.

    Se nenhum match específico acontecer, cai em "outros" (catch-all).
    Case e acentuação insensíveis: a string é normalizada (sem acentos e
    minúscula) antes de bater com os regex ASCII dos patterns.
    """
    if not classificacao:
        return "outros"
    alvo = _strip_accents(classificacao).lower()
    for grupo in MACRO_GRUPOS:
        for pat in grupo["patterns"]:
            if re.search(pat, alvo):
                return grupo["key"]
    return "outros"


# ──────────────────────────────────────────────────────────────────────────
# Durações padrão por classe farmacológica
# ──────────────────────────────────────────────────────────────────────────
# Ordem importa: padrões mais específicos primeiro.
# Cada tupla: (regex_na_classificacao, min_dias, max_dias, descricao_curta)
# Regex testado contra a classificação sem acentos e em minúscula.
_DURACAO_PADRAO: List[Tuple[str, int, int, str]] = [
    # Antiparasitários — maioria dose única ou curtíssimo
    (r'vermifug|anti[- ]?helmint',                   1,   1, 'dose única'),
    (r'ectoparas|endoparas|endectoc|carrapatic|acaricid|pulguicid', 1, 3, 'dose única a curto prazo'),
    # Antifúngicos — curso mais longo que antibacterianos
    (r'antifung',                                    14,  30, 'curso antifúngico'),
    # Antibacterianos / Antimicrobianos
    (r'antibi|antibact|antimicrobia|antissep|antisep', 7, 14, 'curso antibiótico padrão'),
    # Anti-inflamatórios — distingue AINE de esteroides
    (r'nao.*ester|n.o.*ester|aine',                   3,   7, 'anti-inflamatório agudo'),
    (r'esteroid|corticoster|glicocortic',              5,  14, 'corticosteroide'),
    (r'analg|opioid',                                  3,   7, 'analgesia'),
    (r'anti[- ]?inflamat',                             3,   7, 'anti-inflamatório'),
    # SNC / Anestesia / Comportamento
    (r'anest[eé]s|sedat',                              1,   1, 'dose única — procedimento'),
    (r'relaxant.*muscul',                              3,   5, 'relaxamento muscular'),
    (r'anticonvul|antiepil',                          30,  90, 'controle epiléptico contínuo'),
    (r'antidepress|ansiol|tranquiliz|comportament',   30,  90, 'tratamento comportamental'),
    (r'neurolep|psicotr',                             30,  90, 'tratamento neurológico'),
    # Cardiovascular / Renal
    (r'inotr[oó]p|cardiot[oô]n|antiarr',             30,  90, 'tratamento cardíaco crônico'),
    (r'diur[eé]t',                                    14,  30, 'diurético'),
    (r'vasodil|vasopress',                            30,  90, 'suporte vascular'),
    # Endócrino
    (r'insulin|antidiab|hipoglic',                    30,  90, 'controle glicêmico contínuo'),
    (r'horm[oô]n|tireoid|tiroxin',                   30,  90, 'terapia hormonal contínua'),
    (r'anticoncep|contracep',                          30,  90, 'contracepção'),
    # Gastrointestinal / Hepático
    (r'antiem[eé]t|antinaus',                          3,   5, 'controle de êmese'),
    (r'antidiarr',                                     3,   7, 'controle de diarreia'),
    (r'hepatoprot|hepat',                             14,  30, 'hepatoproteção'),
    (r'antiulc|antiac|proteto.*gastric|g[aá]stric',  14,  28, 'proteção gástrica'),
    (r'probiot|prebi[oó]t',                           14,  30, 'probiótico'),
    (r'laxat|procin[eé]t',                             3,   7, 'motilidade gastrointestinal'),
    # Respiratório
    (r'broncodil|broncop',                             7,  14, 'broncodilatação'),
    (r'mucol[ií]t|expector|antituss',                  5,  10, 'manejo respiratório'),
    # Tópicos locais
    (r'otol[oó]g',                                     7,  14, 'tratamento otológico'),
    (r'oftalm|optalmol',                               7,  14, 'tratamento oftálmico'),
    (r'dermatol',                                      7,  21, 'tratamento dermatológico'),
    (r'cicatriz',                                      7,  14, 'cicatrização'),
    # Imunomoduladores
    (r'imunoestim|imunomodul',                        14,  30, 'imunoestimulação'),
    (r'antineoplas',                                   14,  30, 'oncológico — avaliar protocolo'),
    # Suplementos / Nutraceuticos (uso crônico)
    (r'suplem|nutrac|vitamin|regenerad|articular',    30,  90, 'suplementação contínua'),
]


def _duracao_padrao(medicamento) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Retorna (min_dias, max_dias, descricao) de referência para a classe
    do medicamento. Retorna (None, None, None) quando não há padrão aplicável."""
    cls = getattr(medicamento, 'classificacao', None) or ''
    alvo = _strip_accents(cls).lower()
    for pat, mn, mx, desc in _DURACAO_PADRAO:
        if re.search(pat, alvo):
            return (mn, mx, desc)
    return (None, None, None)


def _prescritor_vetsmart_stats(medicamento) -> Dict[str, Any]:
    conteudo = getattr(medicamento, 'conteudo_estruturado', None) or {}
    if not isinstance(conteudo, dict):
        return {}
    stats = conteudo.get('prescritor_vetsmart') or {}
    return stats if isinstance(stats, dict) else {}


def _produtos_vetsmart(medicamento) -> List[Dict[str, Any]]:
    conteudo = getattr(medicamento, 'conteudo_estruturado', None) or {}
    if not isinstance(conteudo, dict):
        return []
    produtos = conteudo.get('produtos_vetsmart') or []
    if not isinstance(produtos, list):
        return []
    return [p for p in produtos if isinstance(p, dict)]


def _resumir_produtos_vetsmart(medicamento) -> List[Dict[str, Any]]:
    saida: List[Dict[str, Any]] = []
    for prod in _produtos_vetsmart(medicamento):
        secoes = prod.get('secoes') if isinstance(prod.get('secoes'), dict) else {}
        apresentacoes = prod.get('apresentacoes') if isinstance(prod.get('apresentacoes'), list) else []
        doses = prod.get('doses') if isinstance(prod.get('doses'), list) else []
        saida.append({
            'vetsmart_produto_id': prod.get('vetsmart_produto_id'),
            'nome': prod.get('nome'),
            'tipo': prod.get('tipo') or 'produto',
            'fabricante': prod.get('fabricante'),
            'classificacao': prod.get('classificacao'),
            'especies': prod.get('especies'),
            'via_administracao': prod.get('via_administracao'),
            'frequencia': prod.get('frequencia'),
            'duracao_tratamento': prod.get('duracao_tratamento'),
            'observacoes': prod.get('observacoes'),
            'fonte': prod.get('fonte'),
            'apresentacoes_count': len(apresentacoes),
            'doses_count': len(doses),
            'apresentacoes': [
                {
                    'forma': ap.get('forma'),
                    'concentracao': ap.get('concentracao'),
                    'concentracao_valor': ap.get('concentracao_valor'),
                    'concentracao_unidade': ap.get('concentracao_unidade'),
                }
                for ap in apresentacoes[:12]
                if isinstance(ap, dict)
            ],
            'secoes': {
                nome: {
                    'texto': (valor.get('texto') if isinstance(valor, dict) else None),
                    'html': _sanitizar_html_vetsmart(valor.get('html')) if isinstance(valor, dict) else None,
                }
                for nome, valor in secoes.items()
                if isinstance(valor, dict) and (valor.get('texto') or valor.get('html'))
            },
        })
    return saida


def _duracao_prescritor_vetsmart(medicamento) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    stats = _prescritor_vetsmart_stats(medicamento)
    try:
        mn = int(stats.get('duracao_min_dias')) if stats.get('duracao_min_dias') is not None else None
        mx = int(stats.get('duracao_max_dias')) if stats.get('duracao_max_dias') is not None else None
    except (TypeError, ValueError):
        return (None, None, None)
    if mn is None and mx is None:
        return (None, None, None)
    desc = stats.get('duracao_texto') or 'referencia do prescritor VetSmart'
    return (mn, mx, desc)


def _parse_duracao_dias(texto: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    if not texto:
        return (None, None)
    t = _strip_accents(str(texto)).lower()
    faixa = re.search(r'(\d{1,3})\s*(?:a|-|ate)\s*(\d{1,3})\s*dias?', t)
    if faixa:
        return (int(faixa.group(1)), int(faixa.group(2)))
    unico = re.search(r'(?:por|durante|continuidade por|usa-se de)?\s*(\d{1,3})\s*dias?', t)
    if unico:
        val = int(unico.group(1))
        return (val, val)
    semanas = re.search(r'(\d{1,2})\s*semanas?', t)
    if semanas:
        val = int(semanas.group(1)) * 7
        return (val, val)
    return (None, None)


def _duracao_produtos_vetsmart(medicamento) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    for prod in _produtos_vetsmart(medicamento):
        candidatos = [
            prod.get('duracao_tratamento'),
            ((prod.get('secoes') or {}).get('Duração do Tratamento') or {}).get('texto')
            if isinstance((prod.get('secoes') or {}).get('Duração do Tratamento'), dict) else None,
            ((prod.get('secoes') or {}).get('Administração e doses') or {}).get('texto')
            if isinstance((prod.get('secoes') or {}).get('Administração e doses'), dict) else None,
        ]
        for texto in candidatos:
            mn, mx = _parse_duracao_dias(texto)
            if mn is not None or mx is not None:
                nome = prod.get('nome') or 'VetSmart'
                return (mn, mx, f'painel clinico VetSmart: {nome}')
    return (None, None, None)


def _adicionar_flag_risco(
    flags: List[Dict[str, str]],
    *,
    codigo: str,
    nivel: str,
    titulo: str,
    detalhe: str,
) -> None:
    flags.append({
        'codigo': codigo,
        'nivel': nivel,
        'titulo': titulo,
        'detalhe': detalhe,
    })


def _resumo_origem_dose(proto, *, duracao_e_padrao: bool, proto_ind: Optional[str]) -> Dict[str, Any]:
    fonte = (getattr(proto, 'fonte', None) or 'SCRAPER').upper()
    confianca = (getattr(proto, 'confianca', None) or 'MEDIA').upper()

    base = {
        'fonte': fonte,
        'confianca': confianca,
        'tem_indicacao_explicita': bool((proto_ind or '').strip()),
        'usa_duracao_padrao': bool(duracao_e_padrao),
    }

    if fonte == 'SCRAPER':
        base.update({
            'tipo': 'fonte_primaria_estruturada',
            'rotulo': 'Dose estruturada do bulário',
            'detalhe': 'Sugestão calculada a partir de protocolo estruturado importado do bulário.',
        })
    elif fonte == 'LLM':
        base.update({
            'tipo': 'fonte_assistida',
            'rotulo': 'Dose estruturada com assistência automatizada',
            'detalhe': 'Protocolo estruturado com apoio automatizado; revisar antes de prescrever.',
        })
    else:
        base.update({
            'tipo': 'fonte_curada',
            'rotulo': 'Dose cadastrada manualmente',
            'detalhe': 'Protocolo estruturado manualmente na plataforma; confirmar aderência ao caso clínico.',
        })
    return base


def construir_macro_grupos(
    classes_db: List[str],
    classe_ativa: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Agrupa a lista crua de classificações em macro-grupos navegáveis.

    Retorna (grupos, key_ativa):
      - grupos: lista de dicts com {key, label, icon, subclasses[], count,
        is_active}. Só inclui macros que têm ao menos 1 subclasse.
      - key_ativa: qual macro contém a `classe_ativa` atual (para a UI abrir
        o drawer correto ao carregar a página). None se sem filtro.

    `classes_db` deve ser uma lista de strings distintas e já ordenadas
    alfabeticamente (como a query atual do endpoint /bulario já faz).
    """
    buckets: Dict[str, List[str]] = {g["key"]: [] for g in MACRO_GRUPOS}
    for cls in classes_db:
        if not cls:
            continue
        buckets[classificar_em_macro_grupo(cls)].append(cls)

    key_ativa: Optional[str] = None
    if classe_ativa:
        key_ativa = classificar_em_macro_grupo(classe_ativa)

    resultado: List[Dict[str, Any]] = []
    for g in MACRO_GRUPOS:
        subs = buckets[g["key"]]
        if not subs:
            continue
        resultado.append({
            "key":        g["key"],
            "label":      g["label"],
            "icon":       g["icon"],
            "subclasses": subs,
            "count":      len(subs),
            "is_active":  g["key"] == key_ativa,
        })
    return resultado, key_ativa


def _texto_limpo(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return texto or None


def _texto_multilinha_limpo(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    texto = str(valor).replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    texto = texto.strip()
    return texto or None


def _dedupe_itens(itens: List[str]) -> List[str]:
    vistos: set[str] = set()
    resultado: List[str] = []
    for item in itens:
        limpo = _texto_limpo(item)
        if not limpo:
            continue
        chave = _strip_accents(limpo).lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(limpo)
    return resultado


def _quebrar_em_itens(texto: Optional[str]) -> List[str]:
    bruto = _texto_multilinha_limpo(texto)
    if not bruto:
        return []
    candidato = bruto
    candidato = re.sub(r"\s*[•·●▪◦]\s*", "\n", candidato)
    candidato = re.sub(r"\s*;\s*", "\n", candidato)
    candidato = re.sub(r"\.\s+(?=[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ])", ".\n", candidato)
    partes = []
    for linha in candidato.split("\n"):
        linha = re.sub(r"^\s*[-–—]\s*", "", linha).strip(" .;-:")
        if len(linha) < 3:
            continue
        partes.append(linha)
    return _dedupe_itens(partes)


def _extrair_bloco_rotulado(texto: Optional[str], rotulos: List[str]) -> Optional[str]:
    bruto = _texto_multilinha_limpo(texto)
    if not bruto:
        return None

    marcadores = [
        "indicações/contraindicações",
        "indicações e contraindicações",
        "indicações",
        "contraindicações",
        "advertências",
        "precauções",
        "efeitos adversos",
        "reações adversas",
        "interações medicamentosas",
    ]
    norm = _strip_accents(bruto).lower()
    encontrados: List[Tuple[int, int, str]] = []
    for rotulo in rotulos:
        idx = norm.find(_strip_accents(rotulo).lower())
        if idx >= 0:
            encontrados.append((idx, idx + len(rotulo), rotulo))
    if not encontrados:
        return None

    encontrados.sort(key=lambda item: item[0])
    inicio = encontrados[0][1]
    fim = len(bruto)
    for marcador in marcadores:
        idx = norm.find(_strip_accents(marcador).lower(), inicio)
        if idx >= 0:
            fim = min(fim, idx)
    trecho = bruto[inicio:fim].strip(" \n\r\t:-")
    return trecho or None


def _extrair_frases_por_palavra_chave(texto: Optional[str], palavras: List[str]) -> List[str]:
    bruto = _texto_multilinha_limpo(texto)
    if not bruto:
        return []
    frases = re.split(r"(?<=[\.;])\s+|\n+", bruto)
    saida = []
    for frase in frases:
        frase_limpa = _texto_limpo(frase)
        if not frase_limpa:
            continue
        alvo = _strip_accents(frase_limpa).lower()
        if any(p in alvo for p in palavras):
            saida.append(frase_limpa.strip(" .;"))
    return _dedupe_itens(saida)


def _inferir_grau_interacao(texto: str) -> str:
    alvo = _strip_accents(texto).lower()
    if any(token in alvo for token in ["contraindicado", "evitar associacao", "nao associar", "grave", "severa"]):
        return "Alta"
    if any(token in alvo for token in ["cautela", "monitorar", "ajustar dose", "moderad"]):
        return "Moderada"
    if any(token in alvo for token in ["leve", "discreta", "pouco relevante"]):
        return "Baixa"
    return "Atenção"


def _inferir_conduta_interacao(texto: str) -> str:
    alvo = _strip_accents(texto).lower()
    if any(token in alvo for token in ["contraindicado", "nao associar", "evitar associacao"]):
        return "Evitar associação"
    if "ajust" in alvo:
        return "Ajustar dose"
    if any(token in alvo for token in ["monitor", "acompanhar", "vigiar"]):
        return "Monitorar de perto"
    if "cautela" in alvo:
        return "Usar com cautela"
    return "Avaliar clinicamente"


def _parsear_interacoes_estruturadas(texto: Optional[str]) -> List[Dict[str, str]]:
    itens = _quebrar_em_itens(texto)
    resultado: List[Dict[str, str]] = []
    for item in itens:
        agente = item
        match = re.match(r"^(.*?)(?:\s*[-:]\s*|\s+)(aumenta|reduz|potencializa|pode|deve|evitar|contraindicado)", item, re.IGNORECASE)
        if match:
            agente = match.group(1).strip(" -:")
        elif ":" in item:
            agente = item.split(":", 1)[0].strip(" -:")
        elif " com " in item.lower():
            agente = item.split(" com ", 1)[0].strip(" -:")
        resultado.append({
            "agente": agente[:120],
            "grau": _inferir_grau_interacao(item),
            "conduta": _inferir_conduta_interacao(item),
            "descricao": item,
        })
    return resultado


def _montar_secao_textual(itens: List[str], texto: Optional[str], resumo: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "itens": _dedupe_itens(itens),
        "texto": _texto_multilinha_limpo(texto),
        "resumo": _dedupe_itens(resumo or []),
    }


def _itens_legados_de_conteudo(valor: Any) -> List[Any]:
    if isinstance(valor, dict):
        itens = valor.get("itens")
        return itens if isinstance(itens, list) else []
    if isinstance(valor, list):
        return valor
    return []


def _conteudo_carregado_sem_lazyload(medicamento) -> Dict[str, Any]:
    conteudo = getattr(medicamento, "__dict__", {}).get("conteudo_estruturado") or {}
    if not isinstance(conteudo, dict):
        return {}
    return conteudo


def _normalizar_secao_estruturada(secao: Any, *, permitir_resumo: bool = True) -> Dict[str, Any]:
    if not isinstance(secao, dict):
        secao = {}
    itens = secao.get("itens")
    if not isinstance(itens, list):
        itens = []
    resumo = secao.get("resumo") if permitir_resumo else []
    if not isinstance(resumo, list):
        resumo = []
    return {
        "itens": _dedupe_itens([str(item) for item in itens if _texto_limpo(str(item))]),
        "texto": _texto_multilinha_limpo(secao.get("texto")),
        "resumo": _dedupe_itens([str(item) for item in resumo if _texto_limpo(str(item))]),
    }


def _normalizar_interacoes_estruturadas(secao: Any) -> Dict[str, Any]:
    if not isinstance(secao, dict):
        secao = {}
    itens_brutos = secao.get("itens")
    if not isinstance(itens_brutos, list):
        itens_brutos = []
    itens: List[Dict[str, str]] = []
    for item in itens_brutos:
        if not isinstance(item, dict):
            continue
        descricao = _texto_limpo(item.get("descricao"))
        agente = _texto_limpo(item.get("agente")) or descricao
        if not descricao or not agente:
            continue
        itens.append({
            "agente": agente[:120],
            "grau": _texto_limpo(item.get("grau")) or _inferir_grau_interacao(descricao),
            "conduta": _texto_limpo(item.get("conduta")) or _inferir_conduta_interacao(descricao),
            "descricao": descricao,
        })
    return {
        "itens": itens,
        "texto": _texto_multilinha_limpo(secao.get("texto")),
    }


def _conteudo_estruturado_do_scraper(medicamento) -> Optional[Dict[str, Any]]:
    conteudo = _conteudo_carregado_sem_lazyload(medicamento)
    metadata = conteudo.get("metadata") if isinstance(conteudo, dict) else None
    parser_version = metadata.get("parser_version") if isinstance(metadata, dict) else None
    if not parser_version:
        return None
    contra = _normalizar_secao_estruturada(conteudo.get("contraindicacoes"))
    if not contra["resumo"]:
        contra["resumo"] = contra["itens"][:3]
    return {
        "indicacoes": _normalizar_secao_estruturada(conteudo.get("indicacoes")),
        "contraindicacoes": contra,
        "efeitos_adversos": _normalizar_secao_estruturada(conteudo.get("efeitos_adversos")),
        "advertencias": _normalizar_secao_estruturada(conteudo.get("advertencias")),
        "interacoes": _normalizar_interacoes_estruturadas(conteudo.get("interacoes")),
        "metadata": {
            "parser_version": parser_version,
            "fonte": metadata.get("fonte") if isinstance(metadata, dict) else None,
        },
    }


def _fallback_conteudo_estruturado(medicamento) -> Dict[str, Any]:
    observacoes = _texto_multilinha_limpo(getattr(medicamento, "observacoes", None))
    conteudo = _conteudo_carregado_sem_lazyload(medicamento)

    indicacoes_texto = (
        _extrair_bloco_rotulado(observacoes, ["Indicações/Contraindicações", "Indicações e contraindicações", "Indicações"])
        or conteudo.get("indicacoes_texto")
    )
    contra_texto = (
        _extrair_bloco_rotulado(observacoes, ["Contraindicações"])
        or conteudo.get("contraindicacoes_texto")
    )
    advertencias_texto = (
        _extrair_bloco_rotulado(observacoes, ["Advertências", "Precauções"])
        or conteudo.get("advertencias_texto")
    )
    efeitos_texto = (
        _extrair_bloco_rotulado(observacoes, ["Efeitos adversos", "Reações adversas"])
        or conteudo.get("efeitos_adversos_texto")
    )
    interacoes_texto = (
        _extrair_bloco_rotulado(observacoes, ["Interações medicamentosas"])
        or conteudo.get("interacoes_texto")
    )

    indicacoes_itens = _itens_legados_de_conteudo(conteudo.get("indicacoes")) or _quebrar_em_itens(indicacoes_texto)
    contra_items = _itens_legados_de_conteudo(conteudo.get("contraindicacoes")) or _quebrar_em_itens(contra_texto)
    if not contra_items:
        contra_items = _extrair_frases_por_palavra_chave(
            " ".join(filter(None, [contra_texto, indicacoes_texto, advertencias_texto])),
            ["contraindic", "nao usar", "nao administrar", "evitar", "hipersens", "gesta", "lacta"],
        )
    efeitos_itens = _itens_legados_de_conteudo(conteudo.get("efeitos_adversos")) or _quebrar_em_itens(efeitos_texto)
    advertencias_itens = _itens_legados_de_conteudo(conteudo.get("advertencias")) or _quebrar_em_itens(advertencias_texto)
    interacoes_brutas = conteudo.get("interacoes")
    interacoes_itens = (
        interacoes_brutas.get("itens") if isinstance(interacoes_brutas, dict)
        else interacoes_brutas if isinstance(interacoes_brutas, list)
        else None
    ) or _parsear_interacoes_estruturadas(interacoes_texto)

    destaques = conteudo.get("contraindicacoes_destaque", []) or contra_items[:3]

    return {
        "indicacoes": _montar_secao_textual(indicacoes_itens, indicacoes_texto),
        "contraindicacoes": _montar_secao_textual(contra_items, contra_texto, resumo=destaques),
        "efeitos_adversos": _montar_secao_textual(efeitos_itens, efeitos_texto),
        "advertencias": _montar_secao_textual(advertencias_itens, advertencias_texto),
        "interacoes": {
            "itens": interacoes_itens,
            "texto": _texto_multilinha_limpo(interacoes_texto),
        },
        "metadata": {
            "parser_version": "legacy-fallback-v1",
            "fonte": "observacoes",
        },
    }


def construir_conteudo_estruturado(
    *,
    indicacoes: Optional[str] = None,
    interacoes: Optional[str] = None,
    advertencias: Optional[str] = None,
    observacoes: Optional[str] = None,
) -> Dict[str, Any]:
    class _Fake:
        conteudo_estruturado = {}

        def __init__(self):
            self.observacoes = observacoes

    fake = _Fake()
    base = _fallback_conteudo_estruturado(fake)
    if indicacoes:
        base["indicacoes"] = _montar_secao_textual(
            _quebrar_em_itens(indicacoes),
            indicacoes,
        )
    if interacoes:
        base["interacoes"] = {
            "itens": _parsear_interacoes_estruturadas(interacoes),
            "texto": _texto_multilinha_limpo(interacoes),
        }
    if advertencias:
        base["advertencias"] = _montar_secao_textual(
            _quebrar_em_itens(advertencias),
            advertencias,
        )
        if not base["contraindicacoes"]["itens"]:
            inferidas = _extrair_frases_por_palavra_chave(
                advertencias,
                ["contraindic", "nao usar", "nao administrar", "evitar", "hipersens"],
            )
            base["contraindicacoes"] = _montar_secao_textual(inferidas, None, resumo=inferidas[:3])
    return base


def _dose_combina_com_especie(dose, alvo: str) -> bool:
    especie_code = getattr(dose, "especie_code", None)
    especie = _strip_accents(getattr(dose, "especie", "") or "").lower()
    if alvo == "caes":
        if especie_code in {"CAES", "AMBOS"}:
            return True
        if especie_code == "GATOS":
            return False
        return ("cao" in especie) or ("caes" in especie) or ("can" in especie) or ("ambos" in especie)
    if alvo == "gatos":
        if especie_code in {"GATOS", "AMBOS"}:
            return True
        if especie_code == "CAES":
            return False
        return ("gato" in especie) or ("gatos" in especie) or ("felin" in especie) or ("ambos" in especie)
    return True


def _apresentacoes_solidas_com_forca(medicamento) -> List[tuple[float, str]]:
    resultado: List[tuple[float, str]] = []
    vistos: set[tuple[float, str]] = set()
    for ap in (getattr(medicamento, 'apresentacoes', []) or []):
        valor = getattr(ap, 'concentracao_valor', None)
        unidade = (getattr(ap, 'concentracao_unidade', None) or '').lower()
        forma = _texto_norm(getattr(ap, 'forma', None))
        if valor is None or not unidade:
            continue
        if unidade in {'mg/ml', 'mcg/ml'}:
            continue
        if any(token in forma for token in ('suspens', 'solucao', 'xarope', 'colirio', 'gota', 'spray', 'gel', 'pomada', 'creme', 'pasta', 'locao')):
            continue
        chave = (float(valor), unidade)
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(chave)
    return resultado


def _dose_texto_tem_forca_explicita(dose) -> bool:
    textos = [
        getattr(dose, 'dose', None),
        getattr(dose, 'dose_raw_text', None),
        getattr(dose, 'observacao', None),
    ]
    for texto in textos:
        norm = _texto_norm(texto)
        if not norm:
            continue
        if re.search(r'\b\d+(?:[.,]\d+)?\s*(mg|mcg|g|ui)\b', norm):
            return True
    return False


def _dose_ambigua_por_apresentacao(medicamento, dose) -> bool:
    unidade = (getattr(dose, 'dose_unidade', None) or '').upper()
    if unidade not in {'COMPRIMIDOS_ANIMAL', 'COMPRIMIDOS_KG'}:
        return False
    if _dose_texto_tem_forca_explicita(dose):
        return False
    return len(_apresentacoes_solidas_com_forca(medicamento)) > 1


def construir_posologia_por_especie(medicamento) -> List[Dict[str, Any]]:
    doses = [
        d for d in (getattr(medicamento, "doses", []) or [])
        if not _dose_ambigua_por_apresentacao(medicamento, d)
    ]
    tabs: List[Dict[str, Any]] = []
    for slug, label, icon in [
        ("caes", "Cães", "fa-dog"),
        ("gatos", "Gatos", "fa-cat"),
    ]:
        linhas = [d for d in doses if _dose_combina_com_especie(d, slug)]
        if not linhas:
            continue
        grupos: Dict[str, List[Any]] = {}
        for dose in linhas:
            chave = _texto_limpo(getattr(dose, "indicacao", None)) or "Uso geral"
            grupos.setdefault(chave, []).append(dose)
        chaves_exibidas = list(grupos.keys())
        if _eh_corticoide_medicamento(medicamento):
            especificas = [c for c in chaves_exibidas if c not in _INDICACOES_GENERICAS_CORTICOIDE]
            if especificas:
                chaves_exibidas = [c for c in chaves_exibidas if c not in _INDICACOES_GENERICAS_CORTICOIDE]
        med_freq = normalizar_frequencia(getattr(medicamento, "frequencia", None))
        med_dur = normalizar_duracao(getattr(medicamento, "duracao_tratamento", None))
        protocolos = []
        for indicacao in chaves_exibidas:
            itens = grupos[indicacao]
            linhas_norm = []
            for d in itens:
                freq = (
                    normalizar_frequencia(
                        getattr(d, "frequencia", None),
                        getattr(d, "intervalo_min_horas", None) or getattr(d, "intervalo_horas", None),
                        getattr(d, "intervalo_max_horas", None),
                    )
                    or med_freq
                    or "Conforme orientação veterinária"
                )
                dur = (
                    normalizar_duracao(getattr(d, "duracao", None))
                    or med_dur
                    or "Conforme orientação veterinária"
                )
                linhas_norm.append({
                    "faixa_peso": _texto_limpo(getattr(d, "faixa_peso", None)) or "Sem faixa definida",
                    "via": _texto_limpo(getattr(d, "via", None)) or _texto_limpo(getattr(medicamento, "via_administracao", None)) or "—",
                    "dose": _texto_limpo(getattr(d, "dose", None)) or "—",
                    "frequencia": freq,
                    "duracao": dur,
                    "observacao": _texto_limpo(getattr(d, "observacao", None)),
                })
            linhas_dedup = consolidar_linhas(linhas_norm)
            if not linhas_dedup:
                continue
            protocolos.append({
                "indicacao": indicacao,
                "linhas": linhas_dedup,
            })
        tabs.append({
            "slug": slug,
            "label": label,
            "icon": icon,
            "protocolos": protocolos,
        })
    return tabs


def montar_monografia_medicamento(medicamento) -> Dict[str, Any]:
    secoes = _conteudo_estruturado_do_scraper(medicamento) or _fallback_conteudo_estruturado(medicamento)
    posologia_tabs = construir_posologia_por_especie(medicamento)
    produtos_vetsmart = _resumir_produtos_vetsmart(medicamento)
    return {
        "resumo_posologia": {
            "dose": _texto_limpo(getattr(medicamento, "dosagem_recomendada", None)),
            "frequencia": _texto_limpo(getattr(medicamento, "frequencia", None)),
            "duracao": _texto_limpo(getattr(medicamento, "duracao_tratamento", None)),
            "tabs": posologia_tabs,
        },
        "secoes": secoes,
        "produtos_vetsmart": produtos_vetsmart,
        "tem_conteudo_clinico": any([
            secoes["indicacoes"]["itens"],
            secoes["contraindicacoes"]["itens"],
            secoes["efeitos_adversos"]["itens"],
            secoes["advertencias"]["itens"],
            secoes["interacoes"]["itens"],
            produtos_vetsmart,
        ]),
    }


def vetsmart_url(medicamento) -> Optional[str]:
    vid = getattr(medicamento, "vetsmart_produto_id", None)
    return f"https://vetsmart.com.br/cg/produto/{vid}" if vid else None


_SECOES_ORDEM_VETSMART = [
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

_ICONES_SECOES_VETSMART = {
    'Sobre':                         'fa-circle-info',
    'Apresentações e concentrações':  'fa-box-open',
    'Indicações e contraindicações':  'fa-stethoscope',
    'Administração e doses':          'fa-syringe',
    'Interações medicamentosas':      'fa-shuffle',
    'Farmacologia':                   'fa-flask',
    'Estudos':                        'fa-book-open',
    'Videos':                         'fa-play-circle',
    'Avaliações':                     'fa-star',
    'Distribuidores':                 'fa-truck',
    'Ref. bibliográficas':            'fa-bookmark',
}

_TAGS_PERMITIDAS_VETSMART = {
    'p', 'ul', 'ol', 'li', 'strong', 'b', 'em', 'i', 'br',
    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'span', 'div',
    'h2', 'h3', 'h4',
}


def _sanitizar_html_vetsmart(html: Optional[str]) -> Optional[str]:
    if not html or BeautifulSoup is None:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(True):
        nome = (tag.name or '').lower()
        if nome in {'script', 'style', 'iframe', 'form', 'input', 'button', 'svg'}:
            tag.decompose()
            continue
        if nome not in _TAGS_PERMITIDAS_VETSMART:
            tag.unwrap()
            continue

        attrs_permitidos: Dict[str, str] = {}
        if nome == 'a':
            href = (tag.get('href') or '').strip()
            if href.startswith('http://') or href.startswith('https://'):
                attrs_permitidos['href'] = href
                attrs_permitidos['target'] = '_blank'
                attrs_permitidos['rel'] = 'noopener noreferrer'
        tag.attrs = attrs_permitidos
    saida = soup.decode().strip()
    return saida or None


def extrair_secoes_vetsmart(medicamento) -> List[Dict[str, Any]]:
    """Retorna lista ordenada das seções brutas do Vetsmart gravadas no banco.

    Cada item: {nome, icone, texto, html}. Retorna [] se não houver raw_sections.
    """
    conteudo = _conteudo_carregado_sem_lazyload(medicamento)
    raw = conteudo.get("raw_sections") if isinstance(conteudo, dict) else None
    raw_html = conteudo.get("raw_sections_html") if isinstance(conteudo, dict) else None
    if not isinstance(raw, dict) or not raw:
        return []
    resultado = []
    for nome in _SECOES_ORDEM_VETSMART:
        texto = raw.get(nome)
        if texto:
            resultado.append({
                "nome": nome,
                "icone": _ICONES_SECOES_VETSMART.get(nome, "fa-circle"),
                "texto": texto,
                "html": _sanitizar_html_vetsmart(raw_html.get(nome)) if isinstance(raw_html, dict) else None,
            })
    return resultado


def serializar_medicamento_busca(medicamento) -> Dict[str, Any]:
    estrutura = montar_monografia_medicamento(medicamento)
    bula_url = vetsmart_url(medicamento)
    return {
        "id": medicamento.id,
        "nome": medicamento.nome,
        "classificacao": getattr(medicamento, "classificacao", None),
        "principio_ativo": getattr(medicamento, "principio_ativo", None),
        "via_administracao": getattr(medicamento, "via_administracao", None),
        "dosagem_recomendada": getattr(medicamento, "dosagem_recomendada", None),
        "frequencia": getattr(medicamento, "frequencia", None),
        "duracao_tratamento": getattr(medicamento, "duracao_tratamento", None),
        "observacoes": getattr(medicamento, "observacoes", None),
        "bula": getattr(medicamento, "bula", None),
        "bula_url": bula_url,
        "monografia_estruturada": estrutura,
    }


_UNIDADE_PRATICA_POR_FORMA = {
    # Orais sólidas
    'capsula': 'cápsula', 'capsulas': 'cápsula',
    'comprimido': 'comprimido', 'comprimidos': 'comprimido',
    'comprimido revestido': 'comprimido', 'drágea': 'drágea', 'dragea': 'drágea',
    'petisco': 'petisco', 'petiscos': 'petisco',
    'tablete': 'tablete', 'tabletes': 'tablete',

    # Orais líquidas
    'suspensao': 'mL', 'suspensao oral': 'mL',
    'solucao oral': 'mL', 'solução oral': 'mL',
    'xarope': 'mL', 'elixir': 'mL', 'liquido': 'mL', 'líquido': 'mL',
    'emulsao': 'mL', 'emulsão': 'mL',
    'gotas': 'gota', 'gota': 'gota',

    # Pasta
    'pasta oral': 'aplicação', 'pasta': 'aplicação',

    # Injetáveis
    'solucao injetavel': 'mL', 'solução injetável': 'mL', 'injetavel': 'mL', 'injetável': 'mL',

    # Tópicos
    'pomada': 'aplicação', 'creme': 'aplicação', 'gel': 'aplicação',
    'spray': 'aplicação', 'loção': 'aplicação', 'locao': 'aplicação',
    'shampoo': 'aplicação', 'xampu': 'aplicação',
    'pipeta': 'pipeta', 'pipetas': 'pipeta',

    # Retais
    'supositorio': 'supositório', 'supositório': 'supositório',
    'enema': 'aplicação',

    # Oftálmicos / óticos
    'colirio': 'gota', 'colírio': 'gota',
    'otologico': 'gota', 'otológico': 'gota',
}


_FORMAS_EMBALAGEM_COMPRIMIDO = (
    'cartucho', 'blister', 'blíster', 'display', 'caixa', 'cartela',
)

_FABRICANTE_MANIPULADO = (
    'manipul', 'farmacia', 'ligvet', 'animalia farma', 'animaliapharma',
    'formula animal',
)


def _forma_categoria_apresentacao_servico(forma: Optional[str], concentracao: Optional[str] = None) -> Tuple[str, str]:
    texto = _texto_norm(f"{forma or ''} {concentracao or ''}")
    if any(k in texto for k in ('colirio', 'oftalm')):
        return ('oftalmico', 'Oftalmicos')
    if any(k in texto for k in ('otolog', 'auric', 'ouvido')):
        return ('otico', 'Oticos')
    if any(k in texto for k in ('injet', 'ampola', 'frasco ampola', 'frasco-ampola')):
        return ('injetavel', 'Injetaveis')
    if any(k in texto for k in ('pomada', 'creme', 'gel', 'spray', 'locao', 'shampoo', 'xampu')):
        return ('topico', 'Topicos')
    if 'suspens' in texto:
        return ('suspensao_oral', 'Suspensoes orais')
    if any(k in texto for k in ('solucao', 'xarope', 'elixir', 'emuls', 'liquido', 'gota')):
        return ('liquido_oral', 'Liquidos orais')
    if any(k in texto for k in ('comprim', 'capsul', 'tablete', 'drage', 'petisco', 'biscoito', 'cartucho', 'blister', 'display', 'caixa', 'cartela')):
        return ('solido_oral', 'Comprimidos e capsulas')
    return ('outros', 'Outras apresentacoes')


def _tipo_origem_apresentacao(fabricante: Optional[str]) -> str:
    texto = _texto_norm(fabricante)
    return 'manipulado' if any(k in texto for k in _FABRICANTE_MANIPULADO) else 'comercial'


def _chave_visual_apresentacao(ap_info: Dict[str, Any]) -> tuple:
    valor = ap_info.get('concentracao_valor')
    try:
        valor_key = round(float(valor), 4) if valor is not None else None
    except (TypeError, ValueError):
        valor_key = None
    return (
        ap_info.get('categoria') or '',
        valor_key,
        (ap_info.get('concentracao_unidade') or '').lower(),
        (ap_info.get('unidade_pratica') or '').lower(),
        ap_info.get('tipo_origem') or '',
    )


def _ordenar_apresentacao_info(ap_info: Dict[str, Any]) -> tuple:
    ordem_cat = {
        'solido_oral': 0,
        'suspensao_oral': 1,
        'liquido_oral': 2,
        'injetavel': 3,
        'oftalmico': 4,
        'otico': 5,
        'topico': 6,
        'outros': 7,
    }
    tipo_score = 1 if ap_info.get('tipo_origem') == 'manipulado' else 0
    valor = ap_info.get('concentracao_valor')
    valor_score = float(valor) if valor is not None else 999999.0
    return (
        ordem_cat.get(ap_info.get('categoria'), 99),
        tipo_score,
        valor_score,
        ap_info.get('forma') or '',
        ap_info.get('fabricante') or '',
    )


def _unidade_pratica_por_forma(forma: Optional[str]) -> str:
    """Mapeia a forma farmacêutica ('Cápsulas', 'Suspensão', ...) para a
    unidade que o tutor vai usar na administração ('cápsula', 'mL', 'gota').

    Quando não reconhece, devolve 'unidade' como fallback seguro.
    """
    if not forma:
        return 'unidade'
    chave = forma.strip().lower()
    chave = chave.replace('ç', 'c').replace('ã', 'a').replace('á', 'a') \
                 .replace('é', 'e').replace('í', 'i').replace('ó', 'o') \
                 .replace('ú', 'u').replace('ô', 'o').replace('ê', 'e')
    resultado = _UNIDADE_PRATICA_POR_FORMA.get(chave)
    if resultado:
        return resultado
    # Embalagens de comprimido (cartucho, blíster, display, caixa) — o tutor
    # administra comprimidos, não a embalagem inteira.
    chave_norm = chave.replace('i', 'i').replace('e', 'e')  # já normalizado
    if any(emb in chave for emb in ('cartucho', 'blister', 'blister', 'display', 'caixa', 'cartela')):
        return 'comprimido'
    return 'unidade'


def _texto_norm(s: Optional[str]) -> str:
    return _strip_accents(s or '').lower().strip()


def _fmt_apresentacao_label(v: float) -> str:
    if v == int(v):
        return f"{int(v)}"
    return f"{v:.2f}".rstrip('0').rstrip('.').replace('.', ',')


def _extrair_faixa_peso_apresentacao(ap) -> Optional[str]:
    textos = [
        getattr(ap, 'nome_variante', None),
        getattr(ap, 'concentracao', None),
        getattr(ap, 'forma', None),
    ]
    for texto in textos:
        norm = _texto_norm(texto)
        if not norm:
            continue
        m = re.search(r'ate\s+(\d+(?:[.,]\d+)?)\s*kg', norm)
        if m:
            return f'até {m.group(1).replace(".", ",")} kg'
        m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:a|ate|-)\s*(\d+(?:[.,]\d+)?)\s*kg', norm)
        if m:
            ini = m.group(1).replace('.', ',')
            fim = m.group(2).replace('.', ',')
            return f'{ini} a {fim} kg'
        m = re.search(r'acima\s+de\s+(\d+(?:[.,]\d+)?)\s*kg', norm)
        if m:
            return f'acima de {m.group(1).replace(".", ",")} kg'
    return None


def _extrair_especie_apresentacao(ap) -> Optional[str]:
    textos = [
        getattr(ap, 'nome_variante', None),
        getattr(ap, 'concentracao', None),
        getattr(ap, 'forma', None),
    ]
    for texto in textos:
        norm = _texto_norm(texto)
        if not norm:
            continue
        if re.search(r'\bcae?s?\b|\bcaes\b|\bcachorr', norm):
            return 'Caes'
        if re.search(r'\bgat[oa]s?\b|\bfelin', norm):
            return 'Gatos'
    return None


def _montar_rotulo_apresentacao_escolha(ap) -> Dict[str, str]:
    faixa_peso = _extrair_faixa_peso_apresentacao(ap) or ''
    especie = _extrair_especie_apresentacao(ap) or ''

    if faixa_peso and especie:
        principal = f'{especie} {faixa_peso}'
    else:
        principal = faixa_peso or especie

    detalhes = []
    if getattr(ap, 'concentracao_valor', None):
        valor = _fmt_apresentacao_label(float(ap.concentracao_valor))
        unidade = getattr(ap, 'concentracao_unidade', None) or ''
        detalhes.append(f'{valor} {unidade}'.strip())
    elif getattr(ap, 'concentracao', None):
        detalhes.append(str(getattr(ap, 'concentracao')))

    forma = getattr(ap, 'forma', None) or ''
    if forma:
        detalhes.append(forma)

    secundario = ' '.join(p for p in detalhes if p).strip()
    return {
        'principal': principal,
        'secundario': secundario,
        'especie': especie,
    }


_INDICACAO_STOPWORDS = {
    'a', 'ao', 'aos', 'as', 'com', 'contra', 'da', 'das', 'de', 'do', 'dos',
    'e', 'em', 'na', 'nas', 'no', 'nos', 'o', 'os', 'ou', 'para', 'por',
    'uso',
}

_INDICACAO_SINONIMOS = (
    ('analges', {'analges', 'dor', 'pain'}),
    ('dor', {'analges', 'dor', 'pain'}),
    ('inflam', {'inflam', 'antiinflam'}),
    ('infect', {'infect', 'bacter', 'microb', 'antibiot'}),
    ('bacter', {'infect', 'bacter', 'microb', 'antibiot'}),
    ('parasit', {'paras', 'parasit', 'pulga', 'ecto', 'verme'}),
    ('pulga', {'paras', 'parasit', 'pulga', 'ecto'}),
    ('ecto', {'paras', 'parasit', 'pulga', 'ecto'}),
    ('topic', {'topic', 'topico', 'cutan', 'dermat', 'ferida', 'lesao', 'cicatriz'}),
    ('topico', {'topic', 'topico', 'cutan', 'dermat', 'ferida', 'lesao', 'cicatriz'}),
    ('dermat', {'topic', 'topico', 'cutan', 'dermat', 'ferida', 'lesao', 'cicatriz'}),
    ('cutan', {'topic', 'topico', 'cutan', 'dermat', 'ferida', 'lesao', 'cicatriz'}),
    ('ferida', {'topic', 'topico', 'cutan', 'dermat', 'ferida', 'lesao', 'cicatriz'}),
    ('lesa', {'topic', 'topico', 'cutan', 'dermat', 'ferida', 'lesao', 'cicatriz'}),
)

_INDICACOES_GENERICAS_CORTICOIDE = {
    'Anti-inflamatório',
    'Uso prolongado',
}


def _tokens_indicacao(texto: Optional[str]) -> set[str]:
    norm = _texto_norm(texto)
    if not norm:
        return set()
    tokens = {
        token for token in re.findall(r'[a-z0-9]+', norm)
        if len(token) >= 3 and token not in _INDICACAO_STOPWORDS
    }
    expandidos = set(tokens)
    for token in list(tokens):
        for gatilho, sinonimos in _INDICACAO_SINONIMOS:
            if gatilho in token:
                expandidos.update(sinonimos)
    return expandidos


def _eh_corticoide_medicamento(medicamento) -> bool:
    alvo = ' '.join(filter(None, [
        getattr(medicamento, 'classificacao', None),
        getattr(medicamento, 'principio_ativo', None),
        getattr(medicamento, 'nome', None),
    ]))
    norm = _texto_norm(alvo)
    return any(token in norm for token in (
        'esteroidal', 'cortico', 'prednis', 'dexamet', 'hidrocortis', 'metilpred',
    ))


def _filtrar_indicacoes_genericas(medicamento, indicacoes: List[str]) -> List[str]:
    """Oculta rótulos genéricos quando o medicamento oferece opções mais clínicas.

    Em corticoides, "Anti-inflamatório" e "Uso prolongado" ajudam pouco quando
    já temos opções mais operacionais como "Alergia" e "Imunossupressão".
    """
    if not indicacoes:
        return []
    if not _eh_corticoide_medicamento(medicamento):
        return indicacoes

    especificas = [i for i in indicacoes if i not in _INDICACOES_GENERICAS_CORTICOIDE]
    if not especificas:
        return indicacoes
    return especificas


def _resolver_indicacao_compativel(disponiveis: List[str], preferida: Optional[str]) -> Optional[str]:
    preferida_norm = _texto_norm(preferida)
    if not preferida_norm:
        return None

    for candidata in disponiveis:
        if _texto_norm(candidata) == preferida_norm:
            return candidata

    for candidata in disponiveis:
        candidata_norm = _texto_norm(candidata)
        if preferida_norm in candidata_norm or candidata_norm in preferida_norm:
            return candidata

    preferida_tokens = _tokens_indicacao(preferida)
    if not preferida_tokens:
        return None

    melhor = None
    melhor_score = 0
    for candidata in disponiveis:
        candidata_tokens = _tokens_indicacao(candidata)
        if not candidata_tokens:
            continue
        score = len(preferida_tokens & candidata_tokens)
        if score > melhor_score:
            melhor = candidata
            melhor_score = score

    return melhor if melhor_score > 0 else None


def _extrair_concentracao_alvo_mg(proto) -> Optional[float]:
    textos = [
        getattr(proto, 'dose', None),
        getattr(proto, 'dose_raw_text', None),
        getattr(proto, 'observacao', None),
    ]
    for texto in textos:
        norm = _texto_norm(texto)
        if not norm:
            continue
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*mg\b', norm)
        if not match:
            continue
        try:
            return float(match.group(1).replace(',', '.'))
        except (TypeError, ValueError):
            continue
    return None


def _categoria_via_texto(texto: Optional[str]) -> Optional[str]:
    """Normaliza vias/formas em poucas categorias clínicas comparáveis."""
    t = _texto_norm(texto)
    if not t:
        return None
    if any(k in t for k in ('colirio', 'oftalm', 'olho')):
        return 'OFTALMICA'
    if any(k in t for k in ('otologic', 'otolog', 'auric', 'ouvido', 'conduto auditivo', 'canal auditivo')):
        return 'OTICA'
    if any(k in t for k in ('intramus', 'intraven', 'subcut', 'injet', ' parenter')):
        return 'INJETAVEL'
    if any(k in t for k in ('oral', 'capsul', 'comprim', 'tablete', 'drage', 'suspens', 'solucao oral', 'xarope', 'petisco')):
        return 'ORAL'
    if any(k in t for k in ('topic', 'pomada', 'creme', 'gel', 'spray', 'locao', 'lesao', 'cutan')):
        return 'TOPICA'
    if any(k in t for k in ('supositorio', 'retal', 'enema')):
        return 'RETAL'
    return None


def _categoria_apresentacao(ap) -> Optional[str]:
    texto = ' '.join(
        p for p in [
            getattr(ap, 'forma', None),
            getattr(ap, 'concentracao', None),
            getattr(ap, 'nome_variante', None),
        ] if p
    )
    return _categoria_via_texto(texto)


def _preferencias_via_do_medicamento(medicamento) -> List[str]:
    counts: Dict[str, int] = {}
    for ap in (getattr(medicamento, 'apresentacoes', []) or []):
        cat = _categoria_apresentacao(ap)
        if cat:
            counts[cat] = counts.get(cat, 0) + 1

    via_medicamento = _categoria_via_texto(getattr(medicamento, 'via_administracao', None))
    if via_medicamento:
        counts[via_medicamento] = counts.get(via_medicamento, 0) + 1

    if not counts:
        return []

    maior = max(counts.values())
    return [cat for cat, n in counts.items() if n == maior]


def _preferencia_unidade_do_medicamento(medicamento) -> Optional[str]:
    """Prefere dose em mg para apresentações sólidas e em mL/gotas para líquidas."""
    counts = {'SOLIDO': 0, 'LIQUIDO': 0}
    for ap in (getattr(medicamento, 'apresentacoes', []) or []):
        forma = _texto_norm(getattr(ap, 'forma', None))
        if any(k in forma for k in ('capsul', 'comprim', 'tablete', 'drage', 'petisco', 'supositorio')):
            counts['SOLIDO'] += 1
        elif any(k in forma for k in ('suspens', 'solucao', 'colirio', 'gota', 'xarope', 'frasco', 'ampola', 'emuls', 'pasta oral')):
            counts['LIQUIDO'] += 1

    if counts['SOLIDO'] == counts['LIQUIDO'] == 0:
        return None
    return 'SOLIDO' if counts['SOLIDO'] >= counts['LIQUIDO'] else 'LIQUIDO'


def _score_unidade_protocolo(proto, preferencia_unidade: Optional[str]) -> int:
    if preferencia_unidade is None:
        return 0
    unidade = (getattr(proto, 'dose_unidade', None) or '').upper()
    eh_liquido = unidade in {'ML_KG', 'ML_ANIMAL', 'GOTAS_ANIMAL'}
    eh_solido = unidade in {
        'MG_KG', 'MCG_KG', 'UI_KG',
        'MG_ANIMAL', 'MCG_ANIMAL', 'UI_ANIMAL',
        'COMPRIMIDOS_ANIMAL',
    }
    if preferencia_unidade == 'LIQUIDO':
        return 0 if eh_liquido else 1
    return 0 if eh_solido else 1


def _score_protocolo(proto, medicamento) -> Tuple[int, int, float, int]:
    vias_preferidas = _preferencias_via_do_medicamento(medicamento)
    via_proto = _categoria_via_texto(getattr(proto, 'via', None))
    if vias_preferidas:
        via_score = 0 if via_proto in vias_preferidas else (1 if via_proto is None else 2)
    else:
        via_score = 0 if via_proto else 1
    unidade_score = _score_unidade_protocolo(proto, _preferencia_unidade_do_medicamento(medicamento))
    indicacao_score = 0 if (getattr(proto, 'indicacao', None) or '').strip() else 1
    return (via_score, unidade_score, _largura_faixa(proto), indicacao_score)


def _contexto_dose_local(proto) -> Optional[str]:
    texto = _texto_norm(getattr(proto, 'dose', None))
    if 'olho' in texto:
        return 'por olho'
    if any(k in texto for k in ('conduto', 'ouvido', 'canal auditivo')):
        return 'por conduto auditivo'
    if 'narina' in texto:
        return 'por narina'
    return None


def _especie_animal_code(animal) -> str:
    """Mapeia o texto da espécie do animal para o enum interno."""
    if not animal:
        return 'OUTRO'
    nome = ''
    esp = getattr(animal, 'species', None)
    if esp and getattr(esp, 'name', None):
        nome = esp.name
    nome = (nome or '').lower()
    na = nome.replace('ã', 'a').replace('ç', 'c')
    if 'gato' in na or 'felino' in na:
        return 'GATOS'
    if 'cachorro' in na or 'cao' in na or 'canino' in na or 'cães' in nome:
        return 'CAES'
    return 'OUTRO'


def _largura_faixa(proto) -> float:
    a = float(proto.peso_min_kg) if proto.peso_min_kg is not None else 0.0
    b = float(proto.peso_max_kg) if proto.peso_max_kg is not None else 9999.0
    return b - a


def _proto_aplica_basico(proto, esp_code: str, peso: float) -> bool:
    """Filtros de espécie + faixa de peso + dose numérica presente.

    Usado tanto para listar indicações candidatas quanto para escolher o
    protocolo final de dose.
    """
    p_code = (proto.especie_code or '').upper() or None
    if p_code is None:
        t = (proto.especie or '').lower().replace('ã', 'a').replace('ç', 'c')
        if 'cao' in t or 'canino' in t or 'cães' in (proto.especie or '').lower():
            p_code = 'AMBOS' if 'gato' in t or 'felino' in t else 'CAES'
        elif 'gato' in t or 'felino' in t:
            p_code = 'GATOS'
        else:
            p_code = 'AMBOS'
    if not (p_code == 'AMBOS' or p_code == esp_code):
        return False
    if proto.peso_min_kg is not None and peso < float(proto.peso_min_kg):
        return False
    if proto.peso_max_kg is not None and peso > float(proto.peso_max_kg):
        return False
    if proto.dose_min is None or proto.dose_unidade is None:
        return False
    return True


def _indicacoes_disponiveis(medicamento, animal) -> List[str]:
    """Lista as indicações clínicas distintas para as quais existe ao menos um
    protocolo aplicável ao animal (mesma espécie + peso na faixa). Ordem
    estável pela frequência de aparição."""
    peso = getattr(animal, 'peso', None)
    if peso is None:
        return []
    try:
        peso = float(peso)
    except (TypeError, ValueError):
        return []
    if peso <= 0:
        return []
    esp_code = _especie_animal_code(animal)
    vistas: List[str] = []
    for proto in (getattr(medicamento, 'doses', []) or []):
        if _dose_ambigua_por_apresentacao(medicamento, proto):
            continue
        if not _proto_aplica_basico(proto, esp_code, peso):
            continue
        ind = (getattr(proto, 'indicacao', None) or '').strip()
        if ind and ind not in vistas:
            vistas.append(ind)
    return _filtrar_indicacoes_genericas(medicamento, vistas)


def sugerir_dose(medicamento, animal, indicacao: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retorna dict com sugestão de dose, ou None se não aplicável.

    Se `indicacao` não for passada e houver protocolos com indicações
    múltiplas aplicáveis ao animal, retorna um dict de modo-lista:
      {
        'multiplo': True,
        'indicacoes': ['Alergia', 'Imunossupressão', ...],
        'medicamento_id': int,
      }
    para o frontend exibir um dropdown e re-chamar passando a indicação.

    Quando `indicacao` é passada, o filtro é aplicado antes da escolha de
    protocolo.

    Formato do retorno de sucesso (modo-dose):
      {
        'multiplo': False,
        'protocolo_id': int,
        'especie':  'Cães',
        'peso_kg':  10.0,
        'dose_min': 125.0, 'dose_max': 250.0, 'dose_unit_out': 'mg',
        'dose_exibir': '125,0–250,0 mg',
        'faixa_texto': '12,5–25 mg/kg',
        'via': 'oral',
        'intervalo_horas': 12, 'frequencia_texto': 'a cada 12h',
        'duracao_min_dias': None, 'duracao_max_dias': 30,
        'duracao_texto': 'por até 30 dias',
        'indicacao': 'Alergia',
        'indicacoes_alternativas': ['Imunossupressão', 'Dermatite atópica'],
        'apresentacoes': [
            {'id': 3, 'descricao': 'comprimido 250 mg — LigVet',
             'fabricante': 'LigVet',
             'equivalencia': '0,75 cp de 250 mg por administração'},
            ...
        ],
        'fonte': 'SCRAPER', 'confianca': 'MEDIA',
        'observacao': '...',
      }
    """
    if not medicamento or not animal:
        return None
    peso = getattr(animal, 'peso', None)
    if peso is None:
        return None
    try:
        peso = float(peso)
    except (TypeError, ValueError):
        return None
    if peso <= 0:
        return None

    esp_code = _especie_animal_code(animal)
    protos = [
        p for p in (getattr(medicamento, 'doses', []) or [])
        if not _dose_ambigua_por_apresentacao(medicamento, p)
    ]
    if not protos:
        return None

    # Se nenhuma indicação foi escolhida, checa se temos múltiplas candidatas
    # e devolve lista pro frontend pedir escolha do vet.
    if indicacao is None:
        indicacoes = _indicacoes_disponiveis(medicamento, animal)
        tem_generico_aplicavel = any(
            _proto_aplica_basico(p, esp_code, peso)
            and not ((getattr(p, 'indicacao', None) or '').strip())
            for p in protos
        )
        # Considera "múltiplo" apenas quando há >=2 indicações diferentes
        # (evita forçar dropdown quando só existe "Alergia" ou quando todos
        # são NULL).
        if len(indicacoes) >= 2:
            return {
                'multiplo': True,
                'indicacoes': indicacoes,
                'medicamento_id': getattr(medicamento, 'id', None),
            }
        # Só auto-filtra quando existe exatamente 1 indicação E não há
        # protocolo genérico aplicável. Se coexistem linhas genéricas com uma
        # única indicação nomeada (caso comum em AINEs), mantemos tudo no pool
        # para a heurística de via/apresentação escolher o protocolo mais útil.
        indicacao_filtro = indicacoes[0] if (len(indicacoes) == 1 and not tem_generico_aplicavel) else None
    else:
        indicacao_filtro = (indicacao or '').strip() or None
        if indicacao_filtro is not None:
            indicacoes_disp = _indicacoes_disponiveis(medicamento, animal)
            indicacao_resolvida = _resolver_indicacao_compativel(indicacoes_disp, indicacao_filtro)
            if indicacao_resolvida is not None:
                indicacao_filtro = indicacao_resolvida
            elif len(indicacoes_disp) >= 2:
                return {
                    'multiplo': True,
                    'indicacoes': indicacoes_disp,
                    'medicamento_id': getattr(medicamento, 'id', None),
                }
            elif len(indicacoes_disp) == 1:
                indicacao_filtro = indicacoes_disp[0]
            else:
                indicacao_filtro = None

    # Filtra por espécie + faixa de peso + indicação
    def _aplica(p):
        if not _proto_aplica_basico(p, esp_code, peso):
            return False
        if indicacao_filtro is not None:
            p_ind = (getattr(p, 'indicacao', None) or '').strip() or None
            if p_ind != indicacao_filtro:
                return False
        return True

    candidatos = [p for p in protos if _aplica(p)]
    if not candidatos:
        # Se o filtro de indicação eliminou tudo, tenta sem filtro como fallback
        if indicacao_filtro is not None:
            candidatos = [p for p in protos if _proto_aplica_basico(p, esp_code, peso)]
        if not candidatos:
            return None

    proto = min(candidatos, key=lambda p: _score_protocolo(p, medicamento))

    dose_min_v = float(proto.dose_min)
    dose_max_v = float(proto.dose_max) if proto.dose_max is not None else dose_min_v
    un = (proto.dose_unidade or 'MG_KG').upper()

    if un.endswith('_KG'):
        dose_calc_min = dose_min_v * peso
        dose_calc_max = dose_max_v * peso
    else:
        dose_calc_min = dose_min_v
        dose_calc_max = dose_max_v

    unit_out_map = {
        'MG_KG': 'mg', 'MCG_KG': 'mcg', 'ML_KG': 'mL', 'UI_KG': 'UI',
        'MG_ANIMAL': 'mg', 'MCG_ANIMAL': 'mcg', 'ML_ANIMAL': 'mL',
        'PIPETA_ANIMAL': 'pipeta(s)', 'COMPRIMIDOS_ANIMAL': 'comprimido(s)',
        'GOTAS_ANIMAL': 'gota(s)', 'UI_ANIMAL': 'UI',
        'CAMADA_TOPICA': 'camada fina',
        # Unidades por peso (dose normalizada por kg)
        'COMPRIMIDOS_KG': 'comprimido(s)',
        'PIPETA_KG': 'pipeta(s)',
    }
    dose_unit_out = unit_out_map.get(un, '')

    def _fmt(v: float) -> str:
        if v == int(v):
            return f"{int(v)}"
        return f"{v:.2f}".rstrip('0').rstrip('.').replace('.', ',')

    if dose_calc_min == dose_calc_max:
        dose_exibir = f"{_fmt(dose_calc_min)} {dose_unit_out}".strip()
    else:
        dose_exibir = f"{_fmt(dose_calc_min)}–{_fmt(dose_calc_max)} {dose_unit_out}".strip()
    if dose_unit_out == 'gota(s)':
        contexto_local = _contexto_dose_local(proto)
        if contexto_local:
            dose_exibir = f"{dose_exibir} {contexto_local}"

    faixa_unit_label = {
        'MG_KG': 'mg/kg', 'MCG_KG': 'mcg/kg', 'ML_KG': 'mL/kg', 'UI_KG': 'UI/kg',
        'MG_ANIMAL': 'mg/animal', 'ML_ANIMAL': 'mL/animal',
        'PIPETA_ANIMAL': 'pipeta/animal', 'COMPRIMIDOS_ANIMAL': 'cp/animal',
        'GOTAS_ANIMAL': 'gotas/animal',
        'CAMADA_TOPICA': 'aplicacao topica',
        'COMPRIMIDOS_KG': 'cp/kg', 'PIPETA_KG': 'pipeta/kg',
    }.get(un, un.lower())
    if dose_min_v == dose_max_v:
        faixa_texto = f"{_fmt(dose_min_v)} {faixa_unit_label}"
    else:
        faixa_texto = f"{_fmt(dose_min_v)}–{_fmt(dose_max_v)} {faixa_unit_label}"

    # Frequência — usa faixa quando disponível
    freq_min_h = proto.intervalo_min_horas
    freq_max_h = proto.intervalo_max_horas
    tem_faixa_freq = bool(freq_min_h and freq_max_h and freq_min_h != freq_max_h)
    if tem_faixa_freq:
        freq_texto = f"a cada {freq_min_h}–{freq_max_h}h"
    elif proto.intervalo_horas:
        freq_texto = f"a cada {proto.intervalo_horas}h"
    elif proto.frequencia:
        freq_texto = proto.frequencia
    else:
        freq_texto = '—'

    # Duração textual — específica do produto ou padrão da classe
    dur_min_d = proto.duracao_min_dias
    dur_max_d = proto.duracao_max_dias
    duracao_e_padrao = False
    duracao_do_prescritor = False
    duracao_padrao_desc: Optional[str] = None
    duracao_proto_texto = (getattr(proto, 'duracao', None) or '').strip()

    if dur_min_d is None and dur_max_d is None and duracao_proto_texto:
        txt_min, txt_max = _parse_duracao_dias(duracao_proto_texto)
        if txt_min is not None or txt_max is not None:
            dur_min_d, dur_max_d = txt_min, txt_max

    if dur_min_d is None and dur_max_d is None:
        pd_min, pd_max, pd_desc = _duracao_produtos_vetsmart(medicamento)
        if pd_min is not None or pd_max is not None:
            dur_min_d, dur_max_d = pd_min, pd_max
            duracao_do_prescritor = True
            duracao_padrao_desc = pd_desc
        else:
            pd_min, pd_max, pd_desc = _duracao_prescritor_vetsmart(medicamento)
            if pd_min is not None or pd_max is not None:
                dur_min_d, dur_max_d = pd_min, pd_max
                duracao_do_prescritor = True
                duracao_padrao_desc = pd_desc
            elif not duracao_proto_texto:
                pd_min, pd_max, pd_desc = _duracao_padrao(medicamento)
                if pd_min is not None:
                    dur_min_d, dur_max_d = pd_min, pd_max
                    duracao_e_padrao = True
                    duracao_padrao_desc = pd_desc

    tem_faixa_dur = bool(dur_min_d and dur_max_d and dur_min_d != dur_max_d)

    if tem_faixa_dur:
        dur_texto = f"por {dur_min_d}–{dur_max_d} dias"
        dur_texto_min = f"por {dur_min_d} dias"
        dur_texto_max = f"por {dur_max_d} dias"
        dur_media_d = (dur_min_d + dur_max_d) // 2
        dur_texto_media = f"por {dur_media_d} dias"
    elif dur_max_d and not dur_min_d:
        dur_texto = f"por até {dur_max_d} dias"
        dur_texto_min = dur_texto_max = dur_texto_media = dur_texto
    elif dur_min_d:
        dur_texto = f"por {dur_min_d} dias"
        dur_texto_min = dur_texto_max = dur_texto_media = dur_texto
    else:
        dur_texto = duracao_proto_texto or '—'
        dur_texto_min = dur_texto_max = dur_texto_media = dur_texto

    # Equivalências por apresentação
    dose_media = (dose_calc_min + dose_calc_max) / 2.0
    apres_info: List[Dict[str, Any]] = []
    for ap in (medicamento.apresentacoes or []):
        desc_parts = [ap.forma]
        if ap.concentracao_valor:
            desc_parts.append(f"{_fmt(float(ap.concentracao_valor))} {ap.concentracao_unidade}")
        if ap.volume_valor:
            desc_parts.append(f"({_fmt(float(ap.volume_valor))} {ap.volume_unidade})")
        desc = ' '.join(p for p in desc_parts if p)
        fabricante = getattr(ap, 'fabricante', None)
        if fabricante:
            desc = f"{desc} — {fabricante}"

        equiv = None
        if dose_unit_out == 'mg' and ap.concentracao_valor and ap.concentracao_unidade:
            cv = float(ap.concentracao_valor)
            un_ap = (ap.concentracao_unidade or '').lower()
            if un_ap in ('mg', 'g', 'mcg'):
                cv_mg = cv
                if un_ap == 'g':
                    cv_mg = cv * 1000.0
                elif un_ap == 'mcg':
                    cv_mg = cv / 1000.0
                n = dose_media / cv_mg
                equiv = f"{_fmt(n)} × {ap.forma} de {_fmt(cv)} {un_ap} por administração"
            elif un_ap in ('mg/ml', 'mcg/ml'):
                cv_mg_ml = cv / 1000.0 if un_ap == 'mcg/ml' else cv
                ml = dose_media / cv_mg_ml
                equiv = f"{_fmt(ml)} mL por administração"
        elif dose_unit_out == 'mL' and ap.concentracao_unidade == 'mg/ml':
            # dose em mL já é direta
            pass

        # Unidade prática que o tutor administra (cápsula, mL, gota, etc.).
        # Usada para gerar a frase "X cápsulas (cinco cápsulas)" no card.
        unidade_pratica = _unidade_pratica_por_forma(ap.forma)
        categoria, categoria_label = _forma_categoria_apresentacao_servico(ap.forma, ap.concentracao)
        tipo_origem = _tipo_origem_apresentacao(fabricante)

        apres_info.append({
            'id': ap.id,
            'descricao': desc,
            'nome_variante': getattr(ap, 'nome_variante', None) or '',
            'fabricante': fabricante,
            'tipo_origem': tipo_origem,
            'categoria': categoria,
            'categoria_label': categoria_label,
            'forma': ap.forma or '',
            'concentracao_texto': ap.concentracao or '',
            'concentracao_valor': float(ap.concentracao_valor) if ap.concentracao_valor is not None else None,
            'concentracao_unidade': ap.concentracao_unidade or '',
            'volume_valor': float(ap.volume_valor) if ap.volume_valor is not None else None,
            'volume_unidade': ap.volume_unidade or '',
            'unidade_pratica': unidade_pratica,
            'faixa_peso_label': _extrair_faixa_peso_apresentacao(ap),
            'especie_label': _extrair_especie_apresentacao(ap),
            'rotulo_escolha': _montar_rotulo_apresentacao_escolha(ap),
            # Se `concentracao_valor` existir, o frontend pode calcular
            # automaticamente; senão, precisa pedir ao vet que digite.
            'permite_calculo_automatico': bool(ap.concentracao_valor),
            'equivalencia': equiv,
        })

    # Lista de indicações alternativas disponíveis para o mesmo animal
    # (pro frontend permitir trocar sem nova round-trip se quiser).
    apres_unicas: Dict[tuple, Dict[str, Any]] = {}
    for ap_info in sorted(apres_info, key=_ordenar_apresentacao_info):
        chave = _chave_visual_apresentacao(ap_info)
        existente = apres_unicas.get(chave)
        fabricante_atual = ap_info.get('fabricante') or ''
        if not existente:
            ap_info['fabricantes'] = [fabricante_atual] if fabricante_atual else []
            ap_info['source_count'] = 1
            apres_unicas[chave] = ap_info
            continue
        if fabricante_atual and fabricante_atual not in existente.get('fabricantes', []):
            existente.setdefault('fabricantes', []).append(fabricante_atual)
        existente['source_count'] = int(existente.get('source_count') or 1) + 1
        if (
            not existente.get('permite_calculo_automatico') and ap_info.get('permite_calculo_automatico')
        ) or len(ap_info.get('descricao') or '') > len(existente.get('descricao') or ''):
            ap_info['fabricantes'] = existente.get('fabricantes', [])
            ap_info['source_count'] = existente.get('source_count', 1)
            apres_unicas[chave] = ap_info
    apres_info = list(apres_unicas.values())

    indicacoes_disp = _indicacoes_disponiveis(medicamento, animal)
    proto_ind = (getattr(proto, 'indicacao', None) or '').strip() or None
    indicacoes_alt = [i for i in indicacoes_disp if i != proto_ind]

    # Concentrações conhecidas — união das concentrações cadastradas em
    # QUALQUER apresentação deste Medicamento. Usado pelo frontend pra
    # oferecer um dropdown de concentrações pré-validadas quando o vet
    # seleciona uma apresentação manipulada sem concentração fixa (ex.
    # "Cápsulas LigVet"). Evita que ele invente uma dose que talvez nem
    # exista no mercado.
    conc_vistas: Dict[str, Dict[str, Any]] = {}
    for ap in (medicamento.apresentacoes or []):
        if ap.concentracao_valor is None or not ap.concentracao_unidade:
            continue
        valor = float(ap.concentracao_valor)
        un = ap.concentracao_unidade
        chave = f"{valor:g}|{un}"
        if chave in conc_vistas:
            # Agrega fabricantes que oferecem esta concentração
            fab_atual = ap.fabricante or ''
            fabs = conc_vistas[chave].get('fabricantes', [])
            if fab_atual and fab_atual not in fabs:
                fabs.append(fab_atual)
            conc_vistas[chave]['fabricantes'] = fabs
        else:
            conc_vistas[chave] = {
                'valor': valor,
                'unidade': un,
                'fabricantes': [ap.fabricante] if ap.fabricante else [],
                'label': f'{valor:g} {un}',
            }
    concentracoes_conhecidas = sorted(
        conc_vistas.values(),
        key=lambda c: (c['unidade'], c['valor']),
    )

    dose_calc_media = (dose_calc_min + dose_calc_max) / 2.0
    concentracao_alvo_mg = _extrair_concentracao_alvo_mg(proto)
    apresentacao_preferida_id = None
    apresentacao_preferida_nome = ''
    if concentracao_alvo_mg is not None:
        for ap in apres_info:
            valor = ap.get('concentracao_valor')
            unidade = (ap.get('concentracao_unidade') or '').lower()
            if valor is None or unidade != 'mg':
                continue
            if abs(float(valor) - float(concentracao_alvo_mg)) < 0.001:
                apresentacao_preferida_id = ap.get('id')
                apresentacao_preferida_nome = ap.get('nome_variante') or ''
                break

    origem = _resumo_origem_dose(proto, duracao_e_padrao=duracao_e_padrao, proto_ind=proto_ind)
    flags_risco: List[Dict[str, str]] = []
    if origem['fonte'] == 'LLM':
        _adicionar_flag_risco(
            flags_risco,
            codigo='PROTOCOLO_ASSISTIDO',
            nivel='atencao',
            titulo='Revisão clínica recomendada',
            detalhe='A estrutura da dose contou com assistência automatizada; revise antes de usar.',
        )
    if origem['confianca'] == 'BAIXA':
        _adicionar_flag_risco(
            flags_risco,
            codigo='CONFIANCA_BAIXA',
            nivel='critico',
            titulo='Confianca baixa',
            detalhe='O protocolo foi marcado com baixa confiança e exige checagem manual antes da prescrição.',
        )
    elif origem['confianca'] == 'MEDIA':
        _adicionar_flag_risco(
            flags_risco,
            codigo='CONFIANCA_MEDIA',
            nivel='atencao',
            titulo='Confianca intermediaria',
            detalhe='A dose é utilizável como apoio, mas ainda deve ser validada no contexto clínico.',
        )
    if duracao_e_padrao:
        _adicionar_flag_risco(
            flags_risco,
            codigo='DURACAO_INFERIDA',
            nivel='atencao',
            titulo='Duracao de referencia',
            detalhe='A duracao foi inferida pela classe farmacologica porque o protocolo original nao informava esse campo.',
        )
    if duracao_do_prescritor:
        _adicionar_flag_risco(
            flags_risco,
            codigo='DURACAO_PRESCRITOR_VETSMART',
            nivel='informativo',
            titulo='Duracao VetSmart',
            detalhe='A duracao veio de dados estruturados do VetSmart porque o protocolo original nao informava esse campo.',
        )
    if not proto_ind:
        _adicionar_flag_risco(
            flags_risco,
            codigo='INDICACAO_NAO_ESPECIFICADA',
            nivel='atencao',
            titulo='Indicacao nao especificada',
            detalhe='O protocolo aplicado nao trouxe indicacao clinica explicita; valide se a dose faz sentido para o objetivo do tratamento.',
        )
    if not apres_info:
        _adicionar_flag_risco(
            flags_risco,
            codigo='SEM_APRESENTACAO_COMERCIAL',
            nivel='informativo',
            titulo='Sem apresentacao vinculada',
            detalhe='Nao ha apresentacao comercial estruturada para converter automaticamente a dose em comprimidos, mL ou gotas.',
        )
    elif not any(ap.get('permite_calculo_automatico') for ap in apres_info):
        _adicionar_flag_risco(
            flags_risco,
            codigo='APRESENTACAO_SEM_CONCENTRACAO',
            nivel='atencao',
            titulo='Apresentacao depende de concentracao',
            detalhe='As apresentacoes disponiveis exigem que o veterinario confirme a concentracao antes da conversao pratica.',
        )

    diagnosticos = {
        'requer_validacao_clinica': any(flag['nivel'] in {'critico', 'atencao'} for flag in flags_risco),
        'tem_apresentacao_calculavel': any(ap.get('permite_calculo_automatico') for ap in apres_info),
        'tem_apresentacao_preferida': bool(apresentacao_preferida_id),
        'quantidade_protocolos_candidatos': len(candidatos),
        'quantidade_indicacoes_disponiveis': len(indicacoes_disp),
        'tem_estatistica_prescritor_vetsmart': bool(_prescritor_vetsmart_stats(medicamento)),
        'origem': origem,
        'flags_risco': flags_risco,
        'resumo_clinico': {
            'indicacao_escolhida': proto_ind,
            'via_escolhida': proto.via or medicamento.via_administracao or '',
            'fonte_label': origem['rotulo'],
        },
    }

    return {
        'multiplo':                False,
        'protocolo_id':            proto.id,
        'especie':                 proto.especie,
        'peso_kg':                 peso,
        'dose_min':                dose_calc_min,
        'dose_media':              dose_calc_media,
        'dose_max':                dose_calc_max,
        'dose_unit_out':           dose_unit_out,
        'dose_exibir':             dose_exibir,
        'faixa_texto':             faixa_texto,
        'via':                     proto.via or medicamento.via_administracao or '',
        'intervalo_horas':         proto.intervalo_horas,
        'intervalo_min_horas':     freq_min_h,
        'intervalo_max_horas':     freq_max_h,
        'tem_faixa_frequencia':    tem_faixa_freq,
        'frequencia_texto':        freq_texto,
        'frequencia_bruta':        getattr(proto, 'frequencia', None) or '',
        'duracao_min_dias':        dur_min_d,
        'duracao_max_dias':        dur_max_d,
        'duracao_texto':           dur_texto,
        'duracao_bruta':           getattr(proto, 'duracao', None) or '',
        'duracao_texto_min':       dur_texto_min,
        'duracao_texto_media':     dur_texto_media,
        'duracao_texto_max':       dur_texto_max,
        'tem_faixa_duracao':       tem_faixa_dur,
        'duracao_e_padrao':        duracao_e_padrao,
        'duracao_do_prescritor_vetsmart': duracao_do_prescritor,
        'duracao_padrao_desc':     duracao_padrao_desc,
        'indicacao':               proto_ind,
        'indicacoes_alternativas': indicacoes_alt,
        'apresentacao_preferida_id': apresentacao_preferida_id,
        'apresentacao_preferida_nome': apresentacao_preferida_nome,
        'apresentacoes':           apres_info,
        'concentracoes_conhecidas': concentracoes_conhecidas,
        'fonte':                   proto.fonte or 'SCRAPER',
        'confianca':               proto.confianca or 'MEDIA',
        'observacao':              proto.observacao,
        'origem':                  origem,
        'flags_risco':             flags_risco,
        'diagnosticos':            diagnosticos,
    }
