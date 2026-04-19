"""
DEMO: sugestão de dose para Malhado (Cachorro SRD) usando dados extraídos do
VetSmart para Agemoxi CL e Cefalexina.

Este script:
  1. Faz scraping dos dois medicamentos
  2. Extrai e estrutura as doses aplicando o schema DoseProtocolo proposto
  3. Renderiza o "card de sugestão" como apareceria na receita

Uso:  python scripts/demo_dose_malhado.py
"""
import sys, os, re, json, time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from importar_medicamentos_vetsmart import (  # type: ignore
    BASE_URL, LIST_URL, aguardar_e_aceitar_cookies,
    _coletar_links_da_pagina, scrape_detalhe_produto,
)
from playwright.sync_api import sync_playwright


# ─────────────────────────────────────────────────────────────────────────────
# 1. Modelo de DoseProtocolo (em memória — seria uma tabela no DB)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class DoseProtocolo:
    especie: str                           # 'CAES' | 'GATOS' | 'AMBOS'
    peso_min_kg: Optional[float] = None
    peso_max_kg: Optional[float] = None
    dose_min: Optional[float] = None
    dose_max: Optional[float] = None
    dose_unidade: str = 'MG_KG'            # MG_KG | ML_KG | MG_ANIMAL | PIPETA_ANIMAL ...
    intervalo_horas: Optional[int] = None
    duracao_min_dias: Optional[int] = None
    duracao_max_dias: Optional[int] = None
    via_administracao: Optional[str] = None
    frequencia_texto: Optional[str] = None
    duracao_texto: Optional[str] = None
    observacao: Optional[str] = None
    dose_raw_text: Optional[str] = None
    fonte: str = 'SCRAPER'                 # SCRAPER | LLM | HUMANO
    confianca: str = 'MEDIA'               # ALTA | MEDIA | BAIXA


@dataclass
class Apresentacao:
    forma: str
    nome_variante: Optional[str] = None
    concentracao_valor: Optional[float] = None
    concentracao_unidade: Optional[str] = None  # mg | mg/ml | UI/ml | %
    volume_valor: Optional[float] = None
    volume_unidade: Optional[str] = None         # un | ml | g


@dataclass
class Animal:
    name: str
    especie: str                            # 'CAES' | 'GATOS'
    peso_kg: float


# ─────────────────────────────────────────────────────────────────────────────
# 2. Parser de dose mais robusto (corrigindo os 4 bugs)
# ─────────────────────────────────────────────────────────────────────────────
def _especie_to_code(txt: str) -> str:
    t = (txt or '').lower()
    t_ascii = t.replace('ã', 'a').replace('ç', 'c')
    if ('cao' in t_ascii or 'canino' in t_ascii or 'cães' in t) and ('gato' in t_ascii or 'felino' in t_ascii):
        return 'AMBOS'
    if 'gato' in t_ascii or 'felino' in t_ascii:
        return 'GATOS'
    if 'cao' in t_ascii or 'canino' in t_ascii or 'cães' in t:
        return 'CAES'
    return 'AMBOS'


def _intervalo_para_horas(freq_texto: str) -> Optional[int]:
    """'12 / 12 horas' → 12,  '2 vezes ao dia' → 12,  'dose única' → None"""
    if not freq_texto:
        return None
    t = freq_texto.lower()
    if 'dose unica' in t.replace('ú','u') or 'dose única' in t:
        return None
    m = re.search(r'(\d+)\s*/\s*\d+\s*horas?', t)
    if m:
        return int(m.group(1))
    m = re.search(r'a\s+cada\s+(\d+)\s*horas?', t)
    if m:
        return int(m.group(1))
    m = re.search(r'a\s+cada\s+(\d+)\s*dias?', t)
    if m:
        return int(m.group(1)) * 24
    m = re.search(r'(\d+)\s*(?:x|vezes?)\s*(?:ao|por)?\s*dia', t)
    if m:
        n = int(m.group(1))
        return 24 // n if n > 0 else None
    return None


def _duracao_para_dias(dur_texto: str) -> (Optional[int], Optional[int]):
    """'7 a 10 dias' → (7, 10),  '30 dias' → (30, 30),  'até 30 dias' → (None, 30)"""
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


