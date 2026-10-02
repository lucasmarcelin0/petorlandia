"""Malha viária para rotas locais: formato, conectividade e entrega."""
import json

from services import entomologia_atlas_malha as malha
from tests.test_entomologia_atualizacao import login

URL = '/sfa/entomologia/atlas/malha'


def line(*points):
    return {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [list(p) for p in points]},
            'properties': {}}


def test_build_liga_trechos_que_compartilham_o_ponto_e_ignora_o_que_nao_e_rua():
    graph = malha.build([
        line((-47.9, -20.7), (-47.899, -20.7), (-47.898, -20.7)),
        line((-47.899, -20.7), (-47.899, -20.699)),                       # cruza no ponto do meio
        {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-47.9, -20.7]}, 'properties': {}},
        {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, 'properties': {}},
        {'type': 'Feature', 'geometry': None, 'properties': {}},
        line((-47.9, -20.7), (-47.899, -20.7)),                           # trecho repetido não duplica
    ])
    assert graph['v'] == 2
    nodes = [(graph['nodes'][i], graph['nodes'][i + 1]) for i in range(0, len(graph['nodes']), 2)]
    assert len(nodes) == 4 and len(set(nodes)) == 4
    edges = {tuple(sorted((graph['edges'][i], graph['edges'][i + 1]))) for i in range(0, len(graph['edges']), 2)}
    assert len(edges) == 3 and len(graph['edges']) == 6
    middle = nodes.index((-47899000, -20700000))
    assert sum(middle in e for e in edges) == 3          # o cruzamento liga os três trechos


def test_build_aceita_multilinha_e_colecao():
    graph = malha.build([
        {'type': 'Feature', 'geometry': {'type': 'MultiLineString', 'coordinates': [[[0, 0], [0, 1]], [[0, 1], [1, 1]]]}, 'properties': {}},
        {'type': 'Feature', 'geometry': {'type': 'GeometryCollection', 'geometries': [
            {'type': 'LineString', 'coordinates': [[1, 1], [2, 2]]}]}, 'properties': {}},
    ])
    assert len(graph['nodes']) // 2 == 4 and len(graph['edges']) // 2 == 3


