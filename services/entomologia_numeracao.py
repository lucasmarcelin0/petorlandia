"""Numeração métrica: posição de um imóvel só pela rua e pelo número.

Em Orlândia o número do imóvel é uma distância em metros: ao longo da rua, o
número cresce um por metro a partir de uma origem. Ruas e alamedas correm num
sentido da malha, avenidas e travessas no outro, e cada trecho de rua tem a sua
origem e o seu sentido (a letra "A" costuma marcar o lado). Nada disso é fixado
aqui: o ângulo da malha e, para cada rua, os trechos de numeração (origem,
sentido e letra) são aprendidos da própria base de endereços do atlas.

Serve para os números que a base não tem: vãos sem imóveis cadastrados, pontas
de rua e portarias. A previsão só vale onde a rua existe (imóvel conhecido por
perto ou traçado na malha de ruas) e é uma estimativa a conferir no campo.
"""
from __future__ import annotations

from collections import Counter
from statistics import median
import math

MX = 111320 * math.cos(math.radians(-20.72))
MY = 111320
FAMILIES = {'rua': 'ew', 'alameda': 'ew', 'avenida': 'ns', 'travessa': 'ns'}
MIN_STREET_POINTS = 8     # imóveis para uma rua informar a direção da malha
MIN_STRETCH = 4           # imóveis que concordam para um trecho de numeração valer
FIT_M = 30                # folga entre o número e a posição para dois imóveis serem do mesmo trecho
REACH_M = 300             # ao longo da rua, até onde um imóvel conhecido diz por onde ela passa
ROAD_M = 15               # folga na ponta de um trecho do traçado da rua


def family(key):
    parts = (key or '').split()
    return FAMILIES.get(parts[0]) if len(parts) == 2 else None