# Regex robusta — ACEITA espaços em mg/kg, mg / kg, mg/ kg, etc.
_RE_DOSE_MGKG = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'(mg|mcg|ml|ui)\s*/\s*kg',
    re.IGNORECASE,
)
# Ex: "0,4 mL/animal"
_RE_DOSE_ANIMAL = re.compile(
    r'(\d+(?:[,\.]\d+)?)\s*(?:[-–a]\s*(\d+(?:[,\.]\d+)?)\s*)?'
    r'(mg|mcg|ml|pipeta|gotas?|comprimidos?)\s*/\s*animal',
    re.IGNORECASE,
)

_RE_FAIXA_PESO_ATE    = re.compile(r'at[eé]\s*(\d+(?:[,\.]\d+)?)\s*kg', re.IGNORECASE)
_RE_FAIXA_PESO_ACIMA  = re.compile(r'acima\s+de\s+(\d+(?:[,\.]\d+)?)\s*kg', re.IGNORECASE)
_RE_FAIXA_PESO_ENTRE  = re.compile(
    r'entre\s+(\d+(?:[,\.]\d+)?)\s*(?:e|-|–|a)\s*(\d+(?:[,\.]\d+)?)\s*kg',
    re.IGNORECASE,
)

_RE_RUIDO = re.compile(r'(?:^|\s)(?:indica[cç][aã]o:\s*0|0\s*(?:mg|ml)\b)(?:\s|$)', re.IGNORECASE)


def _f(txt: str) -> float:
    return float(txt.replace(',', '.'))


def extrair_protocolos(
    dosagem_raw: str,
    frequencia_texto: str,
    duracao_texto: str,
    via: str,
    especies_str: str,
) -> List[DoseProtocolo]:
    """Constrói 1+ DoseProtocolos a partir do texto bruto da seção 'Administração e doses'."""
    if not dosagem_raw:
        return []

    protocolos: List[DoseProtocolo] = []
    intervalo = _intervalo_para_horas(frequencia_texto)
    dur_min, dur_max = _duracao_para_dias(duracao_texto)
    especie_default = _especie_to_code(especies_str)

    # Divide o texto em "blocos" por linha
    linhas = [l.strip() for l in re.split(r'[\n.;]+', dosagem_raw) if l.strip()]
    esp_ctx = especie_default
    peso_min_ctx, peso_max_ctx = None, None

    for linha in linhas:
        # Pula linhas claramente ruído (usa regex com word boundary para
        # evitar que "50 mg" seja filtrado como se contivesse "0 mg")
        if _RE_RUIDO.search(linha):
            continue

        # Detecta mudança de contexto de espécie
        code_linha = _especie_to_code(linha)
        if code_linha != especie_default:
            esp_ctx = code_linha

        # Detecta contexto de peso (só padrões com preposição — corrige bug #3)
        m = _RE_FAIXA_PESO_ENTRE.search(linha)
        if m:
            peso_min_ctx, peso_max_ctx = _f(m.group(1)), _f(m.group(2))
        else:
            m = _RE_FAIXA_PESO_ATE.search(linha)
            if m:
                peso_min_ctx, peso_max_ctx = 0.0, _f(m.group(1))
            else:
                m = _RE_FAIXA_PESO_ACIMA.search(linha)
                if m:
                    peso_min_ctx, peso_max_ctx = _f(m.group(1)), None

        # Extrai dose na linha
        m = _RE_DOSE_MGKG.search(linha)
        if m:
            dose_min = _f(m.group(1))
            dose_max = _f(m.group(2)) if m.group(2) else dose_min
            unidade_txt = m.group(3).lower()
            un_map = {'mg':'MG_KG','mcg':'MCG_KG','ml':'ML_KG','ui':'UI_KG'}
            protocolos.append(DoseProtocolo(
                especie=esp_ctx,
                peso_min_kg=peso_min_ctx,
                peso_max_kg=peso_max_ctx,
                dose_min=dose_min, dose_max=dose_max,
                dose_unidade=un_map.get(unidade_txt, 'MG_KG'),
                intervalo_horas=intervalo,
                duracao_min_dias=dur_min, duracao_max_dias=dur_max,
                via_administracao=via,
                frequencia_texto=frequencia_texto,
                duracao_texto=duracao_texto,
                observacao=(linha[:300] if len(linha) > 30 else None),
                dose_raw_text=linha,
                fonte='SCRAPER',
                confianca='MEDIA',
            ))
            continue

        m = _RE_DOSE_ANIMAL.search(linha)
        if m:
            dose_min = _f(m.group(1))
            dose_max = _f(m.group(2)) if m.group(2) else dose_min
            unidade_txt = m.group(3).lower()
            un_map = {'mg':'MG_ANIMAL','ml':'ML_ANIMAL','mcg':'MCG_ANIMAL',
                      'pipeta':'PIPETA_ANIMAL','gota':'GOTAS_ANIMAL','gotas':'GOTAS_ANIMAL',
                      'comprimido':'COMPRIMIDOS_ANIMAL','comprimidos':'COMPRIMIDOS_ANIMAL'}
            protocolos.append(DoseProtocolo(
                especie=esp_ctx,
                peso_min_kg=peso_min_ctx, peso_max_kg=peso_max_ctx,
                dose_min=dose_min, dose_max=dose_max,
                dose_unidade=un_map.get(unidade_txt, 'MG_ANIMAL'),
                intervalo_horas=intervalo,
                duracao_min_dias=dur_min, duracao_max_dias=dur_max,
                via_administracao=via,
                frequencia_texto=frequencia_texto,
                duracao_texto=duracao_texto,
                dose_raw_text=linha,
                fonte='SCRAPER',
                confianca='MEDIA',
            ))

    # Dedup: mesma (especie, peso_min, peso_max, dose_min, dose_max, unidade)
    vistos, unicos = set(), []
    for p in protocolos:
        chave = (p.especie, p.peso_min_kg, p.peso_max_kg, p.dose_min, p.dose_max, p.dose_unidade)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(p)
    return unicos


