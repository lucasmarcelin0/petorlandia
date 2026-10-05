"""Casos de dengue da planilha posicionados só com os endereços do próprio atlas.

A camada "Dengue Automatizados" é refeita a partir da planilha Arboviroses: cada
linha vira um registro, numa pasta por mês de início dos sintomas, e o endereço
digitado é procurado na base de endereços que o atlas já guarda (CNEFE do IBGE,
com as correções da equipe, e as casas dos croquis dos condomínios). Nenhum
endereço sai para um geocodificador externo, e nome, telefone e nascimento do
paciente não entram na camada.

Cada registro diz como a posição foi obtida e a que distância ficou do marcador
manual da camada Casos Dengue, para a equipe medir a automação antes de confiar
nela. Posições que a equipe corrigir no editor são mantidas nas atualizações.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from statistics import median
import math
import re

from services import entomologia_atlas as atlas
from services.entomologia_atlas import normalize

KEY = 'auto-dengue'
TITLE = 'Dengue Automatizados'
COLOR = '#ff5d8f'
VERSION = 1
MANUAL_TITLE = 'Casos Dengue'

WINDOW = 60          # diferença de numeração até onde um imóvel da mesma rua serve de referência
ZONE_LINK_M = 180    # referências mais afastadas que isso são outro trecho com a mesma numeração
MAX_GAP = 120        # maior intervalo de numeração aceito para interpolar
MAX_SPAN_M = 300     # maior distância entre os dois imóveis usados na interpolação
NEIGHBOR = 30        # sem imóvel dos dois lados: vale o vizinho mais próximo até esta diferença
BLOCK_REACH_M = 15   # o endereço do CNEFE fica na calçada: vale a quadra encostada até esta distância
BLOCK_MARGIN_M = 3   # ... desde que a segunda quadra mais próxima esteja pelo menos isto mais longe
MX = 111320 * math.cos(math.radians(-20.72))
MY = 111320

MONTH_NAMES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto',
               'Setembro', 'Outubro', 'Novembro', 'Dezembro']
STREET_KINDS = {'rua': 'rua', 'r': 'rua', 'avenida': 'avenida', 'av': 'avenida', 'avn': 'avenida',
                'alameda': 'alameda', 'al': 'alameda', 'alam': 'alameda',
                'travessa': 'travessa', 'tv': 'travessa', 'trav': 'travessa', 'tr': 'travessa'}
NUMBER_MARKS = ('n', 'no', 'num', 'numero')
CONDOMINIUMS = {'quebec': 'Quebec', 'quebeck': 'Quebec', 'torino': 'Torino'}
NEIGHBORHOOD_NOISE = {'jardim', 'jd', 'conj', 'conjunto', 'hab', 'habitacional', 'dr', 'vila', 'vl', 'parque',
                      'residencial', 'res', 'condominio', 'cond', 'de', 'da', 'do', 'das', 'dos', 'e'}
RESULT_LABELS = {'positive': 'Positivo', 'negative': 'Negativo', 'pending': 'Pendente / suspeito',
                 'unknown': 'Sem resultado reconhecido'}
METHOD_LABELS = {'exato': 'Endereço exato', 'exato_sufixo': 'Número exato, letra diferente',
                 'interpolado': 'Interpolado entre vizinhos', 'vizinho': 'Vizinho mais próximo',
                 'condominio': 'Casa de condomínio', 'equipe': 'Posição ajustada pela equipe',
                 'sem_posicao': 'Sem posição'}
SHEET_HEADERS = {1: 'agravo/doenca', 2: 'n ficha epidemiologica', 3: 'sinan', 5: 'data notificacao',
                 6: 'data inicio sintomas', 9: 'endereco', 10: 'bairro', 15: 'tipo de exame',
                 16: 'resultado', 17: 'resultado final', 18: 'classificacao do caso'}
NO_STREET = 'Endereço sem logradouro reconhecido (zona rural, chácara ou texto livre).'


def distance_m(a, b):
    return math.hypot((a[0] - b[0]) * MX, (a[1] - b[1]) * MY)


# --------------------------------------------------------------------------
# Leitura do endereço digitado
# --------------------------------------------------------------------------

def _tokens(text):
    text = re.sub(r'[º°ª]', '', str(text or ''))
    text = re.sub(r'[.,;:()/\\|]', ' ', normalize(text))
    text = re.sub(r'(\d)\s*-\s*([a-z])\b', r'\1\2', text)           # 351-A, 351 - a
    return text.split()


def street_key(text):
    """"Rua 08", "R. Oito" e "RUA 8" viram a mesma chave; devolve ``None`` sem tipo de logradouro."""
    tokens = _tokens(text)
    if not tokens or tokens[0] not in STREET_KINDS:
        return None
    from services.entomologia_cnefe import street_number
    name = street_number(' '.join(tokens[1:]))
    name = ' '.join(str(int(t)) if t.isdigit() else t for t in name.split())
    return (STREET_KINDS[tokens[0]] + ' ' + name).strip() if name else None


def _house_number(text):
    match = re.fullmatch(r'(\d{1,6})([a-z]{0,2})', normalize(text).replace('-', '').replace(' ', ''))
    return (int(match[1]), match[2]) if match and int(match[1]) else None


def _is_number(token):
    return re.fullmatch(r'(?:n|no|num)?\d{1,6}[a-z]{0,2}', token) is not None


def parse_address(text):
    """Logradouro, número e letra de um endereço digitado; ``None`` se não há o que procurar.

    Do complemento ficam só as partes estruturadas (casa, apartamento, condomínio):
    texto livre pode trazer nome de pessoa e não entra na camada.
    """
    tokens = _tokens(text)
    if not tokens:
        return None
    joined = ' '.join(tokens)
    condo = next((label for word, label in CONDOMINIUMS.items() if re.search(r'\b' + word + r'\b', joined)), None)
    other = None if condo else re.search(r'\bcond(?:ominio)? ([a-z]{3,20})\b', joined)
    house = re.search(r'\bcasa (\d{1,4})\b', joined)
    apartment = re.search(r'\b(?:apto|apartamento|ap|apt) (\d{1,5}[a-z]?)\b', joined)
    parsed = {'street': None, 'street_label': '', 'number': None, 'suffix': '', 'condominium': condo,
              'other_condominium': other[1].title() if other else '', 'house': int(house[1]) if house else None,
              'complement': ' · '.join(p for p in (
                  'Condomínio ' + (condo or other[1].title()) if condo or other else '',
                  'Casa ' + house[1] if house else '', 'Apto ' + apartment[1].upper() if apartment else '') if p)}
    if tokens[0] in STREET_KINDS:
        kind, rest, index, name = STREET_KINDS[tokens[0]], tokens[1:], 0, []
        marked = lambda i: rest[i] in NUMBER_MARKS and i + 1 < len(rest) and rest[i + 1][:1].isdigit()
        if rest and (rest[0].isdigit() or re.fullmatch(r'[a-z]', rest[0])):
            name, index = [rest[0]], 1                               # Rua 8, Avenida N
        else:
            while index < len(rest) and not _is_number(rest[index]) and not marked(index):
                name.append(rest[index])
                index += 1
        if index < len(rest) and marked(index):
            index += 1
        parsed['street'] = street_key(kind + ' ' + ' '.join(name)) if name else None
        if parsed['street']:
            parsed['street_label'] = ' '.join(t.upper() if len(t) == 1 else t.title() for t in parsed['street'].split())
        if parsed['street'] and index < len(rest):
            number = re.fullmatch(r'(?:n|no|num)?(\d{1,6})([a-z]{0,2})', rest[index])
            if number and int(number[1]):
                parsed['number'], parsed['suffix'] = int(number[1]), number[2]
                if not number[2] and index + 1 < len(rest) and re.fullmatch(r'[a-z]', rest[index + 1]):
                    parsed['suffix'] = rest[index + 1]
    if not parsed['street'] and not parsed['complement']:
        return None
    return parsed


def address_label(parsed):
    if not parsed:
        return ''
    number = (str(parsed['number']) + ('-' + parsed['suffix'].upper() if parsed['suffix'] else '')) if parsed['number'] else ''
    street = (parsed['street_label'] + (', ' + number if number else ', sem número')) if parsed['street'] else ''
    return ' · '.join(p for p in (street, parsed['complement']) if p)


def neighborhood_tokens(value):
    text = re.sub(r'\b1o?\b', 'primeiro', normalize(value))
    return {t for t in re.split(r'[^a-z0-9]+', text) if t and t not in NEIGHBORHOOD_NOISE}


def same_neighborhood(a, b):
    """Comparação frouxa: a planilha e o CNEFE escrevem os bairros de formas diferentes."""
    a, b = neighborhood_tokens(a), neighborhood_tokens(b)
    return bool(a and b) and len(a & b) * 2 > min(len(a), len(b))


# --------------------------------------------------------------------------
# Endereços que o atlas já conhece
# --------------------------------------------------------------------------

class AddressIndex:
    """Imóveis numerados com posição (CNEFE e correções da equipe) e casas dos condomínios."""

    def __init__(self, layers):
        self.streets = defaultdict(list)
        self.houses = defaultdict(list)
        for layer in layers.values():
            kind = layer.get('origin', {}).get('type')
            if layer.get('deleted') or kind not in ('cnefe', 'condominium'):
                continue
            for feature in layer['features']:
                geometry, p = feature.get('geometry'), feature.get('properties', {})
                if not geometry or geometry.get('type') != 'Point':
                    continue
                number = _house_number(p.get('house_number', ''))
                if not number:
                    continue
                point = tuple(geometry['coordinates'][:2])
                if kind == 'condominium':
                    self.houses[(normalize(p.get('condominium')), number[0])].append(
                        {'id': str(feature['id']), 'point': point, 'neighborhood': '',
                         'block': str(p.get('block') or ''), 'sector': str(p.get('sector') or '')})
                    continue
                key = street_key(p.get('street', ''))
                if key:
                    self.streets[key].append({'id': str(feature['id']), 'number': number[0], 'suffix': number[1],
                                              'point': point, 'neighborhood': p.get('neighborhood', '')})

    @property
    def size(self):
        return sum(len(items) for items in self.streets.values())


def _zones(entries):
    """Agrupa referências próximas: a mesma numeração se repete em trechos distantes da mesma rua."""
    zones = []
    for entry in entries:
        near = [z for z in zones if any(distance_m(entry['point'], other['point']) <= ZONE_LINK_M for other in z)]
        zones = [z for z in zones if not any(z is n for n in near)] + [[entry] + [e for z in near for e in z]]
    return zones


def _medoid(entries):
    """Uma posição original (nunca a média) entre registros repetidos do mesmo imóvel."""
    return min(entries, key=lambda e: (sum(distance_m(e['point'], o['point']) for o in entries), e['id']))


def _number_text(entry):
    return str(entry['number']) + entry['suffix'].upper()


def _unlocated(reason):
    return {'geometry': None, 'method': 'sem_posicao', 'confidence': '', 'precision': reason,
            'references': [], 'reference_neighborhood': '', 'issues': []}


def _located(point, method, confidence, precision, references, issues=()):
    hoods = Counter(r['neighborhood'] for r in references if r.get('neighborhood'))
    return {'geometry': {'type': 'Point', 'coordinates': [round(point[0], 6), round(point[1], 6)]},
            'method': method, 'confidence': confidence, 'precision': precision[:240],
            'references': [r['id'] for r in references],
            'reference_neighborhood': hoods.most_common(1)[0][0] if hoods else '', 'issues': list(issues)}


def _locate_house(parsed, index):
    condo = parsed['condominium']
    house, guessed = parsed['house'], False
    if house is None and parsed['number'] and (normalize(condo), parsed['number']) in index.houses:
        house, guessed = parsed['number'], True
    if house is None:
        return _unlocated(f'Condomínio {condo} sem o número da casa.')
    found = index.houses.get((normalize(condo), house), [])
    if len(found) != 1:
        return _unlocated(f'Casa {house} do Condomínio {condo} não está no croqui do atlas.')
    issues = [f'Número {house} lido como casa do condomínio: confira.'] if guessed else []
    located = _located(found[0]['point'], 'condominio', 'baixa' if guessed else 'media',
                       f'Automático · casa {house} do croqui do Condomínio {condo} (posição estimada no atlas).', found, issues)
    # A casa fica na divisa das quadras do croqui: vale a quadra que o próprio croqui informa.
    return {**located, 'block': (found[0]['block'], found[0]['sector']) if found[0]['block'] else None}


def locate(parsed, neighborhood, index):
    """Posição de um endereço usando só as referências do atlas, com o motivo quando não há."""
    if not parsed:
        return _unlocated(NO_STREET)
    if parsed['condominium']:
        return _locate_house(parsed, index)
    if not parsed['street']:
        return _unlocated(f'Condomínio {parsed["other_condominium"]} ainda não tem croqui no atlas.'
                          if parsed['other_condominium'] else NO_STREET)
    street, number, suffix = parsed['street_label'], parsed['number'], parsed['suffix']
    entries = index.streets.get(parsed['street'])
    if not entries:
        return _unlocated(f'{street} não está na base de endereços do atlas.')
    if not number:
        return _unlocated('Endereço sem número.')
    window = [e for e in entries if abs(e['number'] - number) <= WINDOW]
    if not window:
        nearest = min(entries, key=lambda e: abs(e['number'] - number))
        return _unlocated(f'Número fora da faixa conhecida da {street} (mais próximo na base: {_number_text(nearest)}).')

    def weigh(zone):
        exact = [e for e in zone if e['number'] == number]
        hood = any(same_neighborhood(neighborhood, e['neighborhood']) for e in zone)
        # Número e letra iguais pesam mais; depois o número; o bairro desempata; a letra sozinha é o indício mais fraco.
        value = (4 * any(e['suffix'] == suffix for e in exact) + 2 * bool(exact) + 2 * hood
                 + (sum(e['suffix'] == suffix for e in zone) * 2 > len(zone)))
        return {'zone': zone, 'exact': exact, 'hood': hood, 'value': value,
                'delta': min(abs(e['number'] - number) for e in zone)}
    zones = [weigh(z) for z in _zones(window)]
    if any(z['exact'] or len(z['zone']) > 1 for z in zones):
        # Um registro isolado e sem o número procurado não decide nada (costuma ser coordenada fora do lugar).
        zones = [z for z in zones if z['exact'] or len(z['zone']) > 1]
    zones.sort(key=lambda z: (-z['value'], z['delta'], -len(z['zone'])))
    best = zones[0]
    if len(zones) > 1 and zones[1]['value'] == best['value'] and (
            (best['exact'] and zones[1]['exact']) or (not best['exact'] and abs(zones[1]['delta'] - best['delta']) <= 10)):
        places = ' e '.join(sorted({z['zone'][0]['neighborhood'] or 'bairro não informado' for z in zones[:2]}))
        return _unlocated(f'{street}, {number} cabe em mais de um trecho da rua ({places}); '
                          'letra e bairro da planilha não permitem decidir.')
    issues = []
    rival = next((z for z in zones[1:] if z['exact'] and z['hood']), None)
    if rival and not best['hood']:
        issues.append(f'O mesmo número existe em {rival["zone"][0]["neighborhood"]}, bairro informado na planilha: confira.')
    zone, exact = best['zone'], best['exact']
    if exact:
        same = [e for e in exact if e['suffix'] == suffix]
        chosen = _medoid(same or exact)
        spread = max(distance_m(chosen['point'], e['point']) for e in (same or exact))
        if spread > 40:
            issues.append(f'A base tem registros deste número a {round(spread)} m um do outro.')
        if same:
            return _located(chosen['point'], 'exato', 'baixa' if issues else 'alta',
                            f'Automático · endereço exato na base do atlas ({street}, {_number_text(chosen)} · '
                            f'{chosen["neighborhood"]}).', [chosen], issues)
        sure = not issues and (len(zones) == 1 or best['hood'])
        issues.append(f'Planilha traz {number}{"-" + suffix.upper() if suffix else " sem letra"}; '
                      f'a base do atlas tem {_number_text(chosen)}.')
        return _located(chosen['point'], 'exato_sufixo', 'alta' if sure else 'baixa' if len(issues) > 1 else 'media',
                        f'Automático · mesmo número na base do atlas, com letra diferente ({street}, '
                        f'{_number_text(chosen)} · {chosen["neighborhood"]}).', [chosen], issues)

    def pair(candidates):
        lower = [e for e in candidates if e['number'] < number]
        upper = [e for e in candidates if e['number'] > number]
        if not lower or not upper:
            return None
        low, high = max(e['number'] for e in lower), min(e['number'] for e in upper)
        return (_medoid([e for e in lower if e['number'] == low]), _medoid([e for e in upper if e['number'] == high]))
    any_side, same_side = pair(zone), pair([e for e in zone if e['number'] % 2 == number % 2])
    # Mesmo lado da rua (mesma paridade) quando os vizinhos não ficam muito mais longe na numeração.
    chosen = same_side if same_side and (not any_side or same_side[1]['number'] - same_side[0]['number']
                                         <= 2 * (any_side[1]['number'] - any_side[0]['number']) + 20) else any_side
    if chosen:
        low, high = chosen
        gap, span = high['number'] - low['number'], distance_m(low['point'], high['point'])
        if gap <= MAX_GAP and span <= MAX_SPAN_M:
            t = (number - low['number']) / gap
            point = (low['point'][0] + t * (high['point'][0] - low['point'][0]),
                     low['point'][1] + t * (high['point'][1] - low['point'][1]))
            return _located(point, 'interpolado', 'baixa' if issues or gap > 40 or span > 80 else 'media',
                            f'Automático · interpolado entre os nº {_number_text(low)} e {_number_text(high)} '
                            f'da {street} (base do atlas; {round(span)} m entre eles).', [low, high], issues)
    nearest = min(zone, key=lambda e: (abs(e['number'] - number), e['id']))
    if abs(nearest['number'] - number) <= NEIGHBOR:
        return _located(nearest['point'], 'vizinho', 'baixa',
                        f'Automático · posição do nº {_number_text(nearest)} da {street}, o mais próximo na base do atlas '
                        f'(o {number} não está cadastrado).', [nearest], issues)
    return _unlocated(f'{street}, {number}: sem imóveis próximos na base de endereços (mais próximo: {_number_text(nearest)}).')


# --------------------------------------------------------------------------
# Planilha -> registros
# --------------------------------------------------------------------------

def sheet_rows(values):
    """Linhas de dengue da planilha, só com os campos que a camada guarda."""
    header = [normalize(v) for v in (values[0] if values else [])]
    if any(len(header) <= index or header[index] != name for index, name in SHEET_HEADERS.items()):
        raise ValueError('O cabeçalho da planilha mudou. Confira a fonte antes de atualizar a camada.')
    rows, others = [], 0
    for line, raw in enumerate(values[1:], 2):
        row = [str(v).strip() for v in raw] + [''] * max(0, 20 - len(raw))
        if not any(row[:20]):
            continue
        if 'dengue' not in normalize(row[1]):
            others += 1
            continue
        ficha = re.sub(r'\D', '', row[2])
        rows.append({'source_row': line, 'ficha': str(int(ficha)) if ficha else '', 'sinan': atlas.identifier(row[3]),
                     'disease': row[1][:120], 'notification_date': atlas.date_iso(row[5]),
                     'symptoms_date': atlas.date_iso(row[6]), 'raw_address': row[9], 'neighborhood': row[10][:120],
                     'exam': row[15][:120], 'exam_result': row[16][:160], 'final_result': row[17][:160],
                     'classification': row[18][:120]})
    for field, prefix in (('sinan', 'sinan-'), ('ficha', 'ficha-')):
        counts = Counter(r[field] for r in rows if r[field])
        for r in rows:
            if 'id' not in r and r[field] and counts[r[field]] == 1:
                r['id'] = 'dengue-auto-' + prefix + r[field]
    for r in rows:
        r.setdefault('id', 'dengue-auto-linha-' + str(r['source_row']))
    return rows, others


def block_of(point):
    """``(quadra, distância)`` da quadra operacional do ponto: a que o contém ou a encostada na calçada."""
    from services.entomologia_georeference import CELL, distance_segment, in_ring, reference_index
    index = reference_index()
    x, y = math.floor(point[0] / CELL), math.floor(point[1] / CELL)
    near = {i for dx in (-1, 0, 1) for dy in (-1, 0, 1) for i in index['block_grid'].get((x + dx, y + dy), [])}
    near.update(index['wide'])
    inside = [i for i in near if in_ring(point, index['blocks'][i][0][0])
              and not any(in_ring(point, ring) for ring in index['blocks'][i][0][1:])]
    if inside:
        return (index['blocks'][inside[0]][1], 0) if len(inside) == 1 else None
    edges = sorted((min(distance_segment(point, a, b) for a, b in zip(index['blocks'][i][0][0], index['blocks'][i][0][0][1:])), i)
                   for i in near)
    if not edges or edges[0][0] > BLOCK_REACH_M or (len(edges) > 1 and edges[1][0] - edges[0][0] < BLOCK_MARGIN_M):
        return None
    return index['blocks'][edges[0][1]][1], round(edges[0][0])


def _far_from_street(parsed, geometry):
    """Conferência independente: a posição está longe da rua de mesmo nome na malha OSM do atlas?"""
    from services.entomologia_georeference import assess
    review = assess({'id': 'dengue-auto', 'geometry': geometry,
                     'properties': {'address': f'{parsed["street_label"]}, {parsed["number"]}'}})
    road = review.get('declared_road')
    return road['distance_m'] if road and road['distance_m'] > 60 else None


def _manual_index(layer):
    by_sinan, by_address = defaultdict(list), defaultdict(list)
    for feature in (layer or {}).get('features', []):
        geometry, p = feature.get('geometry'), feature.get('properties', {})
        if not geometry or geometry.get('type') != 'Point':
            continue
        if p.get('sinan'):
            by_sinan[p['sinan']].append(feature)
        parsed = parse_address(p.get('address') or p.get('name') or '')
        if parsed and parsed['street'] and parsed['number']:
            by_address[(parsed['street'], parsed['number'])].append(feature)
    return by_sinan, by_address


def _team_position(old):
    """Registro cuja posição a equipe mudou ou confirmou no editor depois da última atualização automática."""
    properties = (old or {}).get('properties', {})
    if 'auto_coordinates' not in properties:
        return None
    geometry = old.get('geometry')
    current = geometry['coordinates'] if geometry and geometry.get('type') == 'Point' else None
    edited = properties.get('position_status') in ('verified', 'to_review') or current != properties['auto_coordinates']
    return old if edited else None


def _date_issue(row):
    if not (row['symptoms_date'] and row['notification_date']):
        return ''
    days = (date.fromisoformat(row['notification_date']) - date.fromisoformat(row['symptoms_date'])).days
    if days < 0:
        return 'Início dos sintomas posterior à notificação: confira as datas.'
    return 'Sintomas mais de 60 dias antes da notificação: confira o ano.' if days > 60 else ''


def build(values, layers, previous=None, read_at='', today=''):
    """Camada completa (pastas por mês + registros) e o resumo da geocodificação."""
    rows, others = sheet_rows(values)
    index = AddressIndex(layers)
    manual = layers.get('earth-' + atlas.layer_id(MANUAL_TITLE))
    if manual and manual.get('deleted'):
        manual = None
    by_sinan, by_address = _manual_index(manual)
    before = {str(f['id']): f for f in (previous or {}).get('features', [])}
    features, months, used_manual, distances = [], set(), set(), []
    methods, confidence = Counter(), Counter()
    for row in rows:
        parsed = parse_address(row['raw_address'])
        found = locate(parsed, row['neighborhood'], index)
        label = address_label(parsed)
        when = row['symptoms_date'] or row['notification_date']
        months.add(when[:7])
        result = RESULT_LABELS[atlas.result_group(row['exam_result'])]
        notes = [' · '.join(p for p in ('Ficha ' + row['ficha'] if row['ficha'] else '',
                                         'SINAN ' + row['sinan'] if row['sinan'] else '',
                                         (row['exam'] + ': ' if row['exam'] else '') + (row['exam_result'] or result)) if p) + '.']
        notes += [_date_issue(row)] + found['issues']
        geometry, status = found['geometry'], 'estimated' if found['geometry'] else 'unlocated'
        automatic = geometry['coordinates'] if geometry else None
        if geometry and found['method'] not in ('condominio',):
            far = _far_from_street(parsed, geometry)
            if far:
                notes.append(f'Posição a {round(far)} m da {parsed["street_label"]} na malha de ruas do atlas: confira.')
                found = {**found, 'confidence': 'baixa'}
        kept = _team_position(before.get(row['id']))
        if kept:
            geometry = kept.get('geometry')
            status = kept['properties'].get('position_status', 'to_review') if geometry else 'unlocated'
            if geometry and geometry['type'] == 'Point' and automatic:
                notes.append(f'A equipe ajustou a posição; a automática fica a {round(distance_m(geometry["coordinates"], automatic))} m.')
            found = {**found, 'method': 'equipe', 'confidence': 'alta' if geometry else '',
                     'precision': kept['properties'].get('precision') or 'Posição ajustada pela equipe no atlas.'}
        properties = {
            'name': label or 'Endereço não reconhecido',
            'address': ' · '.join(p for p in (label, row['neighborhood']) if p)[:240],
            'house_number': (str(parsed['number']) + parsed['suffix'].upper()) if parsed and parsed['number'] else '',
            'category': result, 'date': when,
            'date_origin': 'Início dos sintomas' if row['symptoms_date'] else 'Notificação' if when else '',
            'month': when[5:7], 'period_year': when[:4], 'folder_id': KEY + '-' + (when[:7] or 'sem-data'),
            'source_row': row['source_row'], 'ficha': row['ficha'], 'sheet_neighborhood': row['neighborhood'],
            **{k: row[k] for k in ('sinan', 'disease', 'notification_date', 'symptoms_date', 'exam', 'exam_result',
                                   'final_result', 'classification')}}
        if geometry and geometry['type'] == 'Point':
            block = block_of(geometry['coordinates'])
            if block:
                properties.update(block=str(block[0]['block']), sector=str(block[0]['sector']), block_distance_m=block[1])
            elif found.get('block') and not kept:
                properties.update(block=found['block'][0], sector=found['block'][1], block_distance_m=0)
        candidates = by_sinan.get(row['sinan']) if row['sinan'] else None
        match = 'sinan' if candidates else ''
        if not candidates and parsed and parsed['street'] and parsed['number']:
            candidates = by_address.get((parsed['street'], parsed['number']))
            match = 'endereco' if candidates else ''
        if candidates:
            used_manual.update(str(f['id']) for f in candidates)
            properties['manual_match'] = match
            if geometry and geometry['type'] == 'Point':
                gap = round(min(distance_m(geometry['coordinates'], f['geometry']['coordinates']) for f in candidates))
                properties['manual_distance_m'] = gap
                distances.append(gap)
                notes.append(f'Marcador manual ({"mesmo SINAN" if match == "sinan" else "mesmo endereço"}) a {gap} m'
                             + (f', em {today}.' if today else '.'))
        elif manual is not None:
            notes.append('Sem marcador manual correspondente na camada Casos Dengue.')
        properties.update(position_status=status, precision=found['precision'],
                          notes=' '.join(n for n in notes if n)[:2000], auto_coordinates=automatic,
                          geocode_method=found['method'], geocode_confidence=found['confidence'],
                          geocode_references=found['references'],
                          reference_neighborhood=found['reference_neighborhood'])
        methods[found['method']] += 1
        if found['confidence']:
            confidence[found['confidence']] += 1
        features.append({'type': 'Feature', 'id': row['id'], 'geometry': geometry, 'properties': properties})
    folders = [{'id': KEY + '-' + (month or 'sem-data'), 'parent_id': '',
                'name': f'{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}' if month else 'Sem data'}
               for month in sorted(months, key=lambda m: m or '9999')]
    manual_points = [f for f in (manual or {}).get('features', []) if (f.get('geometry') or {}).get('type') == 'Point']
    summary = {
        'version': VERSION, 'read_at': read_at, 'rows': len(rows), 'other_diseases': others,
        'located': sum(f['geometry'] is not None for f in features),
        'unlocated': sum(f['geometry'] is None for f in features),
        'with_block': sum('block' in f['properties'] for f in features),
        'methods': dict(methods), 'confidence': dict(confidence), 'references': index.size,
        'manual': None if manual is None else {
            'markers': len(manual_points), 'compared': len(distances),
            'median_m': round(median(distances)) if distances else None,
            'within_25m': sum(d <= 25 for d in distances), 'within_50m': sum(d <= 50 for d in distances),
            'within_100m': sum(d <= 100 for d in distances), 'over_100m': sum(d > 100 for d in distances),
            'rows_without_marker': sum('manual_match' not in f['properties'] for f in features),
            'markers_without_row': sum(str(f['id']) not in used_manual for f in manual_points)}}
    layer = {'id': KEY, 'title': TITLE, 'color': (previous or {}).get('color') or COLOR, 'clinical': True,
             'deleted': False, 'features': features, 'folders': folders, 'automation': summary,
             'origin': {'type': 'sheet_snapshot', 'automatic': True, 'title': 'Planilha Arboviroses · posição automática',
                        'url': atlas.SHEET_URL, 'read_at': read_at,
                        'note': 'Posições calculadas só com os endereços do atlas (CNEFE, correções da equipe e croquis). '
                                'Estimativas a conferir no campo.'}}
    return layer, summary


def sync(actor, clinical_allowed, values=None, read_at=''):
    """Lê a planilha e grava a camada como uma nova revisão auditada do atlas."""
    if not clinical_allowed:
        raise PermissionError('A planilha exige acesso SFA completo.')
    from services import entomologia_atlas_editor as editor
    from time_utils import now_in_brazil
    if values is None:
        values, read_at = atlas.sheet_values(force=True)       # rede antes da trava de escrita
    with editor.write_transaction():
        available = editor.layers(True, True)
        previous = available.get(KEY)
        layer, summary = build(values, available, previous, read_at, now_in_brazil().strftime('%d/%m/%Y'))
        stored = editor.store_revision(
            KEY, layer, 'sync_dengue', 'Atualização automática a partir da planilha Arboviroses',
            previous['revision'] if previous else 0, actor,
            {'rows': summary['rows'], 'located': summary['located'], 'unlocated': summary['unlocated']})
    return stored, summary


def report_rows(layer):
    """Tabela de conferência (sem nome, telefone ou nascimento) para comparar com a marcação manual."""
    rows = [['Linha da planilha', 'Ficha', 'SINAN', 'Pasta', 'Início dos sintomas', 'Notificação', 'Resultado',
             'Endereço lido', 'Bairro na planilha', 'Método', 'Confiança', 'Como a posição foi obtida',
             'Bairro da referência', 'Quadra', 'Setor', 'Distância ao marcador manual (m)', 'Vínculo com o manual',
             'Observações', 'Longitude', 'Latitude']]
    for feature in layer['features']:
        p, g = feature['properties'], feature.get('geometry')
        point = g['coordinates'] if g and g['type'] == 'Point' else ['', '']
        rows.append([p.get('source_row', ''), p.get('ficha', ''), p.get('sinan', ''), ' › '.join(p.get('folder_path', [])[1:]),
                     p.get('symptoms_date', ''), p.get('notification_date', ''), p.get('category', ''),
                     p.get('name', ''), p.get('sheet_neighborhood', ''),
                     METHOD_LABELS.get(p.get('geocode_method'), p.get('geocode_method', '')),
                     p.get('geocode_confidence', ''), p.get('precision', ''), p.get('reference_neighborhood', ''),
                     p.get('block', ''), p.get('sector', ''), p.get('manual_distance_m', ''),
                     {'sinan': 'SINAN', 'endereco': 'Endereço'}.get(p.get('manual_match'), ''), p.get('notes', ''),
                     point[0], point[1]])
    return rows