class Grid:
    """Trechos de numeração de cada rua, a partir de ``{rua: [{'number', 'suffix', 'point'}]}``."""

    def __init__(self, streets):
        self.theta = self._angle(streets)
        self.stretches = {}
        if self.theta is None:
            return
        self._cos, self._sin = math.cos(self.theta), math.sin(self.theta)
        tendency = Counter()
        for key, entries in streets.items():
            fam = family(key)
            if fam and len(entries) >= MIN_STRETCH:
                found = self._stretches(fam, entries)
                if found:
                    self.stretches[key] = found
                for stretch in found:
                    for member in stretch['members']:
                        tendency[(fam, member['suffix'], stretch['sign'])] += 1
        # Para que lado a letra costuma apontar em cada família de vias (ex.: "A" = números crescendo para leste).
        self.letters = {}
        for fam in ('ew', 'ns'):
            for suffix in {k[1] for k in tendency if k[0] == fam}:
                plus, minus = tendency[(fam, suffix, 1)], tendency[(fam, suffix, -1)]
                if plus + minus >= 50 and max(plus, minus) >= 4 * min(plus, minus):
                    self.letters[(fam, suffix)] = 1 if plus > minus else -1

    @staticmethod
    def _angle(streets):
        angles = []
        for key, entries in streets.items():
            if family(key) != 'ew' or len(entries) < MIN_STREET_POINTS:
                continue
            xs = [e['point'][0] * MX for e in entries]
            ys = [e['point'][1] * MY for e in entries]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            if sxx > 100 ** 2:                              # rua com extensão suficiente para ter direção
                angles.append(math.atan(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx))
        return median(angles) if len(angles) >= 3 else None

    def _stretches(self, fam, entries):
        """Agrupa os imóveis da rua que obedecem à mesma regra ``posição = origem ± número``."""
        points = []
        for entry in entries:
            along, cross = self.axes(fam, entry['point'])
            points.append({'along': along, 'cross': cross, 'number': entry['number'], 'suffix': entry.get('suffix', ''),
                           'neighborhood': entry.get('neighborhood', '')})
        found, free = [], list(points)
        while len(free) >= MIN_STRETCH:
            # A cada rodada, o maior grupo de imóveis cuja posição menos (ou mais) o número cai na mesma origem.
            best = None
            for sign in (1, -1):
                ordered = sorted(free, key=lambda p: p['along'] - sign * p['number'])
                offsets = [p['along'] - sign * p['number'] for p in ordered]
                first = 0
                for last in range(len(ordered)):
                    while offsets[last] - offsets[first] > 2 * FIT_M:
                        first += 1
                    if best is None or last - first + 1 > len(best[1]):
                        best = (sign, ordered[first:last + 1])
            sign, members = best
            if len(members) < MIN_STRETCH or len({p['number'] for p in members}) < 3:
                break
            taken = {id(p) for p in members}
            free = [p for p in free if id(p) not in taken]
            if self._drifts(sign, members):
                continue                                     # números espaçados por igual no sentido errado, não um trecho
            found.append({'sign': sign, 'origin': median(p['along'] - sign * p['number'] for p in members),
                          'members': members, 'suffix': Counter(p['suffix'] for p in members).most_common(1)[0][0],
                          'low': min(p['number'] for p in members), 'high': max(p['number'] for p in members)})
        return found

    @staticmethod
    def _drifts(sign, members):
        """Num trecho de verdade a origem não depende do número; se ela anda junto com ele, o sentido está trocado."""
        numbers = [p['number'] for p in members]
        mean = sum(numbers) / len(numbers)
        spread = sum((n - mean) ** 2 for n in numbers)
        if spread < 20 ** 2:
            return False
        origins = [p['along'] - sign * p['number'] for p in members]
        centre = sum(origins) / len(origins)
        return abs(sum((n - mean) * (o - centre) for n, o in zip(numbers, origins)) / spread) > 0.5

    @property
    def ready(self):
        return bool(self.stretches)

    def axes(self, fam, point):
        """``(ao longo, através)`` da via, em metros, para uma posição em longitude/latitude."""
        x, y = point[0] * MX, point[1] * MY
        u, v = x * self._cos + y * self._sin, -x * self._sin + y * self._cos
        return (u, v) if fam == 'ew' else (v, u)

    def point(self, fam, along, cross):
        u, v = (along, cross) if fam == 'ew' else (cross, along)
        x, y = u * self._cos - v * self._sin, u * self._sin + v * self._cos
        return (x / MX, y / MY)

    def _on_road(self, fam, along, segments):
        """Posição através do eixo onde o traçado da rua passa por ``along``; ``None`` se a rua não chega lá."""
        best = None
        for a, b in segments:
            (a1, c1), (a2, c2) = self.axes(fam, a), self.axes(fam, b)
            low, high = min(a1, a2), max(a1, a2)
            if low - ROAD_M <= along <= high + ROAD_M:
                t = min(1.0, max(0.0, (along - a1) / (a2 - a1))) if a2 != a1 else 0.0
                gap = max(0.0, low - along, along - high)
                if best is None or gap < best[0]:
                    best = (gap, c1 + t * (c2 - c1))
        return None if best is None else best[1]

    def predict(self, key, number, suffix='', segments=()):
        """Candidatos de posição para ``rua, número``, o mais sustentado primeiro.

        ``segments``: trechos ``(a, b)`` do traçado da rua em longitude/latitude, quando a malha de ruas a conhece.
        Cada candidato traz ``point``, ``near_m`` e ``near_number`` (imóvel conhecido mais próximo do mesmo trecho
        de numeração, ao longo do eixo), ``suffix`` (letra usual do trecho), ``neighborhood`` (e ``neighborhoods``,
        os bairros dos imóveis mais próximos), ``score`` (indícios pela letra) e ``by_road`` (``True`` quando só o
        traçado da rua, e não um imóvel vizinho, diz que ela passa ali).
        """
        fam = family(key)
        found = []
        for stretch in self.stretches.get(key, []) if number else ():
            along = stretch['origin'] + stretch['sign'] * number
            members = sorted(stretch['members'], key=lambda p: abs(p['along'] - along))
            near = members[0]
            local = [p for p in members if abs(p['along'] - along) <= REACH_M]
            by_road = False
            if local:
                same_side = [p for p in local if p['number'] % 2 == number % 2] or local
                cross = median(p['cross'] for p in same_side[:9])
            else:
                cross = self._on_road(fam, along, segments)
                by_road = True
                if cross is None:
                    continue                                 # a rua não tem imóvel nem traçado nessa altura
                # Imóvel conhecido já longe e traçado interrompido naquela altura: a rua não passa ali.
                if segments and abs(near['along'] - along) > 120 and self._on_road(fam, along, segments) is None:
                    continue
            hoods = Counter(p['neighborhood'] for p in members[:9] if p['neighborhood'])
            # Indícios de que este é o trecho certo: a letra do próprio trecho e o lado que a letra costuma indicar.
            score = ((3 if suffix and stretch['suffix'] == suffix else 0)
                     + (2 if suffix and self.letters.get((fam, suffix)) == stretch['sign'] else 0)
                     + (1 if not suffix and stretch['suffix'] == '' else 0))
            found.append({'point': self.point(fam, along, cross), 'near_m': round(abs(near['along'] - along)),
                          'near_number': near['number'], 'suffix': stretch['suffix'], 'by_road': by_road, 'score': score,
                          'neighborhood': hoods.most_common(1)[0][0] if hoods else '', 'neighborhoods': sorted(hoods),
                          'size': len(members)})
        return sorted(found, key=lambda c: (-c['score'], c['by_road'], c['near_m']))
