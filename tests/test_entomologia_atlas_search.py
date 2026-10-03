"""Busca do atlas: resultado igual ao da regra original, mas com índice em cache."""
import json
import re
from copy import deepcopy

import pytest

from services import entomologia_atlas_editor as editor
from services import entomologia_atlas_search as fast
from services.entomologia_atlas import normalize
from tests.test_entomologia_atualizacao import login

BASE = '/sfa/entomologia/atlas'

QUERIES = [
    'Rua um', 'rua 1', 'Rua tres 120', 'avenida 5', 'av. brasil', 'Av 7', 'centro', 'a', 'praça',
    'rua vinte e um', 'Rua trinta e cinco', 'avenida cem', 'travessa dois', 'casa 12', 'casa 012',
    'quebec', 'torino', 'jardim', 'bandeirantes', 'Rua', 'escola, centro', 'ubs', 'sao paulo', 'são paulo',
    'rua 1 rua 2', '  espaços   demais ', 'xyzinexistente', '', 'a' * 241,
]


def legacy_search(query, allowed_clinical):
    """Cópia fiel da busca de produção de antes do índice (v1135): o resultado novo tem que ser idêntico."""
    q = editor.search_text(query)
    if not q or len(q) > 240:
        return []
    q = re.sub(r'\bav\.?\s', 'avenida ', q)
    pattern = r'\b(?:rua|avenida|alameda|travessa|casa) \d+[a-z]?\b'
    phrases = re.findall(pattern, q)
    tokens = re.sub(pattern, ' ', q).replace(',', ' ').split()
    result, grouped = [], {}
    for layer in editor.layers(allowed_clinical).values():
        for f in layer['features']:
            p = f['properties']
            hay = editor.search_text(' '.join(str(p.get(k, '')) for k in (
                'name', 'label', 'address', 'category', 'cep', 'neighborhood', 'cadastre_ref', 'original_street',
                'house_number')))
            if p.get('kind') == 'cadastre_house':
                hay += ' ' + editor.search_text('casa ' + str(p.get('house_number', '')) + ' '
                                                + ' '.join(p.get('folder_path', [])))
            if all(re.search(r'(?<!\w)' + re.escape(t) + r'(?!\w)', hay) for t in phrases) and all(
                    re.search(r'(?<!\d)' + re.escape(t) + r'(?!\d)', hay) if t.isdigit() else t in hay for t in tokens):
                identity = (layer['id'], normalize(p.get('name') or p.get('label')))
                if layer['origin']['type'] == 'reference' and identity in grouped:
                    base = grouped[identity]['feature']
                    if base['geometry']['type'] != 'GeometryCollection':
                        base['geometry'] = {'type': 'GeometryCollection', 'geometries': [base['geometry']]}
                    base['geometry']['geometries'].append(deepcopy(f['geometry']))
                    continue
                item = {'layer_id': layer['id'], 'layer_title': layer['title'], 'feature': deepcopy(f),
                        'located': f.get('geometry') is not None}
                grouped[identity] = item
                result.append(item)
    return sorted(result, key=lambda item: not item['located'])[:80]


@pytest.fixture(autouse=True)
def _fresh_index():
    fast.reset()
    yield
    fast.reset()


@pytest.mark.parametrize('query', QUERIES)
def test_busca_com_indice_e_identica_a_original(app, query):
    with app.app_context():
        assert fast.search(query, True) == legacy_search(query, True)
        assert fast.search(query, False) == legacy_search(query, False)


def test_indice_e_reaproveitado_e_refeito_quando_o_dado_muda(client, app, monkeypatch):
    login(client)
    calls = []
    original = editor.layers
    monkeypatch.setattr(editor, 'layers', lambda *a, **k: calls.append(1) or original(*a, **k))
    with app.app_context():
        fast.search('rua', True)
        fast.search('avenida', True)
        fast.search('centro', True)
        assert len(calls) == 1, 'o índice deveria ser montado uma única vez'
    layer = client.post(BASE + '/editor', json=dict(action='create_layer', revision=0, reason='teste',
                                                     title='Equipamentos', color='#087f81')).json
    feature = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-47.88, -20.72]},
               'properties': {'name': 'Posto Zephyrus', 'address': 'Rua 2, 100', 'category': 'Saúde'}}
    r = client.post(BASE + '/editor/' + layer['id'],
                    json=dict(action='create_feature', revision=layer['revision'], reason='teste', feature=feature))
    assert r.status_code == 200
    with app.app_context():
        found = fast.search('zephyrus', True)
        assert [i['feature']['properties']['name'] for i in found] == ['Posto Zephyrus']


