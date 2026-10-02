"""Versioned, non-identifying municipal snapshot; no external calls at runtime.

A fotografia em ``data/entomologia`` é a base. Arquivos diários enviados pela
equipe (``EntomologiaImportacao``) substituem, na base consolidada, os dias que
contêm; desfazer um envio devolve os dias à versão anterior. Camadas KML/KMZ
exportadas do Google Earth ficam disponíveis como sobreposição do mapa interno.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import threading
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / 'data' / 'entomologia'

TIPO_VISITAS = 'visitas'
TIPO_CAMADA = 'camada'
LIMITE_ENVIO = 15 * 1024 * 1024
LIMITE_DESCOMPACTADO = 60 * 1024 * 1024
LIMITE_FEICOES = 5000
LIMITE_COORDENADAS = 250_000
PREVIA_VALIDADE = timedelta(days=2)


@lru_cache(maxsize=1)
def load_entomologia():
    with (DATA_DIR / 'snapshot.json').open(encoding='utf-8') as stream:
        return json.load(stream)


@lru_cache(maxsize=1)
def load_reference_maps():
    with (DATA_DIR / 'maps' / 'manifest.json').open(encoding='utf-8') as stream:
        return json.load(stream)


@lru_cache(maxsize=1)
def load_field_territory():
    with (DATA_DIR / 'territory.json').open(encoding='utf-8') as stream:
        return json.load(stream)


# ---------------------------------------------------------------------------
# Base consolidada
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache: dict = {}


def consolidar_visitas(base_records, envios):
    """Cada envio, em ordem, substitui integralmente os dias que contém."""
    records = list(base_records)
    for novos in envios:
        dias = {r['date'] for r in novos}
        records = [r for r in records if r['date'] not in dias] + list(novos)
    records.sort(key=lambda r: (r['date'], r['sector'], r['block']))
    return records


def _repeticoes(records):
    assinaturas = Counter(tuple(r.values()) for r in records)
    return sum(n - 1 for n in assinaturas.values())


def _fonte_consolidada(base, records, envios):
    codes = {f['properties']['sector'] for f in base['census']['features']}
    source = dict(base['source'])
    if records:
        source.update(start=records[0]['date'], end=max(r['date'] for r in records))
    source.update(
        rows=len(records),
        missing_larvae=sum(r['positive'] is None for r in records),
        unmatched_sectors=sorted({r['sector'] for r in records} - codes),
        repeated_rows_retained=_repeticoes(records),
    )
    if envios:
        ultimo = envios[-1]
        source['imported_at'] = ultimo['confirmado_em']
        source['base_end'] = base['source']['end']
    return source


def consultar_sem_interromper(consulta, padrao=None):
    """Consulta auxiliar que não quebra o painel nem a transação de quem chamou.

    Sem autoflush, alterações pendentes de outra operação (ex.: uma ação sendo
    registrada) não são enviadas antes da hora. Sem app/tabela, devolve ``padrao``.
    """
    try:
        from extensions import db
        with db.session.no_autoflush:
            return consulta()
    except Exception as exc:  # noqa: BLE001 - painel continua com a fotografia
        from sqlalchemy.exc import SQLAlchemyError
        if isinstance(exc, SQLAlchemyError):
            from extensions import db
            db.session.rollback()
        return padrao


def _chave_ativas():
    """Assinatura leve dos envios ativos; ``None`` quando não há banco disponível."""
    from models.entomologia import EntomologiaImportacao as E

    def consulta():
        rows = (E.query.with_entities(E.id, E.tipo, E.sha256, E.confirmado_em)
                .filter(E.status == 'ATIVA').order_by(E.id).all())
        return tuple((r.id, r.tipo, r.sha256, r.confirmado_em.isoformat() if r.confirmado_em else '')
                     for r in rows)
    return consultar_sem_interromper(consulta)


def _ler_ativas(ids):
    from extensions import db
    from models.entomologia import EntomologiaImportacao as E
    with db.session.no_autoflush:
        rows = {r.id: r for r in E.query.filter(E.id.in_(ids)).all()}
    return [rows[i] for i in ids]


def resumo_envio(row):
    return {
        'id': row.id, 'tipo': row.tipo, 'arquivo': row.nome_arquivo, 'titulo': row.titulo,
        'inicio': row.inicio.isoformat() if row.inicio else None,
        'fim': row.fim.isoformat() if row.fim else None, 'linhas': row.linhas,
        'confirmado_em': row.confirmado_em.isoformat() if row.confirmado_em else None,
    }


def dataset_atual():
    """Fotografia versionada + envios ativos. Nunca altera a fotografia em disco."""
    base = load_entomologia()
    chave = _chave_ativas()
    if not chave:
        return {**base, 'layers': [], 'updates': []}
    with _cache_lock:
        if chave in _cache:
            return _cache[chave]
    ativas = _ler_ativas([item[0] for item in chave])
    visitas = [row for row in ativas if row.tipo == TIPO_VISITAS]
    camadas = [row for row in ativas if row.tipo == TIPO_CAMADA]
    envios = [resumo_envio(row) for row in visitas]
    records = consolidar_visitas(base['records'], [json.loads(row.dados_json) for row in visitas])
    result = {
        **base,
        'records': records,
        'source': _fonte_consolidada(base, records, envios),
        'updates': envios,
        'layers': [{'id': row.id, 'title': row.titulo or row.nome_arquivo,
                    'geojson': json.loads(row.dados_json)} for row in camadas],
    }
    with _cache_lock:
        _cache.clear()
        _cache[chave] = result
    return result


def setores_operacionais():
    return {str(r.get('sector') or '') for r in dataset_atual().get('records', [])}


# ---------------------------------------------------------------------------
# Leitura de arquivos enviados
# ---------------------------------------------------------------------------

def _membro_zip(blob, extensoes, preferir=''):
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ValueError('O arquivo compactado está corrompido ou não é um ZIP válido.') from exc
    with archive:
        membros = [i for i in archive.infolist()
                   if not i.is_dir() and i.filename.lower().endswith(extensoes)]
        if preferir:
            preferidos = [i for i in membros if preferir in _sem_acento(i.filename).lower()]
            membros = preferidos or membros
        if not membros:
            raise ValueError(f'Nenhum arquivo {"/".join(extensoes)} encontrado dentro do ZIP.')
        if len(membros) > 1 and not preferir:
            membros.sort(key=lambda i: (i.filename.count('/'), i.filename))
        escolhido = membros[0]
        if escolhido.file_size > LIMITE_DESCOMPACTADO:
            raise ValueError('O arquivo descompactado é grande demais para o envio pelo navegador.')
        return escolhido.filename.rsplit('/', 1)[-1], archive.read(escolhido)


def _sem_acento(texto):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', texto) if not unicodedata.combining(c))


def ler_visitas(blob, nome_arquivo):
    """CSV "Visita a Imóvel" ou ZIP com esse CSV. Remove LOGIN/AGENTE."""
    from scripts.import_entomologia import read_visits

    if not blob:
        raise ValueError('Arquivo vazio.')
    if len(blob) > LIMITE_ENVIO:
        raise ValueError('Arquivo maior que 15 MB. Envie o CSV ou o ZIP exportado do sistema.')
    nome = (nome_arquivo or '').lower()
    if nome.endswith('.zip') or blob[:4] == b'PK\x03\x04':
        nome_csv, conteudo = _membro_zip(blob, ('.csv',), preferir='visita')
    elif nome.endswith('.csv') or nome.endswith('.txt'):
        nome_csv, conteudo = nome_arquivo, blob
    else:
        raise ValueError('Envie o arquivo .csv "Visita a Imóvel" ou o .zip exportado.')
    try:
        rows, repetidas = read_visits(conteudo)
    except StopIteration as exc:
        raise ValueError('Cabeçalho não encontrado: o arquivo deve ter a linha que começa com "LOGIN;".') from exc
    except KeyError as exc:
        raise ValueError(f'Coluna ausente no arquivo: {exc.args[0]}.') from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f'Arquivo recusado: {exc}') from exc
    return {'arquivo': nome_csv, 'rows': rows, 'repetidas': repetidas,
            'sha256': hashlib.sha256(conteudo).hexdigest()}


def previa_visitas(rows, dataset, hoje):
    """Compara o envio com a base consolidada, dia a dia."""
    antes = Counter(r['date'] for r in dataset['records'])
    depois = Counter(r['date'] for r in rows)
    codes = {f['properties']['sector'] for f in dataset['census']['features']}
    dias = []
    for dia in sorted(depois):
        situacao = 'novo' if not antes.get(dia) else 'substitui'
        dias.append({'data': dia, 'antes': antes.get(dia, 0), 'depois': depois[dia], 'situacao': situacao,
                     'reduz': bool(antes.get(dia)) and depois[dia] < antes[dia]})
    avisos = []
    futuros = [d['data'] for d in dias if d['data'] > hoje.isoformat()]
    if futuros:
        avisos.append(f'{len(futuros)} dia(s) com data posterior a hoje: confira a data do sistema de origem.')
    reduzidos = [d for d in dias if d['reduz']]
    if reduzidos:
        avisos.append(f'{len(reduzidos)} dia(s) passarão a ter menos registros que a base atual. '
                      'Confirme se o arquivo contém toda a equipe desses dias.')
    fora = sorted({r['sector'] for r in rows} - codes)
    if fora:
        avisos.append(f'{len(fora)} setor(es) sem correspondência na malha 2022; permanecem nos totais.')
    return {
        'linhas': len(rows), 'inicio': dias[0]['data'], 'fim': dias[-1]['data'],
        'dias': dias, 'dias_novos': sum(d['situacao'] == 'novo' for d in dias),
        'dias_substituidos': sum(d['situacao'] == 'substitui' for d in dias),
        'setores': len({r['sector'] for r in rows}),
        'quarteiroes': len({(r['area'], r['sector'], r['block']) for r in rows}),
        'trabalhados': sum(r['worked'] or 0 for r in rows),
        'sem_larvas': sum(r['positive'] is None for r in rows),
        'setores_fora_malha': fora, 'avisos': avisos,
    }


_TAG = re.compile(r'<[^>]+>')


def _texto_simples(valor, limite=1000):
    texto = html.unescape(_TAG.sub(' ', valor or ''))
    return re.sub(r'\s+', ' ', texto).strip()[:limite]


def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def _filho(el, nome):
    return next((c for c in el if _local(c.tag) == nome), None)


def _coordenadas(texto, contador):
    pontos = []
    for trio in (texto or '').split():
        partes = trio.split(',')
        if len(partes) < 2:
            continue
        try:
            lon, lat = float(partes[0]), float(partes[1])
        except ValueError as exc:
            raise ValueError('Coordenada inválida no KML.') from exc
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError('Coordenada fora do intervalo geográfico no KML.')
        pontos.append([round(lon, 7), round(lat, 7)])
    contador[0] += len(pontos)
    if contador[0] > LIMITE_COORDENADAS:
        raise ValueError('Camada com pontos demais para exibir no navegador.')
    return pontos


def _geometrias(el, contador):
    nome = _local(el.tag)
    if nome == 'Point':
        pontos = _coordenadas(getattr(_filho(el, 'coordinates'), 'text', ''), contador)
        return [{'type': 'Point', 'coordinates': pontos[0]}] if pontos else []
    if nome == 'LineString':
        pontos = _coordenadas(getattr(_filho(el, 'coordinates'), 'text', ''), contador)
        return [{'type': 'LineString', 'coordinates': pontos}] if len(pontos) >= 2 else []
    if nome == 'Polygon':
        aneis = []
        for fronteira in el:
            if _local(fronteira.tag) not in ('outerBoundaryIs', 'innerBoundaryIs'):
                continue
            anel = _filho(fronteira, 'LinearRing')
            pontos = _coordenadas(getattr(_filho(anel, 'coordinates'), 'text', '') if anel is not None else '', contador)
            if len(pontos) >= 4:
                if _local(fronteira.tag) == 'outerBoundaryIs':
                    aneis.insert(0, pontos)
                else:
                    aneis.append(pontos)
        return [{'type': 'Polygon', 'coordinates': aneis}] if aneis else []
    if nome == 'MultiGeometry':
        return [g for filho in el for g in _geometrias(filho, contador)]
    return []


def ler_camada(blob, nome_arquivo):
    """KML/KMZ do Google Earth → GeoJSON com nome, descrição (texto) e pasta."""
    from defusedxml import ElementTree as SafeET

    if not blob:
        raise ValueError('Arquivo vazio.')
    if len(blob) > LIMITE_ENVIO:
        raise ValueError('Arquivo maior que 15 MB.')
    nome = (nome_arquivo or '').lower()
    if nome.endswith('.kmz') or blob[:4] == b'PK\x03\x04':
        _, conteudo = _membro_zip(blob, ('.kml',), preferir='doc')
    elif nome.endswith('.kml'):
        conteudo = blob
    else:
        raise ValueError('Envie o arquivo .kml ou .kmz exportado do Google Earth.')
    try:
        raiz = SafeET.fromstring(conteudo)
    except Exception as exc:  # noqa: BLE001 - XML malformado ou com entidades bloqueadas
        raise ValueError('Não foi possível ler o KML. Exporte novamente pelo Google Earth.') from exc
    features, contador = [], [0]
    titulo = ''

    def visitar(el, pastas):
        nonlocal titulo
        for filho in el:
            tipo = _local(filho.tag)
            if tipo == 'Document' and not titulo:
                titulo = _texto_simples(getattr(_filho(filho, 'name'), 'text', ''), 200)
            if tipo in ('Document', 'Folder'):
                nome_pasta = _texto_simples(getattr(_filho(filho, 'name'), 'text', ''), 120)
                visitar(filho, pastas + ([nome_pasta] if tipo == 'Folder' and nome_pasta else []))
            elif tipo == 'Placemark':
                geometrias = [g for c in filho for g in _geometrias(c, contador)]
                if not geometrias:
                    continue
                if len(features) >= LIMITE_FEICOES:
                    raise ValueError(f'Camada com mais de {LIMITE_FEICOES} elementos.')
                geometria = geometrias[0] if len(geometrias) == 1 else {'type': 'GeometryCollection', 'geometries': geometrias}
                features.append({'type': 'Feature', 'geometry': geometria, 'properties': {
                    'name': _texto_simples(getattr(_filho(filho, 'name'), 'text', ''), 200),
                    'description': _texto_simples(getattr(_filho(filho, 'description'), 'text', '')),
                    'folder': ' / '.join(pastas)[:240],
                }})

    visitar([raiz] if _local(raiz.tag) != 'kml' else raiz, [])
    if not features:
        raise ValueError('Nenhum ponto, linha ou polígono encontrado no KML.')
    return {'titulo': titulo, 'geojson': {'type': 'FeatureCollection', 'features': features},
            'sha256': hashlib.sha256(conteudo).hexdigest(),
            'pastas': sorted({f['properties']['folder'] for f in features if f['properties']['folder']})}


# ---------------------------------------------------------------------------
# Boletim público (agregado por setor; sem imóvel, endereço ou pessoa)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def malha_publica():
    """Somente geometria, código e situação dos setores: o mínimo para o mapa público."""
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': f['geometry'],
         'properties': {'sector': f['properties']['sector'], 'situation': f['properties']['situation']}}
        for f in load_entomologia()['census']['features']]}


def _soma(rows, chave):
    valores = [r[chave] for r in rows if r.get(chave) is not None]
    return sum(valores) if valores else None


def inicio_semana(dia):
    """Semanas de domingo a sábado, como na comparação semanal do SFA."""
    return dia - timedelta(days=(dia.weekday() + 1) % 7)


def boletim_publico(dataset, fim=None, dias=28):
    if dias not in (7, 14, 28):
        raise ValueError('Janela inválida.')
    records = dataset['records']
    if not records:
        raise ValueError('Não há registros para publicar.')
    ultimo = date.fromisoformat(max(r['date'] for r in records))
    fim = min(fim or ultimo, ultimo)
    inicio = fim - timedelta(days=dias - 1)
    janela = [r for r in records if inicio.isoformat() <= r['date'] <= fim.isoformat()]
    if not janela:
        raise ValueError('Não há registros no período escolhido.')
    codes = {f['properties']['sector'] for f in dataset['census']['features']}
    por_setor = defaultdict(list)
    for r in janela:
        por_setor[r['sector']].append(r)
    setores = {}
    for setor, rows in sorted(por_setor.items()):
        positivos = sum(r.get('positive') or 0 for r in rows)
        especie = sum((r.get('aegypti') or 0) + (r.get('albopictus') or 0) for r in rows)
        informados = sum(r.get('positive') is not None for r in rows)
        situacao = 'foco' if positivos or especie else ('sem_foco' if informados else 'sem_informacao')
        setores[setor] = {
            'situacao': situacao, 'na_malha': setor in codes,
            'quarteiroes': len({(r['area'], r['block']) for r in rows}),
            'trabalhados': _soma(rows, 'worked'),
            'controle_mecanico': _soma(rows, 'mechanical'),
            'ultima_visita': max(r['date'] for r in rows),
        }
    semanas = []
    primeira = inicio_semana(fim) - timedelta(weeks=7)
    for n in range(8):
        comeco = primeira + timedelta(weeks=n)
        rows = [r for r in records if comeco.isoformat() <= r['date'] <= min(comeco + timedelta(days=6), fim).isoformat()]
        semanas.append({'inicio': comeco.isoformat(), 'trabalhados': _soma(rows, 'worked'),
                        'quarteiroes': len({(r['area'], r['sector'], r['block']) for r in rows}),
                        'registros': len(rows), 'parcial': comeco + timedelta(days=6) > fim})
    informados = sum(r.get('positive') is not None for r in janela)
    return {
        'versao': 1, 'inicio': inicio.isoformat(), 'fim': fim.isoformat(), 'dias': dias,
        'totais': {
            'trabalhados': _soma(janela, 'worked'),
            'quarteiroes': len({(r['area'], r['sector'], r['block']) for r in janela}),
            'setores': len(por_setor),
            'setores_com_foco': sum(s['situacao'] == 'foco' for s in setores.values()),
            'controle_mecanico': _soma(janela, 'mechanical'),
            'preenchimento': round(100 * informados / len(janela), 1),
        },
        'setores': setores, 'semanas': semanas,
        'fonte_ate': dataset['source'].get('end'),
    }
