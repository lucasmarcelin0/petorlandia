"""Extract only the non-identifying Quadras layer of a municipal KML.

Build dependency: Shapely. Original polygon coordinates are preserved. Patient
points, descriptions, styles and other layers never enter the output.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from shapely import make_valid
from shapely.geometry import Polygon
from shapely.ops import polylabel

NS = {'k': 'http://www.opengis.net/kml/2.2'}


def build(source):
    raw = Path(source).read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('XML entities are not supported.')
    root = ET.fromstring(raw)
    if root.tag != '{http://www.opengis.net/kml/2.2}kml':
        raise ValueError('Expected a KML document.')
    features = []

    def ring(node):
        points = [list(map(float, token.split(',')[:2]))
                  for token in node.findtext('.//k:coordinates', '', NS).split()]
        if len(points) < 4 or points[0] != points[-1]:
            raise ValueError('Unclosed or incomplete polygon.')
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p)
               or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in points):
            raise ValueError('Invalid coordinate.')
        return points

    def walk(node, path):
        for child in node:
            tag = child.tag.rsplit('}', 1)[-1]
            if tag in ('Document', 'Folder'):
                walk(child, path + [child.findtext('k:name', '', NS).strip()])
            if tag != 'Placemark' or len(path) < 2 or path[1] != 'Quadras':
                continue
            block = child.findtext('k:name', '', NS).strip()
            sector = next((re.fullmatch(r'SC\s*(\d+)', p, re.I) for p in reversed(path)
                           if re.fullmatch(r'SC\s*(\d+)', p, re.I)), None)
            block_match = re.fullmatch(r'(?:Q\s*)?(\d+)([A-Za-z]?)', block, re.I)
            if not block_match or not sector:
                raise ValueError('Quadra without a numeric block/sector identifier.')
            polygons = []
            for polygon in child.findall('.//k:Polygon', NS):
                outer = polygon.find('k:outerBoundaryIs', NS)
                if outer is None:
                    raise ValueError('Missing exterior ring.')
                polygons.append([ring(outer), *[ring(n) for n in polygon.findall('k:innerBoundaryIs', NS)]])
            if not polygons:
                raise ValueError('Quadra without polygon geometry.')
            shapes = [Polygon(p[0], p[1:]) for p in polygons]
            valid = all(s.is_valid for s in shapes)
            candidates = []
            for s in shapes:
                fixed = s if s.is_valid else make_valid(s)
                candidates.extend([fixed] if fixed.geom_type == 'Polygon' else
                                  [g for g in fixed.geoms if g.geom_type == 'Polygon'])
            if not candidates or max(s.area for s in candidates) <= 0:
                raise ValueError('Quadra without a usable interior.')
            label = polylabel(max(candidates, key=lambda s: s.area), tolerance=0.000005)
            features.append({
                'type': 'Feature', 'id': len(features),
                'properties': {'block': str(int(block_match[1])) + block_match[2].upper(), 'sector': sector[1].zfill(3),
                               'district': path[-2], 'source_id': child.get('id', ''),
                               'label': [label.x, label.y], 'geometry_valid': valid},
                'geometry': {'type': 'MultiPolygon', 'coordinates': polygons},
            })

    walk(root, [])
    if not features:
        raise ValueError('No Quadras layer found.')
    keys = Counter((f['properties']['sector'], f['properties']['block']) for f in features)
    for f in features:
        p = f['properties']
        p['duplicate_key'] = keys[p['sector'], p['block']] > 1
    return {
        'type': 'FeatureCollection', 'features': features,
        'source': {'file': Path(source).name, 'sha256': hashlib.sha256(raw).hexdigest(),
                   'layer': 'Quadras', 'crs': 'EPSG:4326',
                   'blocks': len(features), 'sectors': len({p['properties']['sector'] for p in features}),
                   'districts': len({p['properties']['district'] for p in features}),
                   'invalid_geometries': sum(not f['properties']['geometry_valid'] for f in features),
                   'duplicate_keys': sum(v > 1 for v in keys.values()),
                   'coordinates_preserved': True, 'territorial_validation': 'pending'},
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] /
                        'services/data/entomologia/territory.json')
    args = parser.parse_args()
    data = build(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps(data['source'], ensure_ascii=False))