def test_camadas_clinicas_so_aparecem_com_acesso_clinico(client, app):
    login(client)
    layer = client.post(BASE + '/editor', json=dict(action='create_layer', revision=0, reason='teste',
                                                     title='Casos clínicos', color='#b00020', clinical=True)).json
    feature = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-47.88, -20.72]},
               'properties': {'name': 'Caso Quimera', 'address': 'Rua 3, 50', 'category': 'Caso'}}
    client.post(BASE + '/editor/' + layer['id'],
                json=dict(action='create_feature', revision=layer['revision'], reason='teste', feature=feature))
    with app.app_context():
        assert fast.search('quimera', True)
        assert fast.search('quimera', False) == []
        assert any('quimera' in row[4] for row in json.loads(fast.client_index(True)[0])['entries'])
        assert not any('quimera' in row[4] for row in json.loads(fast.client_index(False)[0])['entries'])
        assert fast.place(layer['id'], '1', False) is None


def test_endpoint_do_indice_devolve_json_compacto_com_etag(client, app):
    login(client)
    r = client.get(BASE + '/busca/indice')
    assert r.status_code == 200 and r.mimetype == 'application/json'
    data = r.json
    assert set(data) == {'layers', 'entries'} and data['entries']
    layer_index, fid, name, address, hay, kind, x, y, bbox, cadastre, street = data['entries'][0]
    assert data['layers'][layer_index]['id'] and isinstance(hay, str) and kind in (0, 1, 2)
    assert r.headers['Referrer-Policy'] == 'no-referrer'
    # Admin tem acesso clínico: nada pode ficar guardado no navegador.
    assert r.headers['Cache-Control'] == 'private, no-store'


def test_endpoint_de_lugar_devolve_a_feicao_com_as_ruas_unidas(client, app):
    login(client)
    data = client.get(BASE + '/busca/indice').json
    street = next(e for e in data['entries'] if e[5] == 2)
    layer_id = data['layers'][street[0]]['id']
    r = client.get(BASE + '/busca/lugar', query_string={'layer': layer_id, 'feature': street[1]})
    assert r.status_code == 200
    body = r.json
    assert body['layer_id'] == layer_id and body['located'] and body['feature']['geometry']
    assert client.get(BASE + '/busca/lugar', query_string={'layer': 'nao-existe', 'feature': '1'}).status_code == 404


def _hay(p):
    hay = editor.search_text(' '.join(str(p.get(k, '')) for k in fast.HAY_FIELDS))
    if p.get('kind') == 'cadastre_house':
        hay += ' ' + editor.search_text('casa ' + str(p.get('house_number', '')) + ' ' + ' '.join(p.get('folder_path', [])))
    return hay


def test_indice_cobre_o_que_a_busca_do_servidor_encontra(app):
    """O navegador só pode deixar de achar o que o servidor acha por causa do agrupamento de ruas."""
    with app.app_context():
        payload = json.loads(fast.client_index(True)[0])
        hays = {(payload['layers'][row[0]]['id'], row[4]) for row in payload['entries']}
        for query in ('rua', 'avenida', 'centro', 'praça', 'quebec'):
            for item in fast.search(query, True):
                p = item['feature']['properties']
                assert (item['layer_id'], _hay(p)) in hays


