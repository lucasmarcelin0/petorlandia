"""Build an anonymized dashboard snapshot; usage and sources in docs/entomologia.md."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

METRICS = {
    'worked': 'IM TRAB', 'closed': 'IM FECH', 'vacant': 'IM DESOC',
    'temporary': 'IM TEMP', 'partial': 'IM PARC', 'refused': 'IM RECUSA',
    'positive': 'IM. LARVA', 'aegypti': 'IM AE. AEGYPTI',
    'albopictus': 'IM AE. ALBOPICTUS', 'mechanical': 'IM MECANICO',
    'alternative': 'IM ALTERNATIVO', 'focal': 'IM FOCAL',
    'containers': 'REC. EXIST.', 'water': 'REC. AGUA',
    'positive_containers': 'REC. LARVA', 'aegypti_containers': 'REC AE AEGYPTI',
    'albopictus_containers': 'REC AE ALBOPICTUS',
    'aegypti_larvae': 'LARVAS AE. AEGYPTI', 'albopictus_larvae': 'LARVAS AE. ALBOPICTUS',
}
IBGE_SOURCE = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/malha_com_atributos/setores/shp/UF/SP/SP_setores_CD2022.zip'


def header(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c)).upper().strip()


def number(value):
    value = '' if value is None else str(value).strip()
    if value in ('', 'X', 'x', '-', '..', '...'):
        return None
    result = float(value.replace(',', '.'))
    if result < 0 or not result < float('inf'):
        raise ValueError('Contagem inválida')
    return int(result) if result.is_integer() else result


def read_visits(blob):
    try:
        text = blob.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = blob.decode('cp1252')
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('LOGIN;'))
    reader = csv.DictReader(lines[start:], delimiter=';')
    required = {'DATA', 'AREA', 'CENSITARIO', 'QUARTEIRAO', *METRICS.values()}
    if not required.issubset({header(k) for k in reader.fieldnames}):
        raise ValueError('Colunas obrigatórias ausentes no CSV de visitas')
    rows, signatures = [], Counter()
    for raw in reader:
        row = {header(k): (v or '').strip() for k, v in raw.items() if k}
        when = date.fromisoformat(row['DATA']).isoformat()
        sector = row['CENSITARIO']
        if not re.fullmatch(r'3534302\d{8}', sector):
            raise ValueError(f'Setor inválido ou de outro município: {sector}')
        clean = {'date': when, 'area': row['AREA'], 'sector': sector, 'block': row['QUARTEIRAO']}
        for key, source in METRICS.items():
            clean[key] = number(row[source])
            if clean[key] is not None and not isinstance(clean[key], int):
                raise ValueError(f'Contagem fracionária: {source}')
        # Repeated rows are retained: the source has no reliable unique visit ID.
        signatures[tuple(clean.values())] += 1
        rows.append(clean)
    if not rows:
        raise ValueError('CSV sem visitas')
    rows.sort(key=lambda r: (r['date'], r['sector'], r['block']))
    return rows, sum(n - 1 for n in signatures.values())


def read_census(path):
    import shapefile  # build dependency only (pyshp); production uses JSON
    with zipfile.ZipFile(path) as archive:
        stem = next(n[:-4] for n in archive.namelist() if n.endswith('.shp'))
        projection = archive.read(stem + '.prj').decode()
        if 'GEOGCS' not in projection or 'PROJCS' in projection or 'SIRGAS_2000' not in projection:
            raise ValueError('A malha deve usar coordenadas geográficas SIRGAS 2000')
        reader = shapefile.Reader(**{ext: io.BytesIO(archive.read(stem + '.' + ext)) for ext in ('shp', 'shx', 'dbf')}, encoding='utf-8')
        features = []
        for i, record in enumerate(reader.iterRecords()):
            raw = {k.upper(): v for k, v in record.as_dict().items()}
            if str(raw['CD_MUN']) != '3534302':
                continue
            geometry = reader.shape(i).__geo_interface__
            properties = {
                'sector': str(raw['CD_SETOR']), 'situation': raw['SITUACAO'],
                'area_km2': number(raw['AREA_KM2']), 'population': number(raw['V0001']),
                'households': number(raw['V0002']), 'occupied_households': number(raw['V0007']),
                'residents_per_household': number(raw['V0005']),
            }
            features.append({'type': 'Feature', 'properties': properties, 'geometry': geometry})
    if not features or len({f['properties']['sector'] for f in features}) != len(features):
        raise ValueError('Malha sem setores de Orlândia ou com códigos duplicados')
    return {'type': 'FeatureCollection', 'features': features}


def build(visits_zip, census_zip, destination):
    with zipfile.ZipFile(visits_zip) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith('.csv'))
        blob = archive.read(name)
    rows, repeats = read_visits(blob)
    geo = read_census(census_zip)
    codes = {f['properties']['sector'] for f in geo['features']}
    unmatched = sorted({r['sector'] for r in rows} - codes)
    payload = {
        'schema_version': 1,
        'source': {'file': name, 'sha256': hashlib.sha256(blob).hexdigest(),
                   'census_url': IBGE_SOURCE, 'census_year': 2022,
                   'census_sha256': hashlib.sha256(Path(census_zip).read_bytes()).hexdigest(),
                   'start': min(r['date'] for r in rows), 'end': max(r['date'] for r in rows),
                   'rows': len(rows), 'repeated_rows_retained': repeats, 'unmatched_sectors': unmatched,
                   'missing_larvae': sum(r['positive'] is None for r in rows)},
        'records': rows, 'census': geo,
    }
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / 'snapshot.json'
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    temporary.replace(output)
    print(json.dumps(payload['source'], ensure_ascii=True, indent=2))
    print(f'{len(geo["features"])} census sectors; {output.stat().st_size} bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('visits_zip', type=Path)
    parser.add_argument('census_zip', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'services/data/entomologia')
    args = parser.parse_args()
    build(args.visits_zip, args.census_zip, args.output)
