"""Private atlas sources. No raw clinical exports are written to the repository."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import threading
import time
import unicodedata

TIPO_ATLAS = 'atlas_earth'
EARTH_ID = '1eruMbx5QcW6rK2vn5WRtG1h1036Tq4ha'
EARTH_URL = f'https://earth.google.com/earth/d/{EARTH_ID}'
SHEET_ID = '15UdUxNhuL3VUNpJr_iEiiWTVM-rlKtVcGPeY9jSFJ_E'
SHEET_GID = 1339975360
SHEET_URL = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={SHEET_GID}'
MONTHS = ['janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho', 'julho',
          'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
PALETTE = {'rotina': '#4fbcf3', 'mutirao': '#e9b75f', 'casos dengue': '#d59bfd',
           'larvas': '#ff977b', 'atendimentos': '#82d6ab'}
_sheet_cache = {}
_sheet_lock = threading.Lock()


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or ''))
                   if not unicodedata.combining(c)).strip().lower()


def identifier(value):
    value = str(value or '').strip()
    if re.fullmatch(r'\d+\.0', value):
        value = value[:-2]
    return str(int(value)) if re.fullmatch(r'\d+', value) else ''


def date_iso(value):
    text = str(value or '').strip().split(' ')[0]
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return ''


def result_group(value):
    text = normalize(value)
    if re.search(r'\bnegativo\b', text):
        return 'negative'
    if re.search(r'\bpositivo\b', text):
        return 'positive'
    if 'suspeito' in text or 'aguard' in text or 'pendente' in text:
        return 'pending'
    return 'unknown'


def read_earth(blob, filename):
    """Keep geometry, folder categories and explicit SINAN keys; drop names/text."""
    from defusedxml import ElementTree as ET
    from services.entomologia_service import LIMITE_ENVIO, LIMITE_COORDENADAS, LIMITE_FEICOES, _membro_zip, _texto_simples

    if not blob or len(blob) > LIMITE_ENVIO:
        raise ValueError('Envie um KML/KMZ de até 15 MB.')
    if filename.lower().endswith('.kmz'):
        _, raw = _membro_zip(blob, ('.kml',), preferir='doc')
    elif filename.lower().endswith('.kml'):
        raw = blob
    else:
        raise ValueError('Envie a exportação KML ou KMZ do projeto Earth.')
    try:
        root = ET.fromstring(raw)
    except Exception as exc:
        raise ValueError('KML inválido ou com entidades XML não permitidas.') from exc
    if root.tag != '{http://www.opengis.net/kml/2.2}kml':
        raise ValueError('O arquivo não é um KML.')
    ns = {'k': 'http://www.opengis.net/kml/2.2'}
    features, total_coordinates = [], 0
    def direct(el, name):
        return el.findtext('k:' + name, '', ns).strip()
    def coordinates(el):
        nonlocal total_coordinates
        points = []
        for token in el.findtext('.//k:coordinates', '', ns).split():
            try:
                pair = list(map(float, token.split(',')[:2]))
            except ValueError as exc:
                raise ValueError('Coordenada inválida.') from exc
            if len(pair) != 2 or not all(math.isfinite(v) for v in pair) or not (-180 <= pair[0] <= 180 and -90 <= pair[1] <= 90):
                raise ValueError('Coordenada inválida.')
            points.append(pair)
        total_coordinates += len(points)
        if total_coordinates > LIMITE_COORDENADAS:
            raise ValueError('O arquivo tem coordenadas demais.')
        return points
    def geometry(el):
        kind = el.tag.rsplit('}', 1)[-1]
        if kind == 'Point':
            points = coordinates(el)
            if len(points) != 1:
                raise ValueError('Ponto sem coordenada única.')
            return {'type': 'Point', 'coordinates': points[0]}
        if kind == 'LineString':
            points = coordinates(el)
            if len(points) < 2:
                raise ValueError('Linha incompleta.')
            return {'type': kind, 'coordinates': points}
        if kind == 'Polygon':
            rings = []
            for boundary in ['outerBoundaryIs', 'innerBoundaryIs']:
                for node in el.findall('k:' + boundary, ns):
                    ring = coordinates(node)
                    if len(ring) < 4 or ring[0] != ring[-1]:
                        raise ValueError('Polígono aberto ou incompleto.')
                    rings.append(ring)
            if not rings:
                raise ValueError('Polígono sem contorno.')
            return {'type': kind, 'coordinates': rings}
        if kind == 'MultiGeometry':
            geometries = [g for child in el if (g := geometry(child)) is not None]
            return {'type': 'GeometryCollection', 'geometries': geometries} if geometries else None
        return None
    def walk(el, folders):
        for child in el:
            kind = child.tag.rsplit('}', 1)[-1]
            if kind in ('Document', 'Folder'):
                walk(child, folders + ([direct(child, 'name')] if kind == 'Folder' else []))
            elif kind == 'Placemark':
                if len(features) >= LIMITE_FEICOES:
                    raise ValueError('O arquivo tem elementos demais.')
                geoms = [g for node in child if (g := geometry(node)) is not None]
                if not geoms:
                    continue
                layer = (folders[0] if folders else 'Outras referências')[:120]
                month = next((str(MONTHS.index(normalize(f)) + 1).zfill(2) for f in folders if normalize(f) in MONTHS), '')
                category = next((f[:120] for f in folders[1:] if normalize(f) not in MONTHS and not re.fullmatch(r'SC\s*\d+', f, re.I)), '')
                status = next((f for f in reversed(folders) if normalize(f) in ('positivo', 'negativo', 'negativos', 'suspeito')), '')
                # Only explicitly labelled SINAN numbers can link a clinical row.
                description = _texto_simples(direct(child, 'description'))
                keys = sorted({identifier(m) for m in re.findall(r'\bSINAN\s*[:#\-]?\s*(\d+)\b', description, re.I)} - {''})
                features.append({'type': 'Feature', 'id': child.get('id') or f'earth-{len(features)+1}',
                    'geometry': geoms[0] if len(geoms) == 1 else {'type': 'GeometryCollection', 'geometries': geoms},
                    'properties': {'layer': layer, 'category': category, 'month': month,
                        'folder_status': status, 'sinan': keys[0] if len(keys) == 1 else '',
                        'source_id': child.get('id') or '', 'label': f'{layer} · marcador {len(features)+1}'}})
    walk(root, [])
    if not features:
        raise ValueError('Nenhuma geometria encontrada.')
    title = root.findtext('k:Document/k:name', '', ns)[:200]
    counts = Counter(f['properties']['layer'] for f in features)
    return {'type': 'FeatureCollection', 'features': features, 'source': {
        'title': title, 'file': filename[:200], 'sha256': hashlib.sha256(raw).hexdigest(),
        'url': EARTH_URL, 'counts': dict(counts), 'coordinates_preserved': True}}


def active_earth():
    from models.entomologia import EntomologiaImportacao as E
    from services.entomologia_service import consultar_sem_interromper
    entry = consultar_sem_interromper(lambda: E.query.filter_by(tipo=TIPO_ATLAS, status='ATIVA').order_by(E.id.desc()).first())
    if not entry:
        return {'type': 'FeatureCollection', 'features': [], 'source': {'url': EARTH_URL, 'title': 'Projeto Earth ainda não importado'}}
    data = json.loads(entry.dados_json)
    return {**data, 'source': {**data.get('source', {}), 'imported_at': entry.confirmado_em.isoformat() if entry.confirmado_em else '', 'import_id': entry.id}}


def layer_id(name):
    return hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]


def is_case(name):
    return any(word in normalize(name) for word in ('caso', 'dengue', 'paciente', 'sinan'))


def catalog(data, clinical_allowed):
    grouped = defaultdict(list)
    for feature in data['features']:
        name = feature['properties']['layer']
        if normalize(name) != 'quadras':
            grouped[name].append(feature)
    return {'source': data['source'], 'layers': [
        {'id': layer_id(name), 'title': name, 'count': len(items) if not is_case(name) or clinical_allowed else None,
         'allowed': not is_case(name) or clinical_allowed, 'clinical': is_case(name),
         'color': PALETTE.get(normalize(name), '#aec7ec')}
        for name, items in grouped.items()]}


def sheet_records(values, earth):
    """Link by one explicit SINAN key and one Point only; never by name/address."""
    spatial = defaultdict(list)
    for f in earth['features']:
        if is_case(f['properties']['layer']) and f['properties'].get('sinan') and f['geometry']['type'] == 'Point':
            spatial[f['properties']['sinan']].append(f)
    rows = []
    for index, values_row in enumerate(values[1:], 2):
        row = list(values_row) + [''] * max(0, 20-len(values_row))
        if not any(str(v).strip() for v in row[:20]):
            continue
        rows.append({'id': f'sheet-row-{index}', 'source_row': index, 'sinan': identifier(row[3]),
                     'disease': str(row[1]).strip()[:120], 'notification_date': date_iso(row[5]),
                     'symptoms_date': date_iso(row[6]), 'exam': str(row[15]).strip()[:120],
                     'exam_result': str(row[16]).strip()[:160], 'final_result': str(row[17]).strip()[:160],
                     'classification': str(row[18]).strip()[:120]})
    duplicates = Counter(r['sinan'] for r in rows if r['sinan'])
    for row in rows:
        candidates = spatial.get(row['sinan'], [])
        row['geometry'] = candidates[0]['geometry'] if row['sinan'] and duplicates[row['sinan']] == 1 and len(candidates) == 1 else None
        row['link_status'] = 'explicit_sinan' if row['geometry'] else 'unlocated'
        row['result_group'] = result_group(row['exam_result'])
    return rows


def live_sheet(earth, force=False):
    from services.sfa_service import _get_sheets_service
    with _sheet_lock:
        if force or time.monotonic() - _sheet_cache.get('time', -1000) > 90:
            service = _get_sheets_service()
            metadata = service.spreadsheets().get(spreadsheetId=SHEET_ID, fields='sheets.properties').execute()
            sheet = next((s['properties'] for s in metadata['sheets'] if s['properties']['sheetId'] == SHEET_GID), None)
            if not sheet:
                raise ValueError('A aba de origem não está disponível.')
            bounds = sheet.get('gridProperties', {}).get('rowCount', 10000)
            if bounds > 10000:
                raise ValueError('A planilha ultrapassa o limite de consulta. Confira a integração antes de ampliar.')
            title = sheet['title'].replace("'", "''")
            values = service.spreadsheets().values().get(spreadsheetId=SHEET_ID,
                range=f"'{title}'!A1:T{bounds}", valueRenderOption='FORMATTED_VALUE').execute().get('values', [])
            expected = {1:'agravo/doenca',3:'sinan',5:'data notificacao',6:'data inicio sintomas',
                        15:'tipo de exame',16:'resultado',17:'resultado final',18:'classificacao do caso'}
            if not values or any(len(values[0]) <= index or normalize(values[0][index]) != name for index,name in expected.items()):
                raise ValueError('O cabeçalho da planilha mudou. Confira a fonte antes de integrar.')
            _sheet_cache.update(time=time.monotonic(), values=values, read_at=datetime.now(timezone.utc).isoformat())
        rows = sheet_records(_sheet_cache['values'], earth)
        return {'records': rows, 'source': {'title': 'Arboviroses 2026 · planilha', 'url': SHEET_URL,
            'read_at': _sheet_cache['read_at'], 'rows': len(rows), 'mapped': sum(r['geometry'] is not None for r in rows),
            'note': 'Sem coordenadas na planilha. Apenas um número SINAN explícito e único no Earth recebe posição. Demais registros ficam na lista.'}}