# ─────────────────────────────────────────────────────────────────────────────
# 3. Parser de apresentação (estrutura valor/unidade/volume)
# ─────────────────────────────────────────────────────────────────────────────
_RE_CONC_MG = re.compile(r'(\d+(?:[,\.]\d+)?)\s*(mg|mcg|g|ui|%)\b', re.IGNORECASE)
_RE_CONC_MGML = re.compile(r'(\d+(?:[,\.]\d+)?)\s*(mg|mcg|ui)\s*/\s*ml\b', re.IGNORECASE)
_RE_VOLUME = re.compile(r'\((\d+(?:[,\.]\d+)?)\s*(ml|un|g|kg|l|mg)\b', re.IGNORECASE)


def estruturar_apresentacao(forma_raw: str, conc_raw: str) -> Apresentacao:
    ap = Apresentacao(forma=forma_raw or '')
    if not conc_raw:
        return ap
    # volume entre parênteses
    m = _RE_VOLUME.search(conc_raw)
    if m:
        ap.volume_valor = _f(m.group(1))
        ap.volume_unidade = m.group(2).lower()
    # concentração mg/ml (checa antes de mg só)
    m = _RE_CONC_MGML.search(conc_raw)
    if m:
        ap.concentracao_valor = _f(m.group(1))
        ap.concentracao_unidade = f"{m.group(2).lower()}/ml"
    else:
        m = _RE_CONC_MG.search(conc_raw)
        if m:
            ap.concentracao_valor = _f(m.group(1))
            ap.concentracao_unidade = m.group(2).lower()
    # "nome variante" = texto antes da concentração
    parte_nome = re.sub(r'\s*\([^)]*\)\s*$', '', conc_raw).strip()
    parte_nome = re.sub(r'\s*\d+(?:[,\.]\d+)?\s*(mg|mcg|g|ui|%|ml)[\s/]*\w*\s*$', '', parte_nome, flags=re.IGNORECASE).strip()
    if parte_nome:
        ap.nome_variante = parte_nome
    return ap


