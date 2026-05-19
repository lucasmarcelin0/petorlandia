"""Normalização de posologia (frequência / duração) e deduplicação de doses.

Módulo PURO (depende só de `re`/`unicodedata`) — usado tanto pela camada de
apresentação (`services/bulario.py`) quanto pelo scraper
(`scripts/importar_medicamentos_vetsmart.py`).  O objetivo é transformar o
texto bruto e bagunçado que vem do VetSmart em strings curtas, canônicas e
reconhecíveis por veterinários, e colapsar linhas de dose semanticamente
idênticas.

Casos reais tratados (observados no banco):
  frequência:
    "8/8 horas 12/12 horas"   -> "8/8h ou 12/12h"  (dois protocolos colados)
    "Via Oral: 8-12h."        -> "8–12h"            (via vazou pro campo)
    "12 em 12 horas"          -> "12/12h"
    "12 / 12 horas"           -> "12/12h"
    "a cada 24 horas"         -> "24/24h"
    "2 vezes ao dia"          -> "12/12h"
  duração:
    "7 a 10 dias. Em processos..." -> "7 a 10 dias"
    "A duração do tratamento pode variar muito de acordo com a gravidade da
     infecção. Frequentemente usa-"  (truncado)  -> "Conforme avaliação clínica"
    "A critério do médico veterinário." -> "A critério do médico-veterinário"
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, List, Optional


def _sa(s: str) -> str:
    """strip accents + lower."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _limpo(texto: Optional[str]) -> str:
    if not texto:
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip()


# ───────────────────────── FREQUÊNCIA ──────────────────────────────────────

# Prefixos que "vazam" do campo Via para o campo Frequência no VetSmart.
# NÃO inclui sid/bid/tid/qid — essas são abreviações de FREQUÊNCIA, não via.
_RE_PREFIXO_VIA = re.compile(
    r"^\s*(?:via\s+)?(?:oral|t[oó]pica?|or[ai]l|of?t[aá]lmica?|"
    r"intramuscular|intravenosa|subcut[aâ]nea|parenteral|v\.?o\.?|i\.?m\.?|"
    r"i\.?v\.?|s\.?c\.?)\b"
    r"\s*[:\-–]?\s*",
    re.IGNORECASE,
)

_H = r"(?:h|hr|hrs|hora|horas)"

# Latim/abreviações veterinárias -> horas
_VET_ABBR = [
    (r"\bsid\b|\bq\s*24\s*h\b|\b1\s*x\s*(?:ao|por|/)?\s*dia\b|uma\s+vez\s+ao\s+dia", 24),
    (r"\bbid\b|\bq\s*12\s*h\b|\b2\s*x\s*(?:ao|por|/)?\s*dia\b|duas\s+vezes\s+ao\s+dia", 12),
    (r"\btid\b|\bq\s*8\s*h\b|\b3\s*x\s*(?:ao|por|/)?\s*dia\b|tr[eê]s\s+vezes\s+ao\s+dia", 8),
    (r"\bqid\b|\bq\s*6\s*h\b|\b4\s*x\s*(?:ao|por|/)?\s*dia\b|quatro\s+vezes\s+ao\s+dia", 6),
    (r"\beod\b|\bq\s*48\s*h\b|dias?\s+alternad|every\s+other\s+day", 48),
]