def test_membro_sem_acesso_clinico_revalida_o_indice_com_etag(client, app, monkeypatch):
    from extensions import db
    from models.entomologia import EntomologiaEquipe
    login(client)
    clinical = client.post(BASE + '/editor', json=dict(action='create_layer', revision=0, reason='teste',
                                                        title='Casos', color='#b00020', clinical=True)).json
    client.post(BASE + '/editor/' + clinical['id'], json=dict(
        action='create_feature', revision=clinical['revision'], reason='teste',
        feature={'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-47.9, -20.7]},
                 'properties': {'name': 'Caso Sigiloso', 'address': 'Rua 9', 'category': 'Caso'}}))
    member = login(client, 'tutor')
    db.session.add(EntomologiaEquipe(user_id=member.id, concedido_por='admin'))
    db.session.commit()
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    https = {'base_url': 'https://localhost'}

    first = client.get(BASE + '/busca/indice', **https)
    assert first.status_code == 200
    assert first.headers['Cache-Control'] == 'private, max-age=0, must-revalidate'
    assert 'sigiloso' not in first.get_data(as_text=True).lower()
    etag = first.headers['ETag']

    again = client.get(BASE + '/busca/indice', headers={'If-None-Match': etag}, **https)
    assert again.status_code == 304 and again.headers['ETag'] == etag

    # Quando o dado muda, a etiqueta muda e o navegador baixa a versão nova.
    layer = client.post(BASE + '/editor', json=dict(action='create_layer', revision=0, reason='teste',
                                                     title='Equipe', color='#087f81'), **https).json
    client.post(BASE + '/editor/' + layer['id'], json=dict(
        action='create_feature', revision=layer['revision'], reason='teste',
        feature={'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-47.9, -20.7]},
                 'properties': {'name': 'Ponto Novo', 'address': 'Rua 4', 'category': 'Apoio'}}), **https)
    changed = client.get(BASE + '/busca/indice', headers={'If-None-Match': etag}, **https)
    assert changed.status_code == 200 and changed.headers['ETag'] != etag
    assert 'ponto novo' in changed.get_data(as_text=True).lower()

    # E o servidor nunca entrega a feição clínica pelo endpoint de lugar.
    assert client.get(BASE + '/busca/lugar', query_string={'layer': clinical['id'], 'feature': '1'}, **https).status_code == 404


def _synthetic_layers():
    def feat(i, name, located=True, **props):
        geometry = {'type': 'Point', 'coordinates': [-47.9 + i / 1000, -20.7]} if located else None
        return {'type': 'Feature', 'id': 'f%d' % i, 'geometry': geometry,
                'properties': {'name': name, 'address': props.pop('address', ''), 'category': props.pop('category', ''), **props}}
    cadastre = {'id': 'cad', 'title': 'Cadastro', 'clinical': False, 'deleted': False, 'origin': {'type': 'cadastre'},
                'features': [feat(1, 'Casa 12', located=False, kind='cadastre_house', house_number='12',
                                  cep='14620-010', neighborhood='Centro', original_street='Rua Quinze',
                                  folder_path=['Quadra S024Q045', 'Rua Quinze']),
                             feat(2, 'Casa 14', kind='cadastre_house', house_number='14', cep='14620-010',
                                  neighborhood='Centro', folder_path=['Quadra S024Q045']),
                             feat(3, 'Sem posição', located=False, cep='14620-999')]}
    streets = {'id': 'ref', 'title': 'Ruas', 'clinical': False, 'deleted': False, 'origin': {'type': 'reference'},
               'features': [feat(10, 'Rua Quinze', category='residential'), feat(11, 'Rua Quinze', category='residential'),
                            feat(12, 'Rua Quinze', category='primary'),
                            feat(13, 'Avenida I', category='residential'), feat(14, 'Avenida Internacional', category='primary'),
                            feat(15, 'Rua A', category='residential'), feat(16, 'Rua Amazonas', category='residential'),
                            feat(17, 'Acesso A Avenida Marginal Esquerda, sem número', category='service')]}
    many = {'id': 'many', 'title': 'Muitos', 'clinical': False, 'deleted': False, 'origin': {'type': 'cnefe'},
            'features': [feat(100 + i, 'Posto %d' % i, located=i % 3 != 0, address='Rua Quinze, %d' % i) for i in range(260)]}
    clinical = {'id': 'clin', 'title': 'Casos', 'clinical': True, 'deleted': False, 'origin': {'type': 'earth'},
                'features': [feat(900, 'Caso Quimera', address='Rua Quinze, 7')]}
    return {k: v for k, v in (('cad', cadastre), ('ref', streets), ('many', many), ('clin', clinical))}