# ─────────────────────────────────────────────────────────────────────────────
# 4. Sugestão de dose
# ─────────────────────────────────────────────────────────────────────────────
def sugerir_dose(protocolos: List[DoseProtocolo], animal: Animal):
    candidatos = [
        p for p in protocolos
        if (p.especie == animal.especie or p.especie == 'AMBOS')
        and (p.peso_min_kg is None or animal.peso_kg >= p.peso_min_kg)
        and (p.peso_max_kg is None or animal.peso_kg <= p.peso_max_kg)
    ]
    if not candidatos:
        return None

    # mais específico (menor range de peso)
    def largura(p):
        a = p.peso_min_kg or 0
        b = p.peso_max_kg or 9999
        return b - a
    proto = min(candidatos, key=largura)

    peso = animal.peso_kg
    un = proto.dose_unidade
    dose_unit_out = None
    dose_min_calc = proto.dose_min
    dose_max_calc = proto.dose_max

    if un == 'MG_KG':
        dose_min_calc = proto.dose_min * peso
        dose_max_calc = proto.dose_max * peso
        dose_unit_out = 'mg'
    elif un == 'ML_KG':
        dose_min_calc = proto.dose_min * peso
        dose_max_calc = proto.dose_max * peso
        dose_unit_out = 'mL'
    elif un == 'MCG_KG':
        dose_min_calc = proto.dose_min * peso
        dose_max_calc = proto.dose_max * peso
        dose_unit_out = 'mcg'
    elif un == 'UI_KG':
        dose_min_calc = proto.dose_min * peso
        dose_max_calc = proto.dose_max * peso
        dose_unit_out = 'UI'
    elif un == 'MG_ANIMAL':
        dose_unit_out = 'mg'
    elif un == 'ML_ANIMAL':
        dose_unit_out = 'mL'
    elif un == 'PIPETA_ANIMAL':
        dose_unit_out = 'pipeta(s)'
    elif un == 'COMPRIMIDOS_ANIMAL':
        dose_unit_out = 'comprimido(s)'
    elif un == 'GOTAS_ANIMAL':
        dose_unit_out = 'gota(s)'

    return {
        'protocolo': proto,
        'dose_min': dose_min_calc,
        'dose_max': dose_max_calc,
        'dose_unit_out': dose_unit_out,
    }


def converter_para_apresentacao(dose_mg: float, ap: Apresentacao) -> Optional[str]:
    if not ap.concentracao_valor:
        return None
    if ap.concentracao_unidade == 'mg':
        n = dose_mg / ap.concentracao_valor
        return f"{n:.2g} {ap.forma} de {ap.concentracao_valor:g} mg"
    if ap.concentracao_unidade in ('mg/ml','mcg/ml','ui/ml'):
        ml = dose_mg / ap.concentracao_valor
        return f"{ml:.2f} mL"
    return None


def render_card(med_nome: str, fabricante: str, principio: str,
                apresentacoes: List[Apresentacao],
                sug: Optional[dict], animal: Animal):
    print(f"\n┌─ 💡 Sugestão de dose ─ {med_nome} ─ ({fabricante}) ─────────")
    print(f"│ Princípio ativo: {principio}")
    print(f"│ Animal: {animal.name} — {animal.especie} — {animal.peso_kg} kg")
    if not sug:
        print(f"│ ⚠ Sem protocolo de dose cadastrado para esta combinação.")
        print(f"│   → preencher manualmente")
        print(f"└────────────────────────────────────────────────────────────")
        return
    p = sug['protocolo']
    un_legivel = {
        'MG_KG':'mg/kg', 'MCG_KG':'mcg/kg', 'ML_KG':'mL/kg', 'UI_KG':'UI/kg',
        'MG_ANIMAL':'mg/animal', 'ML_ANIMAL':'mL/animal',
        'PIPETA_ANIMAL':'pipeta/animal', 'COMPRIMIDOS_ANIMAL':'cp/animal',
    }.get(p.dose_unidade, p.dose_unidade)

    if sug['dose_min'] == sug['dose_max']:
        dose_txt = f"{sug['dose_min']:.1f} {sug['dose_unit_out']}"
    else:
        dose_txt = f"{sug['dose_min']:.1f}–{sug['dose_max']:.1f} {sug['dose_unit_out']}"
    faixa = f"({p.dose_min:g}–{p.dose_max:g} {un_legivel})" if p.dose_min != p.dose_max else f"({p.dose_min:g} {un_legivel})"

    via = (p.via_administracao or '—').lower()
    freq = (f"a cada {p.intervalo_horas}h" if p.intervalo_horas else (p.frequencia_texto or '—'))
    if p.duracao_min_dias and p.duracao_max_dias and p.duracao_min_dias != p.duracao_max_dias:
        dur = f"por {p.duracao_min_dias}–{p.duracao_max_dias} dias"
    elif p.duracao_max_dias:
        dur = f"por até {p.duracao_max_dias} dias"
    elif p.duracao_min_dias:
        dur = f"por {p.duracao_min_dias} dias"
    else:
        dur = p.duracao_texto or ''

    print(f"│ Dose sugerida: {dose_txt} {faixa}")
    print(f"│ Via: {via}   |   Frequência: {freq}   |   Duração: {dur}")
    print(f"│")
    print(f"│ Equivalência por apresentação:")
    for ap in apresentacoes:
        dose_media_mg = (sug['dose_min'] + sug['dose_max']) / 2 if sug['dose_unit_out'] == 'mg' else None
        equiv = converter_para_apresentacao(dose_media_mg, ap) if dose_media_mg else None
        desc = f"{ap.forma}"
        if ap.concentracao_valor:
            desc += f" {ap.concentracao_valor:g} {ap.concentracao_unidade}"
        if ap.volume_valor:
            desc += f" ({ap.volume_valor:g} {ap.volume_unidade})"
        if equiv:
            print(f"│   • {desc:<40s} → {equiv} por administração")
        else:
            print(f"│   • {desc}")
    print(f"│")
    print(f"│ [Protocolo: espécie={p.especie}, peso {p.peso_min_kg}–{p.peso_max_kg} kg, "
          f"fonte={p.fonte}, confiança={p.confianca}]")
    if p.observacao:
        print(f"│ Obs: {p.observacao[:200]}")
    print(f"└──────────────────────────────────────────────────────────────")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