# "N/N h", "N em N h", "N - N h" (intervalo único onde os dois números são iguais)
_RE_NN_H = re.compile(rf"(\d{{1,3}})\s*(?:/|em|\-|–)\s*\1\s*{_H}\b", re.IGNORECASE)
# "a cada N horas" / "cada N h" / "N/N horas" (qualquer N)
_RE_CADA_H = re.compile(
    rf"(?:a\s+cada|cada|de)\s+(\d{{1,3}})\s*{_H}\b", re.IGNORECASE
)
_RE_BARRA_H = re.compile(rf"(\d{{1,3}})\s*/\s*(\d{{1,3}})\s*{_H}\b", re.IGNORECASE)
_RE_EM_H = re.compile(rf"(\d{{1,3}})\s*em\s*(\d{{1,3}})\s*{_H}\b", re.IGNORECASE)
# faixa contínua "a cada 8 a 12h" / "8-12h" / "8 a 12 horas"
_RE_FAIXA_H = re.compile(
    rf"(\d{{1,3}})\s*(?:{_H})?\s*(?:a|à|–|-|ou|até)\s*(\d{{1,3}})\s*{_H}\b",
    re.IGNORECASE,
)
_RE_X_DIA = re.compile(
    r"(\d{1,2})\s*(?:x|vezes?)\s*(?:ao|por|/)?\s*dia", re.IGNORECASE
)
_RE_CADA_DIA = re.compile(
    r"(?:a\s+cada|cada)\s+(\d{1,2})\s*dias?\b", re.IGNORECASE
)


def _fmt_intervalo(v: int) -> Optional[str]:
    if not v or v <= 0:
        return None
    if v >= 24 and v % 24 == 0:
        dias = v // 24
        return "24/24h" if dias == 1 else f"a cada {dias} dias"
    return f"{v}/{v}h"


