"""Malha viária compacta para traçar rotas no navegador.

Sai dos trechos de rua do OpenStreetMap que já fazem parte do atlas
(``atlas-referencias/lugares.json``). O cálculo do caminho acontece no
navegador: nenhum endereço, paciente ou ponto da rota é enviado a um serviço
externo de rotas.

Formato (inteiros em micrograus, para a resposta ficar pequena):
    {"v": 1, "nodes": [x0, y0, x1, y1, ...], "edges": [a0, b0, a1, b1, ...]}
``nodes`` guarda longitude e latitude de cada ponto; ``edges`` guarda pares de
índices de pontos ligados por um trecho de rua.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import math

MICRO = 1_000_000
# Ilhas de ruas a menos disso uma da outra são ligadas por um trecho curto: o OpenStreetMap
# desenha muitos cruzamentos (e a ligação com rodovias) sem um ponto em comum, e sem isso a
# rota entre duas ruas de verdade cairia em linha reta.
BRIDGE_METERS = 40


def _lines(geometry):
    if not geometry:
        return
    kind = geometry.get('type')
    if kind == 'LineString':
        yield geometry['coordinates']
    elif kind == 'MultiLineString':
        yield from geometry['coordinates']
    elif kind == 'GeometryCollection':
        for part in geometry.get('geometries', []):
            yield from _lines(part)


def build(features):
    """Monta a malha a partir de feições GeoJSON; só linhas viram trechos de rua."""
    index, nodes, seen, edges = {}, [], set(), []

    def node(position):
        key = (round(position[0] * MICRO), round(position[1] * MICRO))
        found = index.get(key)
        if found is None:
            found = index[key] = len(index)
            nodes.extend(key)
        return found

    for feature in features:
        for line in _lines(feature.get('geometry')):
            previous = None
            for position in line:
                current = node(position)
                if previous is not None and previous != current:
                    pair = (previous, current) if previous < current else (current, previous)
                    if pair not in seen:
                        seen.add(pair)
                        edges.extend(pair)
                previous = current
    edges.extend(_bridges(nodes, edges))
    return {'v': 1, 'nodes': nodes, 'edges': edges}


def _meters(nodes, a, b):
    lat = (nodes[2 * a + 1] + nodes[2 * b + 1]) / 2 / MICRO
    dx = (nodes[2 * a] - nodes[2 * b]) / MICRO * 111320 * math.cos(math.radians(lat))
    dy = (nodes[2 * a + 1] - nodes[2 * b + 1]) / MICRO * 110574
    return math.hypot(dx, dy)


def _bridges(nodes, edges):
    """Pares de pontos que ligam ilhas vizinhas (o par mais curto de cada par de ilhas)."""
    count = len(nodes) // 2
    parent = list(range(count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(0, len(edges), 2):
        parent[find(edges[i])] = find(edges[i + 1])
    cell = 0.0005 * MICRO                                  # ~55 m: maior que BRIDGE_METERS
    grid = defaultdict(list)
    for i in range(count):
        grid[(nodes[2 * i] // cell, nodes[2 * i + 1] // cell)].append(i)
    best = {}
    for i in range(count):
        cx, cy = nodes[2 * i] // cell, nodes[2 * i + 1] // cell
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((cx + dx, cy + dy), ()):
                    if j <= i or find(i) == find(j):
                        continue
                    distance = _meters(nodes, i, j)
                    if distance > BRIDGE_METERS:
                        continue
                    key = tuple(sorted((find(i), find(j))))
                    if key not in best or distance < best[key][0]:
                        best[key] = (distance, i, j)
    added = []
    for distance, i, j in sorted(best.values()):           # do mais curto: nunca liga em ciclo
        if find(i) != find(j):
            parent[find(i)] = find(j)
            added.extend((i, j))
    return added


@lru_cache(maxsize=1)
def street_network():
    """(corpo JSON, etiqueta). Os dados de referência só mudam com uma nova publicação."""
    from services import entomologia_atlas_editor as editor
    graph = build(editor.references()['features'])
    body = json.dumps(graph, separators=(',', ':'))
    return body, hashlib.sha256(body.encode()).hexdigest()[:24]