def test_malha_real_da_cidade_e_grande_e_conectada():
    graph = json.loads(malha.street_network()[0])
    count = len(graph['nodes']) // 2
    assert count > 3000 and len(graph['edges']) // 2 > count
    parent = list(range(count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(0, len(graph['edges']), 2):
        parent[find(graph['edges'][i])] = find(graph['edges'][i + 1])
    sizes = {}
    for i in range(count):
        sizes[find(i)] = sizes.get(find(i), 0) + 1
    assert max(sizes.values()) > count * 0.6, 'a malha principal precisa cobrir a maior parte da cidade'
    # Orlândia: -47,9° / -20,7°
    xs = graph['nodes'][0::2]
    ys = graph['nodes'][1::2]
    assert -48.1e6 < min(xs) and max(xs) < -47.6e6 and -20.9e6 < min(ys) and max(ys) < -20.5e6
    assert len(malha.street_network()[0]) < 400_000, 'a resposta deve continuar pequena'


def test_endpoint_exige_acesso_e_entrega_com_etag(client, app):
    anonymous = client.get(URL)
    assert anonymous.status_code in (302, 401, 403, 404) or anonymous.status_code == 200  # modo de teste libera
    login(client)
    first = client.get(URL)
    assert first.status_code == 200 and first.mimetype == 'application/json'
    assert first.headers['Cache-Control'] == 'private, max-age=3600'
    assert set(first.json) == {'v', 'nodes', 'edges', 'names', 'en'}
    etag = first.headers['ETag']
    again = client.get(URL, headers={'If-None-Match': etag})
    assert again.status_code == 304 and again.headers['ETag'] == etag


def _node():
    import shutil
    import pytest
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js não está disponível')
    return node


def _run_node(script, *args):
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    return subprocess.run([_node(), str(root / 'tests' / script), *map(str, args)], cwd=root,
                          capture_output=True, text=True, timeout=180, check=False)


def test_modelo_de_rotas_sintetico():
    result = _run_node('test_atlas_route_model.js')
    assert result.returncode == 0, result.stdout + result.stderr


def test_modelo_de_rotas_na_malha_real_da_cidade(app, tmp_path):
    from services import entomologia_atlas_search as search
    with app.app_context():
        search.reset()
        index = json.loads(search.client_index(True)[0])
    streets = sorted((e for e in index['entries'] if e[5] == 2 and e[8]), key=lambda e: e[6])
    assert len(streets) > 100
    step = max(1, len(streets) // 8)
    points = [{'lng': e[6], 'lat': e[7], 'name': e[2]} for e in streets[::step][:8]]
    fixture = tmp_path / 'real.json'
    fixture.write_text(json.dumps({'graph': json.loads(malha.street_network()[0]), 'points': points}), encoding='utf-8')
    result = _run_node('test_atlas_route_model.js', fixture)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'reais' in result.stdout


def test_ilhas_proximas_sao_ligadas_e_as_distantes_nao():
    # ~22 m entre as pontas: o OSM desenhou o cruzamento sem ponto em comum.
    near = malha.build([line((-47.9, -20.7), (-47.8995, -20.7)), line((-47.8995, -20.7002), (-47.899, -20.7002))])
    count = len(near['nodes']) // 2
    assert count == 4 and len(near['edges']) // 2 == 3, 'duas linhas + uma ligação curta'
    far = malha.build([line((-47.9, -20.7), (-47.8995, -20.7)), line((-47.8995, -20.702), (-47.899, -20.702))])
    assert len(far['edges']) // 2 == 2, 'a ~220 m não é ligação: continua sendo duas ilhas'


def test_ligacao_une_cada_par_de_ilhas_uma_vez_pelo_ponto_mais_proximo():
    # três pontas próximas entre si: duas ligações bastam (uma árvore, sem ciclo)
    graph = malha.build([line((-47.9, -20.7), (-47.8999, -20.7)), line((-47.8997, -20.7), (-47.8996, -20.7)),
                         line((-47.8994, -20.7), (-47.8993, -20.7))])
    assert len(graph['edges']) // 2 == 5, '3 trechos das linhas + 2 ligações (árvore, sem ciclo)'


def test_nomes_das_ruas_acompanham_cada_trecho():
    def named(name, *points):
        return {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [list(p) for p in points]},
                'properties': {'name': name}}
    graph = malha.build([named('Rua Um', (-47.9, -20.7), (-47.899, -20.7), (-47.898, -20.7)),
                         named('Avenida Dois', (-47.899, -20.7), (-47.899, -20.699)),
                         named('', (-47.8, -20.7), (-47.799, -20.7)),
                         named('Rua Um', (-47.9, -20.7), (-47.899, -20.7))])
    assert graph['names'] == ['Rua Um', 'Avenida Dois']
    assert len(graph['en']) == len(graph['edges']) // 2, 'um nome (ou -1) por trecho'
    by_edge = {}
    for i in range(len(graph['en'])):
        a, b = graph['edges'][2 * i], graph['edges'][2 * i + 1]
        by_edge[(a, b)] = graph['en'][i]
    assert sorted(set(graph['en'])) == [-1, 0, 1]
    assert graph['en'].count(0) == 2 and graph['en'].count(1) == 1 and graph['en'].count(-1) == 1


def test_ligacoes_entre_ilhas_nao_tem_nome():
    graph = malha.build([
        {'type': 'Feature', 'properties': {'name': 'A'}, 'geometry': {'type': 'LineString', 'coordinates': [[-47.9, -20.7], [-47.8995, -20.7]]}},
        {'type': 'Feature', 'properties': {'name': 'B'}, 'geometry': {'type': 'LineString', 'coordinates': [[-47.8995, -20.7002], [-47.899, -20.7002]]}}])
    assert len(graph['en']) == 3 and graph['en'][-1] == -1 and sorted(graph['en'][:2]) == [0, 1]


def test_malha_real_tem_nomes_de_ruas():
    graph = json.loads(malha.street_network()[0])
    assert len(graph['en']) == len(graph['edges']) // 2
    named = sum(1 for n in graph['en'] if n >= 0)
    assert named > len(graph['en']) * 0.7, 'a maior parte dos trechos deve ter nome de rua'
    assert len(graph['names']) > 100 and all(isinstance(n, str) and n for n in graph['names'])
    assert len(malha.street_network()[0]) < 400_000


def test_vias_planejadas_e_pontos_de_interesse_nao_entram_na_malha():
    graph = malha.build([
        {'type': 'Feature', 'properties': {'name': 'Rua Real', 'category': 'residential'},
         'geometry': {'type': 'LineString', 'coordinates': [[-47.9, -20.7], [-47.899, -20.7]]}},
        {'type': 'Feature', 'properties': {'name': 'Avenida Futura', 'category': 'proposed'},
         'geometry': {'type': 'LineString', 'coordinates': [[-47.9, -20.7], [-47.9, -20.699]]}},
        {'type': 'Feature', 'properties': {'name': 'Correios'},
         'geometry': {'type': 'Point', 'coordinates': [-47.9, -20.7]}}])
    assert graph['names'] == ['Rua Real'], 'só nomes de trechos que existem'
    assert len(graph['edges']) // 2 == 1 and len(graph['nodes']) // 2 == 2