def _coletar_intervalos(t: str) -> List[Any]:
    """Retorna lista ordenada/única de intervalos detectados.

    Cada item é um int (horas) OU uma tupla (min, max) para faixa contínua.
    """
    achados: List[Any] = []

    for pat, horas in _VET_ABBR:
        if re.search(pat, t, re.IGNORECASE):
            achados.append(horas)

    # faixa contínua explícita ("a cada 8 a 12h", "8-12h") — só conta como
    # faixa se os dois números forem diferentes.
    for m in _RE_FAIXA_H.finditer(t):
        a, b = int(m.group(1)), int(m.group(2))
        if a != b and 1 <= a <= 72 and 1 <= b <= 72:
            achados.append((min(a, b), max(a, b)))

    # "N/N h" e "N em N h" (mesmo número dos dois lados → intervalo único)
    for m in _RE_NN_H.finditer(t):
        achados.append(int(m.group(1)))
    for rx in (_RE_BARRA_H, _RE_EM_H):
        for m in rx.finditer(t):
            a, b = int(m.group(1)), int(m.group(2))
            if a == b and 1 <= a <= 72:
                achados.append(a)

    for m in _RE_CADA_H.finditer(t):
        v = int(m.group(1))
        if 1 <= v <= 72:
            achados.append(v)
    for m in _RE_CADA_DIA.finditer(t):
        achados.append(int(m.group(1)) * 24)
    for m in _RE_X_DIA.finditer(t):
        n = int(m.group(1))
        if n > 0:
            achados.append(max(1, 24 // n))

    # Último recurso: "12h" / "24hrs" soltos (sem "a cada"/"/"/etc.).
    # Só quando nada mais foi detectado, pega o PRIMEIRO token de horas
    # plausível — evita mostrar a prosa bruta do VetSmart.
    if not achados:
        m = re.search(r"(?<![\d.,/])(\d{1,2})\s*(?:h|hr|hrs|horas?)\b", t, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if 2 <= v <= 72:
                achados.append(v)

    # dedupe preservando ordem, mas com ints antes de tuplas para ordenação
    vistos = set()
    out: List[Any] = []
    for a in achados:
        key = a if isinstance(a, int) else tuple(a)
        if key in vistos:
            continue
        vistos.add(key)
        out.append(a)
    return out


# Frases curtas e legítimas que devem ser preservadas (não têm intervalo).
_FREQ_FRASES = (
    (r"dose\s*[uú]nica", "Dose única"),
    (r"aplica[cç][aã]o\s*[uú]nica", "Aplicação única"),
    (r"uso\s+cont[ií]nuo|cont[ií]nuo", "Uso contínuo"),
    (r"quando\s+necess[aá]rio|se\s+necess[aá]rio|s\.?o\.?s\.?", "Quando necessário"),
    (r"crit[eé]rio\s+(?:do\s+)?(?:m[eé]dico|veterin[aá]rio)", "A critério do médico-veterinário"),
)


def normalizar_frequencia(
    texto: Optional[str],
    intervalo_min: Optional[int] = None,
    intervalo_max: Optional[int] = None,
) -> Optional[str]:
    """Texto bruto de frequência -> string curta e canônica (ou None).

    Pode receber `intervalo_min`/`intervalo_max` (já parseados pelo scraper)
    como dica/fallback quando o texto não tem intervalo explícito.
    """
    t = _limpo(texto)
    # remove prefixo de via que vazou ("Via Oral: 8-12h." -> "8-12h.")
    prev = None
    while prev != t:
        prev = t
        t = _RE_PREFIXO_VIA.sub("", t).strip()
    t = t.strip(" .;:-–")

    intervalos = _coletar_intervalos(t) if t else []

    if not intervalos:
        # fallback: usa os números já estruturados pelo scraper
        if intervalo_min and intervalo_max and intervalo_min != intervalo_max:
            return f"{_fmt_intervalo(intervalo_min)} a {_fmt_intervalo(intervalo_max)}"
        if intervalo_min:
            return _fmt_intervalo(intervalo_min)
        # frases curtas legítimas
        sa = _sa(t)
        for pat, label in _FREQ_FRASES:
            if re.search(pat, sa):
                return label
        # texto curto e plausível (sem ser prosa truncada)
        if t and 2 < len(t) <= 40 and not t.endswith("-"):
            return t[0].upper() + t[1:]
        return None

    # formata cada intervalo
    partes: List[str] = []
    for it in intervalos:
        if isinstance(it, tuple):
            partes.append(f"a cada {it[0]}–{it[1]}h")
        else:
            f = _fmt_intervalo(it)
            if f:
                partes.append(f)
    # dedupe final preservando ordem
    seen = set()
    uniq = [p for p in partes if not (p in seen or seen.add(p))]
    if not uniq:
        return None
    if len(uniq) == 1:
        return uniq[0]
    return " ou ".join(uniq)


# ───────────────────────── DURAÇÃO ─────────────────────────────────────────

_RE_DUR_DIAS = re.compile(
    r"(\d{1,3})\s*(?:a|à|-|–|até|ou)\s*(\d{1,3})\s*dias?\b", re.IGNORECASE
)
_RE_DUR_DIA = re.compile(r"(?:por\s+)?(\d{1,3})\s*dias?\b", re.IGNORECASE)
_RE_DUR_SEM = re.compile(
    r"(\d{1,2})(?:\s*(?:a|à|-|–|até|ou)\s*(\d{1,2}))?\s*semanas?\b", re.IGNORECASE
)
_RE_DUR_MES = re.compile(
    r"(\d{1,2})(?:\s*(?:a|à|-|–|até|ou)\s*(\d{1,2}))?\s*m[eê]s(?:es)?\b",
    re.IGNORECASE,
)

# prosa sem número -> frase canônica curta
_DUR_FRASES = (
    (r"crit[eé]rio\s+(?:do\s+)?(?:m[eé]dico|veterin[aá]rio)|crit[eé]rio\s+m[eé]dico",
     "A critério do médico-veterinário"),
    (r"protocolo\s+m[eé]dico|de\s+acordo\s+com\s+(?:o\s+)?protocolo",
     "Conforme protocolo médico"),
    (r"orienta[cç][aã]o\s+(?:do\s+)?(?:m[eé]dico|veterin[aá]rio)|orienta[cç][aã]o\s+veterin[aá]ria",
     "Conforme orientação veterinária"),
    (r"uso\s+cont[ií]nuo|tratamento\s+cont[ií]nuo|cont[ií]nuo\s+e\s+ininterrupto",
     "Uso contínuo"),
    (r"uso\s+prolongado|longo\s+prazo", "Uso prolongado"),
    (r"dose\s*[uú]nica|aplica[cç][aã]o\s*[uú]nica", "Dose única"),
    (r"variar?\b|gravidade|avalia[cç][aã]o\s+cl[ií]nica|depende",
     "Conforme avaliação clínica"),
)


def normalizar_duracao(texto: Optional[str]) -> Optional[str]:
    """Texto bruto de duração -> frase curta e profissional (ou None)."""
    t = _limpo(texto)
    if not t:
        return None

    # 1) duração numérica explícita (pega a PRIMEIRA — descarta o resto da prosa)
    m = _RE_DUR_DIAS.search(t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a and b and a <= b <= 365:
            return f"{a} a {b} dias"
    m = _RE_DUR_SEM.search(t)
    if m:
        if m.group(2):
            return f"{int(m.group(1))} a {int(m.group(2))} semanas"
        return f"{int(m.group(1))} semana" + ("s" if int(m.group(1)) != 1 else "")
    m = _RE_DUR_MES.search(t)
    if m:
        if m.group(2):
            return f"{int(m.group(1))} a {int(m.group(2))} meses"
        return f"{int(m.group(1))} mês" if int(m.group(1)) == 1 else f"{int(m.group(1))} meses"
    m = _RE_DUR_DIA.search(t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 365:
            return f"{n} dia" if n == 1 else f"{n} dias"

    # 2) prosa sem número -> frase canônica
    sa = _sa(t)
    for pat, label in _DUR_FRASES:
        if re.search(pat, sa):
            return label

    # 3) texto curto e limpo (não truncado mid-word) -> mantém apresentável
    if 2 < len(t) <= 50 and not t.endswith("-") and re.search(r"[\.\)]\s*$|\b(dias?|semanas?|mes(?:es)?)\b", t):
        t = t.rstrip(" .;:-–")
        return t[0].upper() + t[1:] if t else None

    # 4) prosa longa/truncada sem âncora -> deixa o chamador usar fallback
    return None


# ───────────────────────── DEDUPLICAÇÃO DE LINHAS ──────────────────────────


def _num_canon(m: "re.Match") -> str:
    """'25' / '25.0' / '25,00' -> '25'  ;  '12,50' -> '12.5' (mesma chave)."""
    try:
        v = float(m.group(0).replace(",", "."))
    except ValueError:
        return m.group(0)
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _dose_canonica(dose_txt: Optional[str]) -> str:
    """Normaliza string de dose p/ comparação.

    '0,5 - 1 mg/kg' ~ '0.5-1 mg / kg' e '12,5 - 25 mg/kg' ~ '12,5 - 25,0 mg/kg'
    (números equivalentes colapsam: 25 == 25,0 == 25.00).
    """
    s = _sa(dose_txt or "")
    s = s.replace(",", ".")
    s = re.sub(r"\d+\.\d+|\d+", _num_canon, s)
    s = re.sub(r"\s*[-–a]\s*", "-", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s+", "", s)
    return s


def chave_semantica_linha(linha: dict) -> tuple:
    """Chave de deduplicação de uma linha de posologia já formatada.

    Duas linhas com a mesma dose + via + frequência + faixa de peso são a
    mesma recomendação clínica (independente da prosa de origem).
    """
    return (
        _dose_canonica(linha.get("dose")),
        _sa(linha.get("via") or ""),
        _sa(linha.get("frequencia") or ""),
        _sa((linha.get("faixa_peso") or "").replace("Sem faixa definida", "")),
    )


def consolidar_linhas(linhas: List[dict]) -> List[dict]:
    """Remove linhas de posologia semanticamente duplicadas, preservando ordem.

    Quando há duplicata, mantém a primeira mas adota a duração mais informativa
    (a que tem texto, em vez de '—').
    """
    out: List[dict] = []
    idx: dict = {}
    for ln in linhas:
        k = chave_semantica_linha(ln)
        if k in idx:
            prev = out[idx[k]]
            dur_atual = (prev.get("duracao") or "").strip()
            dur_nova = (ln.get("duracao") or "").strip()
            if (not dur_atual or dur_atual == "—") and dur_nova and dur_nova != "—":
                prev["duracao"] = ln["duracao"]
            if not prev.get("observacao") and ln.get("observacao"):
                prev["observacao"] = ln["observacao"]
            continue
        idx[k] = len(out)
        out.append(dict(ln))
    return out
