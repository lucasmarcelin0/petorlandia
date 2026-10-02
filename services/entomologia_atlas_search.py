"""Índice de busca do atlas em cache (endereços, ruas, equipamentos, casas).

Antes, cada tecla recarregava todas as camadas do banco, copiava tudo e rodava
dezenas de substituições de texto em cada feição. Aqui o texto normalizado de
cada feição é calculado uma vez e reaproveitado até algum dado mudar. Os dados
continuam locais: nenhuma consulta nem endereço sai para um provedor externo.

Duas saídas, com a mesma regra de casamento:
  * ``search()``       -> resultado completo (usado pelo servidor como reserva);
  * ``client_index()`` -> versão compacta que o navegador filtra sozinho, para a
                          busca responder a cada tecla sem ir ao servidor.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import threading

from services import entomologia_atlas as atlas
from services import entomologia_atlas_editor as editor
from services.entomologia_atlas import normalize

RESULT_LIMIT = 80
PHRASE_PATTERN = re.compile(r'\b(?:rua|avenida|alameda|travessa|casa) \d+[a-z]?\b')
HAY_FIELDS = ('name', 'label', 'address', 'category', 'cep', 'neighborhood', 'cadastre_ref',
              'original_street', 'house_number')

_lock = threading.RLock()
_snapshots = {}
_payloads = {}


class _Entry:
    """Uma feição pronta para casar: texto normalizado calculado uma única vez."""
    __slots__ = ('layer', 'feature', 'hay', 'identity')

    def __init__(self, layer, feature):
        p = feature['properties']
        self.layer = layer
        self.feature = feature
        hay = editor.search_text(' '.join(str(p.get(k, '')) for k in HAY_FIELDS))
        if p.get('kind') == 'cadastre_house':
            hay += ' ' + editor.search_text(
                'casa ' + str(p.get('house_number', '')) + ' ' + ' '.join(p.get('folder_path', [])))
        self.hay = hay
        self.identity = (layer['id'], normalize(p.get('name') or p.get('label')))


class _Snapshot:
    __slots__ = ('entries', 'signature', '_groups', '_by_key', '_by_identity')

    def __init__(self, layers, signature):
        self.signature = signature
        # Camadas clínicas ficam no mesmo instantâneo e são filtradas na hora de
        # responder: um único conjunto na memória, e a permissão continua valendo.
        self.entries = [_Entry(layer, f) for layer in layers.values() for f in layer['features']]
        self._groups = None
        self._by_key = None
        self._by_identity = None

    def groups(self):
        """Entradas agrupadas como a busca agrupa (ruas OSM de mesmo nome e texto viram uma)."""
        if self._groups is None:
            groups, order = {}, []
            for entry in self.entries:
                if entry.layer['origin']['type'] == 'reference':
                    key = (entry.identity, entry.hay)
                    if key in groups:
                        groups[key].append(entry)
                        continue
                else:
                    key = (id(entry),)
                groups[key] = [entry]
                order.append(key)
            self._groups = [groups[k] for k in order]
            self._by_key = {(m[0].layer['id'], str(m[0].feature['id'])): m for m in self._groups}
            # Ruas de referência com o mesmo nome são um resultado só, mesmo com textos diferentes.
            self._by_identity = {}
            for entry in self.entries:
                if entry.layer['origin']['type'] == 'reference':
                    self._by_identity.setdefault(entry.identity, []).append(entry)
        return self._groups

    def street(self, entry):
        """Todos os trechos da mesma rua (ou só o próprio item, fora das camadas de referência)."""
        self.groups()
        return self._by_identity.get(entry.identity) if entry.layer['origin']['type'] == 'reference' else None

    def group_for(self, layer_id, feature_id):
        self.groups()
        return self._by_key.get((layer_id, str(feature_id)))


def _signature():
    """Impressão digital barata dos dados ativos; ``None`` se o banco não responde.

    Todas as fontes dinâmicas do atlas (revisões, Google Earth, CNEFE, cadastro,
    camadas enviadas) são linhas ATIVAS da mesma tabela de importações. Trocou
    uma linha, mudou o identificador ou o hash e o índice é refeito.
    """
    from models.entomologia import EntomologiaImportacao as E
    from services.entomologia_service import consultar_sem_interromper
    rows = consultar_sem_interromper(
        lambda: E.query.filter_by(status='ATIVA').with_entities(E.id, E.sha256).order_by(E.id).all())
    if rows is None:
        return None
    return tuple((row.id, row.sha256) for row in rows)


def _cache_key(signature):
    # Os provedores entram na chave como objetos (e não como id()): substituí-los
    # (testes, ajustes em tempo de execução) invalida o índice sem risco de
    # reaproveitar o endereço de memória de uma função já descartada.
    from services import entomologia_cadastre, entomologia_cnefe, entomologia_service
    return (signature, atlas.active_earth, entomologia_service.dataset_atual, editor.source_layers,
            editor.references, editor.condominiums,
            entomologia_cadastre.active, entomologia_cadastre.source_layers,
            entomologia_cnefe.active, entomologia_cnefe.source_layers)


def snapshot():
    signature = _signature()
    if signature is None:
        return _Snapshot(editor.layers(True), None)
    key = _cache_key(signature)
    with _lock:
        cached = _snapshots.get(key)
    if cached:
        return cached
    built = _Snapshot(editor.layers(True), signature)
    with _lock:
        _snapshots.clear()
        _payloads.clear()
        _snapshots[key] = built
    return built


def reset():
    with _lock:
        _snapshots.clear()
        _payloads.clear()


def parse(query):
    """Mesma interpretação do texto digitado que a busca sempre teve."""
    q = editor.search_text(query)
    if not q or len(q) > 240:
        return None
    q = re.sub(r'\bav\.?\s', 'avenida ', q)
    phrases = PHRASE_PATTERN.findall(q)
    tokens = PHRASE_PATTERN.sub(' ', q).replace(',', ' ').split()
    return (
        [re.compile(r'(?<!\w)' + re.escape(t) + r'(?!\w)') for t in phrases],
        [(t, re.compile(r'(?<!\d)' + re.escape(t) + r'(?!\d)') if t.isdigit() else None) for t in tokens],
    )


def _matches(hay, parsed):
    phrases, tokens = parsed
    return (all(p.search(hay) for p in phrases)
            and all((rx.search(hay) if rx else t in hay) for t, rx in tokens))


def _merge(base, other_geometry):
    if base['geometry']['type'] != 'GeometryCollection':
        base['geometry'] = {'type': 'GeometryCollection', 'geometries': [base['geometry']]}
    base['geometry']['geometries'].append(deepcopy(other_geometry))


def search(query, clinical_allowed):
    """Resultado idêntico ao da busca anterior, sem recarregar nem renormalizar."""
    parsed = parse(query)
    if parsed is None:
        return []
    result, grouped, located = [], {}, 0
    for entry in snapshot().entries:
        layer, f = entry.layer, entry.feature
        if layer['clinical'] and not clinical_allowed:
            continue
        is_reference = layer['origin']['type'] == 'reference'
        # O resultado final põe os locais posicionados primeiro e corta em 80. Quando já
        # há 80 posicionados, nada que venha depois entra; só falta unir trechos de ruas
        # já listadas. O resto não precisa gastar o casamento de texto.
        if located >= RESULT_LIMIT and not (is_reference and entry.identity in grouped):
            continue
        if not _matches(entry.hay, parsed):
            continue
        if is_reference and entry.identity in grouped:
            base = grouped[entry.identity]['feature']
            if base.get('geometry') and f.get('geometry'):
                _merge(base, f['geometry'])
            continue
        item = {'layer_id': layer['id'], 'layer_title': layer['title'], 'feature': deepcopy(f),
                'located': f.get('geometry') is not None}
        grouped[entry.identity] = item
        result.append(item)
        located += item['located']
    return sorted(result, key=lambda item: not item['located'])[:RESULT_LIMIT]


# --------------------------------------------------------------------------
# Índice compacto para o navegador
# --------------------------------------------------------------------------

def _walk(coords, box):
    if coords and isinstance(coords[0], (int, float)):
        x, y = coords[0], coords[1]
        box[0], box[1] = min(box[0], x), min(box[1], y)
        box[2], box[3] = max(box[2], x), max(box[3], y)
        return
    for item in coords or []:
        _walk(item, box)


def _bbox(geometries):
    box = [180.0, 90.0, -180.0, -90.0]
    for g in geometries:
        if not g:
            continue
        if g['type'] == 'GeometryCollection':
            for part in g['geometries']:
                _walk(part['coordinates'], box)
        else:
            _walk(g['coordinates'], box)
    return box if box[0] <= box[2] else None


def _round(value):
    return round(value, 6)


def _compact(members, layer_index):
    first = members[0]
    layer, f = first.layer, first.feature
    p = f['properties']
    geometries = [m.feature.get('geometry') for m in members]
    box = _bbox(geometries)
    if not any(geometries) or box is None:
        kind, x, y, bbox = 0, None, None, None
    elif len(members) == 1 and f['geometry']['type'] == 'Point':
        kind, x, y, bbox = 1, _round(box[0]), _round(box[1]), None
    else:
        kind, x, y = 2, _round((box[0] + box[2]) / 2), _round((box[1] + box[3]) / 2)
        bbox = [_round(v) for v in box]
    # Última posição: nome normalizado da rua, só nas camadas de referência. O navegador
    # usa para mostrar uma única linha por rua, como a busca do servidor sempre fez.
    ident = first.identity[1] if layer['origin']['type'] == 'reference' else None
    return [layer_index[layer['id']], str(f['id']), str(p.get('name') or p.get('label') or layer['title']),
            str(p.get('address') or ''), first.hay, kind, x, y, bbox, p.get('cadastre_ref') or None, ident]


def client_index(clinical_allowed):
    """Payload JSON (já serializado) com tudo o que o navegador precisa para buscar sozinho."""
    snap = snapshot()
    variant = bool(clinical_allowed)
    with _lock:
        cached = _payloads.get((snap.signature, variant))
    if cached and snap.signature is not None:
        return cached
    layer_index, layers, rows = {}, [], []
    for members in snap.groups():
        layer = members[0].layer
        if layer['clinical'] and not variant:
            continue
        if layer['id'] not in layer_index:
            layer_index[layer['id']] = len(layers)
            layers.append({'id': layer['id'], 'title': layer['title']})
        rows.append(_compact(members, layer_index))
    body = json.dumps({'layers': layers, 'entries': rows}, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False)
    etag = hashlib.sha256((repr(snap.signature) + str(variant) + body[:64]).encode()).hexdigest()[:24]
    payload = (body, etag if snap.signature is not None else None)
    if snap.signature is not None:
        with _lock:
            _payloads[(snap.signature, variant)] = payload
    return payload


def place(layer_id, feature_id, clinical_allowed):
    """Feição completa (com a geometria) de uma entrada do índice, ruas já unidas."""
    snap = snapshot()
    members = snap.group_for(layer_id, feature_id)
    if not members:
        return None
    first = members[0]
    if first.layer['clinical'] and not clinical_allowed:
        return None
    members = snap.street(first) or members
    base = deepcopy(first.feature)
    for other in members:
        if other is first or not other.feature.get('geometry'):
            continue
        if base.get('geometry') is None:
            base['geometry'] = deepcopy(other.feature['geometry'])
        else:
            _merge(base, other.feature['geometry'])
    return {'layer_id': layer_id, 'layer_title': first.layer['title'], 'feature': base,
            'located': base.get('geometry') is not None}
