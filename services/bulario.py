"""Serviço de sugestão de dose a partir do bulário.

Usado pelo endpoint /api/bulario/sugerir-dose e por qualquer outro caller
que precise propor uma dose para um animal específico.
"""
from __future__ import annotations
import re
import unicodedata
from typing import Optional, Dict, Any, List, Tuple


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
    return _UNIDADE_PRATICA_POR_FORMA.get(chave, 'unidade')


def _texto_norm(s: Optional[str]) -> str:
    return _strip_accents(s or '').lower().strip()


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
        if not _proto_aplica_basico(proto, esp_code, peso):
            continue
        ind = (getattr(proto, 'indicacao', None) or '').strip()
        if ind and ind not in vistas:
            vistas.append(ind)
    return vistas


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
    protos = list(getattr(medicamento, 'doses', []) or [])
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
    }.get(un, un.lower())
    if dose_min_v == dose_max_v:
        faixa_texto = f"{_fmt(dose_min_v)} {faixa_unit_label}"
    else:
        faixa_texto = f"{_fmt(dose_min_v)}–{_fmt(dose_max_v)} {faixa_unit_label}"

    # Frequência textual
    if proto.intervalo_horas:
        freq_texto = f"a cada {proto.intervalo_horas}h"
    elif proto.frequencia:
        freq_texto = proto.frequencia
    else:
        freq_texto = '—'

    # Duração textual
    if proto.duracao_min_dias and proto.duracao_max_dias and proto.duracao_min_dias != proto.duracao_max_dias:
        dur_texto = f"por {proto.duracao_min_dias}–{proto.duracao_max_dias} dias"
    elif proto.duracao_max_dias and not proto.duracao_min_dias:
        dur_texto = f"por até {proto.duracao_max_dias} dias"
    elif proto.duracao_min_dias:
        dur_texto = f"por {proto.duracao_min_dias} dias"
    else:
        dur_texto = proto.duracao or '—'

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

        apres_info.append({
            'id': ap.id,
            'descricao': desc,
            'fabricante': fabricante,
            'forma': ap.forma or '',
            'concentracao_texto': ap.concentracao or '',
            'concentracao_valor': float(ap.concentracao_valor) if ap.concentracao_valor is not None else None,
            'concentracao_unidade': ap.concentracao_unidade or '',
            'volume_valor': float(ap.volume_valor) if ap.volume_valor is not None else None,
            'volume_unidade': ap.volume_unidade or '',
            'unidade_pratica': unidade_pratica,
            # Se `concentracao_valor` existir, o frontend pode calcular
            # automaticamente; senão, precisa pedir ao vet que digite.
            'permite_calculo_automatico': bool(ap.concentracao_valor),
            'equivalencia': equiv,
        })

    # Lista de indicações alternativas disponíveis para o mesmo animal
    # (pro frontend permitir trocar sem nova round-trip se quiser).
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

    return {
        'multiplo':                False,
        'protocolo_id':            proto.id,
        'especie':                 proto.especie,
        'peso_kg':                 peso,
        'dose_min':                dose_calc_min,
        'dose_max':                dose_calc_max,
        'dose_unit_out':           dose_unit_out,
        'dose_exibir':             dose_exibir,
        'faixa_texto':             faixa_texto,
        'via':                     proto.via or medicamento.via_administracao or '',
        'intervalo_horas':         proto.intervalo_horas,
        'frequencia_texto':        freq_texto,
        'duracao_min_dias':        proto.duracao_min_dias,
        'duracao_max_dias':        proto.duracao_max_dias,
        'duracao_texto':           dur_texto,
        'indicacao':               proto_ind,
        'indicacoes_alternativas': indicacoes_alt,
        'apresentacoes':           apres_info,
        'concentracoes_conhecidas': concentracoes_conhecidas,
        'fonte':                   proto.fonte or 'SCRAPER',
        'confianca':               proto.confianca or 'MEDIA',
        'observacao':              proto.observacao,
    }