@pytest.mark.parametrize('query', ['14620-010', '14620', 'casa 12', 'casa 14', 'quadra s024q045', 'centro',
                                   'rua quinze', 'rua 15', 'posto', 'posto 7', 'quimera', 'sem posicao', 'residential'])
def test_regras_de_producao_cep_cadastro_ordem_e_limite(app, monkeypatch, query):
    layers = _synthetic_layers()
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in layers.items() if allowed or not v['clinical']})
    with app.app_context():
        for allowed in (True, False):
            assert fast.search(query, allowed) == legacy_search(query, allowed)
        # posicionados primeiro e no máximo 80
        found = fast.search('posto', True)
        assert len(found) == 80 and all(i['located'] for i in found)
        assert [i['located'] for i in fast.search('casa', True)][:1] == [True]


@pytest.mark.parametrize('query', ['14620010', '14620-010', '14620 010'])
def test_cep_funciona_so_com_numeros(app, monkeypatch, query):
    layers = _synthetic_layers()
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in layers.items() if allowed or not v['clinical']})
    fast.reset()
    with app.app_context():
        names = {i['feature']['properties']['name'] for i in fast.search(query, True)}
        if query == '14620 010':
            return  # separado por espaço não é CEP; só não pode quebrar
        assert {'Casa 12', 'Casa 14'} <= names
        assert 'Sem posição' not in names  # outro CEP (14620-999) não entra


def _names(query, allowed=True):
    return sorted({i['feature']['properties']['name'] for i in fast.search(query, allowed)})


def test_rua_de_nome_em_letra_acha_a_rua_exata(app, monkeypatch):
    """"Avenida i" achava qualquer endereço com a letra i; agora a avenida I vem sozinha."""
    layers = _synthetic_layers()
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in layers.items() if allowed or not v['clinical']})
    fast.reset()
    with app.app_context():
        assert _names('Avenida i') == ['Avenida I']
        assert _names('avenida I') == ['Avenida I']
        assert _names('Av. i') == ['Avenida I']
        assert _names('Rua A') == ['Rua A']
        # Passou da letra: volta ao casamento por prefixo, sem a rua exata.
        assert 'Avenida Internacional' in _names('avenida in') and 'Avenida I' not in _names('avenida in')
        assert 'Rua Amazonas' in _names('rua am')
        # Rua em letra que não existe: cai no casamento solto de antes (a pessoa pode estar digitando outra rua).
        assert 'Rua Amazonas' in _names('rua a') or _names('rua a') == ['Rua A']
        assert _names('avenida z') == []


def test_montagem_do_indice_e_uma_so_mesmo_com_varias_requisicoes_ao_mesmo_tempo(app, monkeypatch):
    """Com o cache vazio, índice + buscas + pré-montagem chegavam juntos e cada um montava a sua cópia (R14/R15)."""
    import threading
    import time
    layers = _synthetic_layers()
    calls = []

    def slow_layers(allowed, include_deleted=False):
        calls.append(1)
        time.sleep(0.4)                       # tempo para as outras threads chegarem
        return {k: deepcopy(v) for k, v in layers.items() if allowed or not v['clinical']}
    monkeypatch.setattr(editor, 'layers', slow_layers)
    fast.reset()
    results = []

    def work(kind):
        with app.app_context():
            results.append(fast.client_index(True) if kind == 'index' else fast.search('rua quinze', True))
    threads = [threading.Thread(target=work, args=(k,)) for k in ('index', 'index', 'search', 'search', 'search')]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    assert len(calls) == 1, f'montou {len(calls)} vezes ao mesmo tempo'
    assert len(results) == 5
    indices = [r for r in results if isinstance(r, tuple)]
    assert len(indices) == 2 and indices[0] == indices[1]          # os dois pedidos do índice recebem o mesmo payload


