"""Quanto da lista de vacinação o atlas consegue posicionar.

Recebe só rua, número e bairro de cada linha (sem nome de tutor nem telefone) e diz, para cada
endereço, se o atlas tem:
  * ``ponto``   — a casa, com posição cadastrada (dá para ordenar a visita pelo mapa);
  * ``rua``     — a rua, mas não aquele número (ordena pela rua, não pela casa);
  * ``nenhum``  — nada que case (fica na regra antiga de texto).

Nenhuma posição é estimada: o que não está cadastrado aparece como não encontrado.
"""
from __future__ import annotations

import re

from services import entomologia_atlas_editor as editor
from services import entomologia_atlas_search as atlas_search

MAX_ROWS = 600            # por chamada: cada busca percorre o índice inteiro
MAX_LISTED = 400          # endereços não resolvidos devolvidos na resposta


def _clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _street(value):
    """Abreviações da planilha ("R. 6", "Trav. 2", "Al. A") viram o nome que o atlas usa."""
    text = _clean(value)
    text = re.sub(r'^(?:r|rua)\.?\s+', 'Rua ', text, flags=re.I)
    text = re.sub(r'^(?:trav|tv)\.?\s+', 'Travessa ', text, flags=re.I)
    text = re.sub(r'^(?:al|alam)\.?\s+', 'Alameda ', text, flags=re.I)
    return text


def _located(item):
    return bool(item.get('located')) and bool((item.get('feature') or {}).get('geometry'))


def _house_match(item, street_norm, number):
    """O resultado é mesmo "<rua>, <número>" (e não uma rua que só cita o número)."""
    props = (item.get('feature') or {}).get('properties') or {}
    text = editor.search_text(f"{props.get('name', '')} {props.get('address', '')}")
    return re.search(r'\b' + re.escape(street_norm) + r'[,\s]+0*' + re.escape(number) + r'\b', text) is not None


def status_of(street, number):
    street = _street(street)
    if not street:
        return 'sem_rua'
    street_norm = editor.search_text(street)
    digits = re.search(r'\d+', _clean(number))
    if digits:
        num = str(int(digits.group()))
        for item in atlas_search.search(f'{street} {num}', False):
            geometry = ((item.get('feature') or {}).get('geometry') or {}).get('type')
            if _located(item) and geometry == 'Point' and _house_match(item, street_norm, num):
                return 'ponto'
    if any(_located(item) for item in atlas_search.search(street, False)):
        return 'rua'
    return 'nenhum'


def coverage(rows):
    """``rows``: [{linha, rua, numero, bairro}]. Devolve totais, por bairro e os não resolvidos."""
    rows = list(rows or [])[:MAX_ROWS]
    totals = {'ponto': 0, 'rua': 0, 'nenhum': 0, 'sem_rua': 0}
    by_neighborhood, unresolved = {}, []
    for row in rows:
        status = status_of(row.get('rua'), row.get('numero'))
        totals[status] += 1
        name = _clean(row.get('bairro')) or 'NÃO INFORMADO'
        bucket = by_neighborhood.setdefault(name, {'total': 0, 'ponto': 0, 'rua': 0, 'nenhum': 0, 'sem_rua': 0})
        bucket['total'] += 1
        bucket[status] += 1
        if status != 'ponto' and len(unresolved) < MAX_LISTED:
            unresolved.append({'linha': row.get('linha'), 'rua': _street(row.get('rua')),
                               'numero': _clean(row.get('numero')), 'situacao': status})
    return {'total': len(rows), **totals, 'por_bairro': by_neighborhood, 'nao_resolvidos': unresolved,
            'cortado': len(rows) >= MAX_ROWS}
