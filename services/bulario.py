"""Serviço de sugestão de dose a partir do bulário.

Usado pelo endpoint /api/bulario/sugerir-dose e por qualquer outro caller
que precise propor uma dose para um animal específico.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List


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


def sugerir_dose(medicamento, animal) -> Optional[Dict[str, Any]]:
    """Retorna um dict com a sugestão de dose, ou None se não houver protocolo
    aplicável / peso do animal desconhecido.

    Formato do retorno:
      {
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
        'apresentacoes': [
            {'id': 3, 'descricao': 'comprimido 250 mg (10 un)',
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

    # Filtra por espécie + faixa de peso
    def _aplica(p):
        p_code = (p.especie_code or '').upper() or None
        if p_code is None:
            # fallback: se não tem especie_code, tenta inferir de p.especie textual
            t = (p.especie or '').lower().replace('ã', 'a').replace('ç', 'c')
            if 'cao' in t or 'canino' in t or 'cães' in (p.especie or '').lower():
                p_code = 'AMBOS' if 'gato' in t or 'felino' in t else 'CAES'
            elif 'gato' in t or 'felino' in t:
                p_code = 'GATOS'
            else:
                p_code = 'AMBOS'
        if not (p_code == 'AMBOS' or p_code == esp_code):
            return False
        if p.peso_min_kg is not None and peso < float(p.peso_min_kg):
            return False
        if p.peso_max_kg is not None and peso > float(p.peso_max_kg):
            return False
        # Exige dose numérica para poder calcular
        if p.dose_min is None or p.dose_unidade is None:
            return False
        return True

    candidatos = [p for p in protos if _aplica(p)]
    if not candidatos:
        return None

    proto = min(candidatos, key=_largura_faixa)

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

        equiv = None
        if dose_unit_out == 'mg' and ap.concentracao_valor and ap.concentracao_unidade:
            cv = float(ap.concentracao_valor)
            un_ap = (ap.concentracao_unidade or '').lower()
            if un_ap == 'mg':
                n = dose_media / cv
                equiv = f"{_fmt(n)} × {ap.forma} de {_fmt(cv)} mg por administração"
            elif un_ap in ('mg/ml', 'mcg/ml'):
                ml = dose_media / cv
                equiv = f"{_fmt(ml)} mL por administração"
        elif dose_unit_out == 'mL' and ap.concentracao_unidade == 'mg/ml':
            # dose em mL já é direta
            pass

        apres_info.append({
            'id': ap.id,
            'descricao': desc,
            'equivalencia': equiv,
        })

    return {
        'protocolo_id':      proto.id,
        'especie':           proto.especie,
        'peso_kg':           peso,
        'dose_min':          dose_calc_min,
        'dose_max':          dose_calc_max,
        'dose_unit_out':     dose_unit_out,
        'dose_exibir':       dose_exibir,
        'faixa_texto':       faixa_texto,
        'via':               proto.via or medicamento.via_administracao or '',
        'intervalo_horas':   proto.intervalo_horas,
        'frequencia_texto':  freq_texto,
        'duracao_min_dias':  proto.duracao_min_dias,
        'duracao_max_dias':  proto.duracao_max_dias,
        'duracao_texto':     dur_texto,
        'apresentacoes':     apres_info,
        'fonte':             proto.fonte or 'SCRAPER',
        'confianca':         proto.confianca or 'MEDIA',
        'observacao':        proto.observacao,
    }