def test_sem_banco_as_requisicoes_simultaneas_dividem_uma_montagem(app, monkeypatch):
    """Banco indisponível (assinatura None): sem cache, mas uma só montagem, repartida entre as requisições simultâneas."""
    import threading
    import time
    layers = _synthetic_layers()
    state = {'now': 0, 'peak': 0, 'calls': 0}
    guard = threading.Lock()

    def layers_fn(allowed, include_deleted=False):
        with guard:
            state['now'] += 1
            state['calls'] += 1
            state['peak'] = max(state['peak'], state['now'])
        time.sleep(0.15)
        with guard:
            state['now'] -= 1
        return {k: deepcopy(v) for k, v in layers.items()}
    monkeypatch.setattr(editor, 'layers', layers_fn)
    monkeypatch.setattr(fast, '_signature', lambda: None)
    fast.reset()

    def work():
        with app.app_context():
            fast.search('rua quinze', True)
    threads = [threading.Thread(target=work) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    assert state['calls'] == 1 and state['peak'] == 1, state   # quem chega junto reaproveita a mesma montagem


def test_pre_montagem_do_indice_em_segundo_plano(app, monkeypatch):
    layers = _synthetic_layers()
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in layers.items() if allowed or not v['clinical']})
    fast.reset()
    thread = fast.warm_async(app, True)
    assert thread is not None
    thread.join(timeout=60)
    assert not thread.is_alive()
    with fast._lock:
        assert not fast._warming
    with app.app_context():
        snap = fast.snapshot()
        if snap.signature is not None:        # com assinatura o payload fica guardado e a requisição o reaproveita
            assert (snap.signature, True) in fast._payloads
        body, _etag = fast.client_index(True)
    assert json.loads(body)['entries']


def test_pre_montagem_nao_duplica_trabalho_nem_quebra_a_tela(app, monkeypatch):
    fast.reset()
    with fast._lock:
        fast._warming.add(True)
    try:
        assert fast.warm_async(app, True) is None          # já há uma montando
    finally:
        with fast._lock:
            fast._warming.discard(True)

    def boom(allowed, include_deleted=False):
        raise RuntimeError('banco fora')
    monkeypatch.setattr(editor, 'layers', boom)
    fast.reset()
    thread = fast.warm_async(app, False)
    thread.join(timeout=60)
    assert not thread.is_alive()                           # a falha é registrada e não derruba nada
    with fast._lock:
        assert not fast._warming


TEXTS = ['Rua Um', 'RUA UM, 12', 'Av. Brasil 100', 'Avenida   Sete', 'Rua vinte e um', 'Rua trinta e nove', 'Travessa Dois 0045',
         'casa 007', 'Casa 0', 'rua quinze', 'Rua Dezesseis', 'rua cem', 'rua cento e dois', 'Alameda Vinte', 'Rua Trinta',
         'São José do Rio Preto', 'AÇÚCAR e café', 'Praça 9 de Julho', 'rua 01', 'avenida 007b', 'Rua Um e Rua Dois',
         '  espaços  ', 'ÁGUA', 'Ruas Unidas', 'avenida vinte e cinco', 'rua dois mil', 'casa 12', 'CEP 14620-010', '']


def _variant(name, app, allowed, queries):
    with app.app_context():
        payload = json.loads(fast.client_index(allowed)[0])
        expected = []
        for q in queries:
            expected.append([q, [[i['layer_id'], str(i['feature']['id'])] for i in fast.search(q, allowed)]])
    return {'name': name, 'index': payload, 'queries': expected}


def test_busca_no_navegador_equivale_ao_servidor(app, monkeypatch, tmp_path):
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js não está disponível')
    queries = QUERIES + ['14620-010', '14620', 'casa 12', 'casa 14', 'quadra s024q045', 'rua quinze', 'rua 15',
                         'posto', 'posto 7', 'quimera', 'sem posicao', 'residential', 'rua quinze 12', '15',
                         'avenida i', 'Avenida I', 'Av. i', 'rua a', 'avenida in', 'avenida z', 'rua am', 'rua e', 'travessa b',
                         'avenida i 120', 'rua a 5']
    variants = [_variant('dados reais', app, True, QUERIES)]
    layers = _synthetic_layers()
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in layers.items() if allowed or not v['clinical']})
    fast.reset()
    variants += [_variant('sintético, com acesso clínico', app, True, queries),
                 _variant('sintético, sem acesso clínico', app, False, queries)]
    fixture = {'texts': [[t, editor.search_text(t)] for t in TEXTS], 'variants': variants}
    path = tmp_path / 'fixture.json'
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, str(root / 'tests' / 'test_atlas_search_model.js'), str(path)], cwd=root,
                            capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