BUSCAS = [
    ('agemoxi', 'CL'),           # só Agemoxi CL, não LA
    ('rilexine', 'palat'),       # Rilexine Palatável (Virbac) — cefalexina
    ('cefaseptin', None),        # Cefaseptin (Vetoquinol) — cefalexina
]


def encontrar_na_lista(page, termo, sub_filtro, max_pag=61):
    ids = set()
    for n in range(1, max_pag + 1):
        page.goto(f"{LIST_URL}/{n}", wait_until="networkidle", timeout=45000)
        try:
            page.wait_for_selector("a[href*='/produto/']", timeout=8000)
        except Exception:
            return []
        links = _coletar_links_da_pagina(page, ids)
        for l in links:
            nome = (l['nome'] or '').lower()
            if termo in nome:
                if sub_filtro and sub_filtro.lower() not in nome:
                    continue
                return l
        time.sleep(0.3)
    return None


def main():
    malhado = Animal(name="Malhado", especie="CAES", peso_kg=10.0)
    print(f"═══ Malhado (Cachorro SRD, {malhado.peso_kg} kg — peso de referência,"
          f" pois peso real no banco está NULL) ═══")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="pt-BR", viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        aguardar_e_aceitar_cookies(page, timeout=8000)

        for termo, sub in BUSCAS:
            print(f"\n▶ Buscando '{termo}'" + (f" (filtro: {sub})" if sub else ""))
            info = encontrar_na_lista(page, termo, sub)
            if not info:
                print(f"  ✗ não encontrado")
                continue
            print(f"  → {info['nome']}  ({info['url']})")
            prod = scrape_detalhe_produto(page, info)

            # Estrutura apresentações
            aps_estruturadas = [
                estruturar_apresentacao(ap.get('forma',''), ap.get('concentracao',''))
                for ap in prod.apresentacoes
            ]

            # Extrai protocolos estruturados a partir da dosagem_recomendada (texto rico)
            protocolos = extrair_protocolos(
                dosagem_raw=prod.dosagem_recomendada or '',
                frequencia_texto=prod.frequencia or '',
                duracao_texto=prod.duracao_tratamento or '',
                via=prod.via_administracao or '',
                especies_str=prod.especies or '',
            )

            print(f"\n── DADOS ESTRUTURADOS EXTRAÍDOS ──────────────────────")
            print(f"Apresentações ({len(aps_estruturadas)}):")
            for ap in aps_estruturadas:
                print(f"  • forma={ap.forma!r} "
                      f"variante={ap.nome_variante!r} "
                      f"conc={ap.concentracao_valor}{ap.concentracao_unidade or ''} "
                      f"vol={ap.volume_valor}{ap.volume_unidade or ''}")
            print(f"\nProtocolos de dose ({len(protocolos)}):")
            for i, p in enumerate(protocolos, 1):
                print(f"  [{i}] especie={p.especie}  peso={p.peso_min_kg}–{p.peso_max_kg}kg "
                      f"dose={p.dose_min}–{p.dose_max} {p.dose_unidade}  "
                      f"intervalo={p.intervalo_horas}h  duração={p.duracao_min_dias}–{p.duracao_max_dias}d")

            # Renderiza card para Malhado
            sug = sugerir_dose(protocolos, malhado)
            render_card(
                med_nome=prod.nome,
                fabricante=prod.fabricante or '—',
                principio=prod.principio_ativo or '—',
                apresentacoes=aps_estruturadas,
                sug=sug,
                animal=malhado,
            )

        browser.close()


if __name__ == "__main__":
    main()
