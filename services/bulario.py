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


def construir_posologia_por_especie(medicamento) -> List[Dict[str, Any]]:
    doses = list(getattr(medicamento, "doses", []) or [])
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
        protocolos = []
        for indicacao, itens in grupos.items():
            protocolos.append({
                "indicacao": indicacao,
                "linhas": [
                    {
                        "faixa_peso": _texto_limpo(getattr(d, "faixa_peso", None)) or "Sem faixa definida",
                        "via": _texto_limpo(getattr(d, "via", None)) or _texto_limpo(getattr(medicamento, "via_administracao", None)) or "—",
                        "dose": _texto_limpo(getattr(d, "dose", None)) or "—",
                        "frequencia": _texto_limpo(getattr(d, "frequencia", None)) or _texto_limpo(getattr(medicamento, "frequencia", None)) or "—",
                        "duracao": _texto_limpo(getattr(d, "duracao", None)) or _texto_limpo(getattr(medicamento, "duracao_tratamento", None)) or "—",
                        "observacao": _texto_limpo(getattr(d, "observacao", None)),
                    }
                    for d in itens
                ],
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
    return {
        "resumo_posologia": {
            "dose": _texto_limpo(getattr(medicamento, "dosagem_recomendada", None)),
            "frequencia": _texto_limpo(getattr(medicamento, "frequencia", None)),
            "duracao": _texto_limpo(getattr(medicamento, "duracao_tratamento", None)),
            "tabs": posologia_tabs,
        },
        "secoes": secoes,
        "tem_conteudo_clinico": any([
            secoes["indicacoes"]["itens"],
            secoes["contraindicacoes"]["itens"],
            secoes["efeitos_adversos"]["itens"],
            secoes["advertencias"]["itens"],
            secoes["interacoes"]["itens"],
        ]),
    }


def serializar_medicamento_busca(medicamento) -> Dict[str, Any]:
    estrutura = montar_monografia_medicamento(medicamento)
    bula_url = None
    if getattr(medicamento, "vetsmart_produto_id", None):
        bula_url = f"https://vetsmart.com.br/cg/produto/{medicamento.vetsmart_produto_id}"
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
        'COMPRIMIDOS_KG': 'cp/kg', 'PIPETA_KG': 'pipeta/kg',
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

    # Duração textual — mínima, padrão e máxima quando há faixa real
    dur_min_d = proto.duracao_min_dias
    dur_max_d = proto.duracao_max_dias
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
        dur_texto = proto.duracao or '—'
        dur_texto_min = dur_texto_max = dur_texto_media = dur_texto
    tem_faixa_dur = tem_faixa_dur  # reusado abaixo

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

    dose_calc_media = (dose_calc_min + dose_calc_max) / 2.0

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
        'frequencia_texto':        freq_texto,
        'duracao_min_dias':        proto.duracao_min_dias,
        'duracao_max_dias':        proto.duracao_max_dias,
        'duracao_texto':           dur_texto,
        'duracao_texto_min':       dur_texto_min,
        'duracao_texto_media':     dur_texto_media,
        'duracao_texto_max':       dur_texto_max,
        'tem_faixa_duracao':       tem_faixa_dur,
        'indicacao':               proto_ind,
        'indicacoes_alternativas': indicacoes_alt,
        'apresentacoes':           apres_info,
        'concentracoes_conhecidas': concentracoes_conhecidas,
        'fonte':                   proto.fonte or 'SCRAPER',
        'confianca':               proto.confianca or 'MEDIA',
        'observacao':              proto.observacao,
    }
