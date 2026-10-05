"""Camada Dengue Automatizados: endereços da planilha posicionados só com a base do atlas.

Todos os nomes, telefones e endereços aqui são fictícios.
"""
import json
from pathlib import Path

import pytest

from services import entomologia_atlas as atlas
from services import entomologia_dengue_auto as dengue
from tests.test_entomologia_atualizacao import login

URL = '/sfa/entomologia/atlas/dengue-automatizados'
LON, LAT = -47.88, -20.72
HEADER = ['Carimbo de data/hora', 'Agravo/Doença ', 'N Ficha Epidemiológica ', 'SINAN', 'Unidade Notificante ',
          'Data notificação ', 'Data inicio sintomas', 'Nome ', 'Data Nascimento ', 'Endereço', 'Bairro',
          'Telefone para contato', 'Local de Trabalho/Estudo', 'Deslocamento', 'Informações complementares',
          'Tipo de Exame ', 'Resultado ', 'Resultado final', 'Classificação do Caso', 'Responsável pelo preenchimento']


def east(meters, north=0):
    return [round(LON + meters / dengue.MX, 7), round(LAT + north / dengue.MY, 7)]


def reference(*houses, condo=()):
    """Base de endereços fictícia: ``(rua, número, [lon, lat], bairro)`` e casas ``(condomínio, casa, [lon, lat])``."""
    layers = {'cnefe-teste': {'id': 'cnefe-teste', 'title': 'Bairro de teste', 'clinical': False, 'deleted': False,
                              'origin': {'type': 'cnefe', 'title': 'IBGE'}, 'folders': [], 'revision': 0, 'features': [
        {'type': 'Feature', 'id': f'cnefe-{i}', 'geometry': {'type': 'Point', 'coordinates': point},
         'properties': {'street': street, 'house_number': number, 'neighborhood': hood, 'kind': 'cnefe_house',
                        'name': f'{street}, {number}'}}
        for i, (street, number, point, hood) in enumerate(houses)]}}
    if condo:
        layers['condo-teste'] = {'id': 'condo-teste', 'title': 'Casas', 'clinical': False, 'deleted': False,
                                 'origin': {'type': 'condominium'}, 'folders': [], 'revision': 0, 'features': [
            {'type': 'Feature', 'id': f'{name}-casa-{house}', 'geometry': {'type': 'Point', 'coordinates': point},
             'properties': {'condominium': name, 'house_number': str(house), 'block': '899A', 'sector': '103'}}
            for name, house, point in condo]}
    return layers


def sheet(*rows):
    return [list(HEADER)] + [list(r) for r in rows]


def case(ficha, sinan, address, hood='Centro', symptoms='01/01/2026', notified='05/01/2026',
         result='Negativo Clin. Epidemiológico', disease='Dengue'):
    return ['05/01/2026 16:04:46', disease, ficha, sinan, 'UBS FICTICIA', notified, symptoms, 'PESSOA FICTICIA DA SILVA',
            '01/02/1990', address, hood, '16999990001', 'ESCOLA FICTICIA', 'N/A', 'observação livre', 'NS1', result, '',
            'Autoctone', 'DIGITADOR FICTICIO']


def find(address, hood, layers):
    return dengue.locate(dengue.parse_address(address), hood, dengue.AddressIndex(layers))


@pytest.fixture()
def no_street_check(monkeypatch):
    """Os pontos fictícios não ficam sobre as ruas reais do atlas."""
    monkeypatch.setattr(dengue, '_far_from_street', lambda parsed, geometry: None)


@pytest.mark.parametrize('text,street,number,suffix', [
    ('RUA 11 2130', 'rua 11', 2130, ''), ('ALAMEDA 12 351-A', 'alameda 12', 351, 'a'),
    ('RUA 12 1035 A', 'rua 12', 1035, 'a'), ('AL 26 2229', 'alameda 26', 2229, ''),
    ('AV Y 1266', 'avenida y', 1266, ''), ('AVENIDA N 674 SIENA', 'avenida n', 674, ''),
    ('RUA A N 33', 'rua a', 33, ''), ('AVENIDA J N1481', 'avenida j', 1481, ''),
    ('AVENIDA 08, 1362', 'avenida 8', 1362, ''), ('Rua Doze nº 239', 'rua 12', 239, ''),
    ('AVENIDA DO CAFÉ 573 APTO 91', 'avenida do cafe', 573, ''), ('TRAVESSA H 15', 'travessa h', 15, ''),
    ('AVENIDA 9 377      AVENIDA 9 377', 'avenida 9', 377, ''), ('RUA 7', 'rua 7', None, '')])
def test_typed_addresses_become_street_number_and_letter(text, street, number, suffix):
    parsed = dengue.parse_address(text)
    assert (parsed['street'], parsed['number'], parsed['suffix']) == (street, number, suffix)


def test_complement_keeps_only_structured_parts_never_free_text():
    parsed = dengue.parse_address('RUA 5 438 APTO 1 CASA DA PESSOA FICTICIA')
    assert dengue.address_label(parsed) == 'Rua 5, 438 · Apto 1'
    condo = dengue.parse_address('RUA 20 955 CASA 177 QUEBEC')
    assert (condo['condominium'], condo['house']) == ('Quebec', 177)
    assert dengue.parse_address('CONDOMINIO QUEBECK CASA 144')['house'] == 144
    assert dengue.address_label(dengue.parse_address('CONDOMINIO PARIS CASA 45')) == 'Condomínio Paris · Casa 45'
    assert dengue.parse_address('ASSENTAMENTO BOA SORTE') is None and dengue.parse_address('') is None


def test_exact_address_uses_an_original_reference_coordinate():
    layers = reference(('Rua 11', '2130', east(0), 'Centro'), ('Rua 11', '2130', east(3), 'Centro'),
                       ('Rua 11', '2140', east(12), 'Centro'), ('Rua 1', '2130', east(900), 'Centro'))
    found = find('RUA 11 2130', 'Centro', layers)
    assert (found['method'], found['confidence']) == ('exato', 'alta')
    assert found['geometry']['coordinates'] in ([round(v, 6) for v in east(0)], [round(v, 6) for v in east(3)])


def test_letter_is_weak_evidence_but_is_reported():
    layers = reference(('Rua 8', '353', east(0), 'Jardim Boa Vista'), ('Rua 8', '363', east(10), 'Jardim Boa Vista'))
    found = find('RUA 8 353-A JBV', 'Jardim Boa Vista', layers)
    assert (found['method'], found['confidence']) == ('exato_sufixo', 'alta')
    assert any('353-A' in issue and '353' in issue for issue in found['issues'])


def test_same_number_in_two_stretches_is_decided_by_letter_then_neighborhood_or_left_unplaced():
    far = east(2500)
    layers = reference(('Rua 3', '851', east(0), 'Centro'), ('Rua 3', '851A', far, 'Jardim Parisi'))
    assert find('RUA 3 851-A', '', layers)['geometry']['coordinates'] == [round(v, 6) for v in far]
    assert find('RUA 3 851', '', layers)['geometry']['coordinates'] == [round(v, 6) for v in east(0)]
    twins = reference(('Rua 3', '851', east(0), 'Centro'), ('Rua 3', '851', far, 'Jardim Parisi'))
    assert find('RUA 3 851', 'Jardim Parisi', twins)['geometry']['coordinates'] == [round(v, 6) for v in far]
    undecided = find('RUA 3 851', '', twins)
    assert undecided['geometry'] is None and 'mais de um trecho' in undecided['precision']
    # Letra e bairro apontam para trechos diferentes: fica no da letra, com confiança baixa e o aviso.
    conflict = find('RUA 3 851-A', 'Centro', layers)
    assert conflict['confidence'] == 'baixa' and any('Centro' in issue for issue in conflict['issues'])


def test_missing_number_is_interpolated_between_neighbours_on_the_same_side():
    layers = reference(('Rua 2', '2006A', east(0), 'Santa Rita'), ('Rua 2', '2016A', east(10), 'Santa Rita'),
                       ('Rua 2', '2011A', east(5, 14), 'Santa Rita'), ('Rua 2', '2015A', east(9, 14), 'Santa Rita'))
    found = find('RUA 2 2013', 'Jardim Santa Rita', layers)
    assert (found['method'], found['confidence']) == ('interpolado', 'media')
    # Ímpar: entre 2011A e 2015A, do outro lado da rua (14 m ao norte), e não entre 2006A e 2016A.
    assert dengue.distance_m(found['geometry']['coordinates'], east(7, 14)) < 1
    assert '2011A' in found['precision'] and '2015A' in found['precision']


def test_one_sided_neighbour_and_unknown_addresses_are_explained():
    layers = reference(('Rua 9', '100', east(0), 'Centro'), ('Rua 9', '110', east(10), 'Centro'))
    near = find('RUA 9 122', 'Centro', layers)
    assert (near['method'], near['confidence']) == ('vizinho', 'baixa')
    assert near['geometry']['coordinates'] == [round(v, 6) for v in east(10)]
    for address, reason in (('RUA 9 900', 'fora da faixa'), ('RUA 77 10', 'não está na base'), ('RUA 9', 'sem número'),
                            ('CHACARA RECANTO', 'sem logradouro'), ('CONDOMINIO PARIS CASA 45', 'não tem croqui')):
        found = find(address, 'Centro', layers)
        assert found['geometry'] is None and reason in found['precision'], address


def test_condominium_house_comes_from_the_atlas_sketch():
    layers = reference(('Rua 20', '67', east(0), 'Centro'), condo=[('Quebec', 177, east(500)), ('Quebec', 67, east(520))])
    found = find('RUA 20 955 CASA 177 QUEBEC', 'Morada do Sol', layers)
    assert (found['method'], found['confidence'], found['block']) == ('condominio', 'media', ('899A', '103'))
    # "Rua 20 67 Condomínio Quebec": o 67 é a casa, não o imóvel de mesmo número no Centro.
    guessed = find('RUA 20 67 CONDOMINIO QUEBEC', 'Morada do Sol', layers)
    assert guessed['confidence'] == 'baixa' and guessed['geometry']['coordinates'] == [round(v, 6) for v in east(520)]
    assert find('CONDOMINIO QUEBEC', '', layers)['geometry'] is None
    assert find('CONDOMINIO TORINO CASA 9', '', layers)['geometry'] is None


def test_block_is_the_containing_or_the_touching_one():
    territory = json.loads((Path(dengue.__file__).parent / 'data' / 'entomologia' / 'territory.json').read_text(encoding='utf-8'))
    feature = next(f for f in territory['features'] if f['properties'].get('geometry_valid') and not f['properties'].get('duplicate_key'))
    block, distance = dengue.block_of(feature['properties']['label'])
    assert (block['block'], block['sector'], distance) == (feature['properties']['block'], feature['properties']['sector'], 0)
    assert dengue.block_of([-40.0, -10.0]) is None


def test_layer_has_month_folders_stable_ids_and_no_personal_data(no_street_check):
    layers = reference(('Rua 11', '2130', east(0), 'Centro'), ('Rua 11', '2140', east(10), 'Centro'))
    values = sheet(case('001', '9000001', 'RUA 11 2130'),
                   case('002', 'PESSOA FICTICIA DA SILVA', 'RUA 11 2140 CASA DA PESSOA FICTICIA', symptoms='10/02/2026', notified='12/02/2026',
                        result='Positivo Clin. Epidemiológico'),
                   case('003', '9000003', 'SITIO FICTICIO', symptoms='07/01/2025', notified='07/01/2026'),
                   case('004', '9000004', 'RUA 11 2130', disease='Chikungunya'), [''] * 20)
    layer, summary = dengue.build(values, layers, read_at='2026-10-05T12:00:00+00:00')
    assert (layer['id'], layer['title'], layer['clinical']) == ('auto-dengue', 'Dengue Automatizados', True)
    assert [f['name'] for f in layer['folders']] == ['Janeiro 2025', 'Janeiro 2026', 'Fevereiro 2026']
    assert [f['id'] for f in layer['features']] == ['dengue-auto-sinan-9000001', 'dengue-auto-ficha-2', 'dengue-auto-sinan-9000003']
    first, second, third = (f['properties'] for f in layer['features'])
    assert first['folder_id'] == 'auto-dengue-2026-01' and first['date'] == '2026-01-01' and first['month'] == '01'
    assert first['position_status'] == 'estimated' and first['auto_coordinates'] == layer['features'][0]['geometry']['coordinates']
    assert second['category'] == 'Positivo' and second['sinan'] == '' and second['name'] == 'Rua 11, 2140'
    assert third['position_status'] == 'unlocated' and layer['features'][2]['geometry'] is None
    assert 'confira o ano' in third['notes']
    assert summary['rows'] == 3 and summary['other_diseases'] == 1 and summary['located'] == 2 and summary['manual'] is None
    text = json.dumps(layer, ensure_ascii=False)
    for private in ('PESSOA', 'FICTICIA', '16999990001', '01/02/1990', 'ESCOLA', 'DIGITADOR', 'UBS', 'observação livre'):
        assert private not in text, private
    report = dengue.report_rows(layer)
    assert report[0][0] == 'Linha da planilha' and len(report) == 4 and 'PESSOA' not in json.dumps(report, ensure_ascii=False)


def test_changed_header_stops_the_update():
    values = sheet(case('001', '9000001', 'RUA 11 2130'))
    values[0][9] = 'Telefone'
    with pytest.raises(ValueError):
        dengue.build(values, reference())


def test_comparison_with_manual_markers_by_sinan_and_address(no_street_check):
    layers = reference(('Rua 11', '2130', east(0), 'Centro'), ('Rua 11', '2140', east(10), 'Centro'),
                       ('Rua 11', '2150', east(20), 'Centro'))
    marker = lambda fid, point, **p: {'type': 'Feature', 'id': fid, 'geometry': {'type': 'Point', 'coordinates': point},
                                      'properties': {'layer': 'Casos Dengue', **p}}
    layers['earth-' + atlas.layer_id('Casos Dengue')] = {'id': 'manual', 'title': 'Casos Dengue', 'clinical': True,
        'origin': {'type': 'earth'}, 'features': [marker('m1', east(0, 30), sinan='9000001', address='Rua 99, 1'),
                                                   marker('m2', east(10, 12), address='RUA 11 Nº 2140'),
                                                   marker('m3', east(700), address='Avenida 1, 5')]}
    values = sheet(case('001', '9000001', 'RUA 11 2130'), case('002', '9000002', 'RUA 11 2140'), case('003', '9000003', 'RUA 11 2150'))
    layer, summary = dengue.build(values, layers, today='05/10/2026')
    one, two, three = (f['properties'] for f in layer['features'])
    assert (one['manual_match'], one['manual_distance_m']) == ('sinan', 30)
    assert (two['manual_match'], two['manual_distance_m']) == ('endereco', 12)
    assert 'manual_match' not in three and 'Sem marcador manual' in three['notes']
    assert 'a 12 m, em 05/10/2026' in two['notes']
    assert summary['manual'] == {'markers': 3, 'compared': 2, 'median_m': 21, 'within_25m': 1, 'within_50m': 2,
                                 'within_100m': 2, 'over_100m': 0, 'rows_without_marker': 1, 'markers_without_row': 1}


def test_far_from_the_named_street_lowers_confidence(monkeypatch):
    monkeypatch.setattr(dengue, '_far_from_street', lambda parsed, geometry: 140.0)
    layer, summary = dengue.build(sheet(case('001', '9000001', 'RUA 11 2130')), reference(('Rua 11', '2130', east(0), 'Centro')))
    p = layer['features'][0]['properties']
    assert p['geocode_confidence'] == 'baixa' and '140 m da Rua 11' in p['notes'] and summary['confidence'] == {'baixa': 1}


def test_team_corrections_survive_the_next_update(no_street_check):
    layers = reference(('Rua 11', '2130', east(0), 'Centro'), ('Rua 11', '2140', east(10), 'Centro'))
    values = sheet(case('001', '9000001', 'RUA 11 2130'), case('002', '9000002', 'RUA 11 2140'))
    first, _ = dengue.build(values, layers)
    moved = json.loads(json.dumps(first))                      # como volta do banco
    moved['features'][0]['geometry']['coordinates'] = east(40, 25)
    moved['features'][0]['properties']['precision'] = 'Entrada conferida no campo'
    layers['cnefe-teste']['features'][1]['geometry']['coordinates'] = east(14)   # a base de endereços mudou
    second, summary = dengue.build(values, layers, previous=moved)
    kept, redone = second['features']
    assert kept['geometry']['coordinates'] == east(40, 25) and kept['properties']['geocode_method'] == 'equipe'
    assert kept['properties']['precision'] == 'Entrada conferida no campo' and 'A equipe ajustou' in kept['properties']['notes']
    assert kept['properties']['auto_coordinates'] == [round(v, 6) for v in east(0)]
    assert redone['geometry']['coordinates'] == [round(v, 6) for v in east(14)]
    assert summary['methods'] == {'equipe': 1, 'exato': 1}


def _served(monkeypatch, values, layers):
    from services import entomologia_cnefe
    monkeypatch.setattr(entomologia_cnefe, 'source_layers', lambda: {k: json.loads(json.dumps(v)) for k, v in layers.items()})
    monkeypatch.setattr(atlas, 'sheet_values', lambda force=False: (values, '2026-10-05T12:00:00+00:00'))
    monkeypatch.setattr(dengue, '_far_from_street', lambda parsed, geometry: None)


def test_update_route_writes_one_audited_clinical_revision_and_stays_local(client, app, monkeypatch):
    import urllib.request
    from models.entomologia import EntomologiaImportacao as E
    from services import entomologia_atlas_editor as editor
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Nenhum endereço pode sair do atlas'))
    _served(monkeypatch, sheet(case('001', '9000001', 'RUA 11 2130'), case('002', '9000002', 'RUA 11 2136', symptoms='03/02/2026')),
            reference(('Rua 11', '2130', east(0), 'Centro'), ('Rua 11', '2140', east(10), 'Centro')))
    login(client)
    response = client.post(URL, json={})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json['layer_id'] == 'auto-dengue' and response.json['summary']['located'] == 2
    assert response.headers['Cache-Control'] == 'private, no-store'
    layer = client.get('/sfa/entomologia/atlas/editor/auto-dengue').json
    assert layer['clinical'] and layer['origin']['type'] == 'sheet_snapshot' and layer['origin']['automatic']
    assert [f['properties']['folder_path'] for f in layer['features']] == [['Dengue Automatizados', 'Janeiro 2026'],
                                                                           ['Dengue Automatizados', 'Fevereiro 2026']]
    assert layer['features'][1]['properties']['geocode_method'] == 'interpolado'
    catalog = next(item for item in client.get('/sfa/entomologia/atlas/camadas').json['layers'] if item['id'] == 'auto-dengue')
    assert catalog['count'] == 2 and catalog['automation']['rows'] == 2 and len(catalog['folders']) == 2
    assert 'PESSOA' not in client.get('/sfa/entomologia/atlas/camadas/auto-dengue').get_data(as_text=True)
    # Atualizar de novo substitui a revisão ativa em vez de criar outra camada, e o histórico registra quem atualizou.
    again = client.post(URL, json={})
    assert again.status_code == 200 and again.json['revision'] != response.json['revision']
    assert E.query.filter_by(tipo=editor.TIPO, titulo='auto-dengue', status='ATIVA').count() == 1
    history = client.get('/sfa/entomologia/atlas/editor/auto-dengue/historico').json['revisions']
    assert len(history) == 2 and history[0]['action'] == 'sync_dengue' and history[0]['located'] == 2
    report = client.get(URL + '/conferencia.csv')
    assert report.status_code == 200 and report.mimetype == 'text/csv'
    body = report.get_data(as_text=True)
    assert 'Rua 11, 2136' in body and 'Interpolado entre vizinhos' in body and 'PESSOA' not in body
    assert 'attachment' in report.headers['Content-Disposition'] and report.headers['Cache-Control'] == 'private, no-store'


def test_team_edit_in_the_editor_is_kept_by_the_route(client, app, monkeypatch):
    _served(monkeypatch, sheet(case('001', '9000001', 'RUA 11 2130')), reference(('Rua 11', '2130', east(0), 'Centro')))
    login(client)
    assert client.post(URL, json={}).status_code == 200
    target = '/sfa/entomologia/atlas/editor/auto-dengue'
    layer = client.get(target).json
    feature = layer['features'][0]
    moved = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': east(35, 20)}, 'properties': {'name': feature['properties']['name']}}
    saved = client.post(target, json={'action': 'update_feature', 'revision': layer['revision'], 'reason': 'Entrada conferida',
                                      'feature_id': feature['id'], 'feature': moved})
    assert saved.status_code == 200, saved.get_data(as_text=True)
    assert client.post(URL, json={}).status_code == 200
    kept = client.get(target).json['features'][0]
    assert kept['geometry']['coordinates'] == east(35, 20) and kept['properties']['geocode_method'] == 'equipe'


def test_only_identified_administrators_update_and_read_the_layer(client, app, monkeypatch):
    from extensions import db
    from flask import g
    from models.entomologia import EntomologiaEquipe
    _served(monkeypatch, sheet(case('001', '9000001', 'RUA 11 2130')), reference(('Rua 11', '2130', east(0), 'Centro')))
    login(client)
    assert client.post(URL, json={}).status_code == 200
    member = login(client, 'tutor')
    db.session.add(EntomologiaEquipe(user_id=member.id, concedido_por='admin'))
    db.session.commit()
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    https = {'base_url': 'https://localhost'}
    assert client.post(URL, json={}, **https).status_code == 403
    assert client.get(URL + '/conferencia.csv', **https).status_code == 404
    assert client.get('/sfa/entomologia/atlas/camadas/auto-dengue', **https).status_code == 404
    stub = next(item for item in client.get('/sfa/entomologia/atlas/camadas', **https).json['layers'] if item['id'] == 'auto-dengue')
    assert stub['allowed'] is False and 'automation' not in stub and stub['count'] is None
    with client.session_transaction() as session:
        session.clear()
    g.pop('_login_user', None)
    monkeypatch.setenv('SFA_ADMIN_TOKEN', 'read-only-test')
    assert client.post(URL + '?token=read-only-test', json={}, **https).status_code in (302, 401, 403)


def test_sheet_failures_do_not_touch_the_layer(client, app, monkeypatch):
    from models.entomologia import EntomologiaImportacao as E
    login(client)
    monkeypatch.setattr(atlas, 'sheet_values', lambda force=False: (_ for _ in ()).throw(RuntimeError('sem rede')))
    assert client.post(URL, json={}).status_code == 503
    monkeypatch.setattr(atlas, 'sheet_values', lambda force=False: ([['outra', 'planilha']], ''))
    refused = client.post(URL, json={})
    assert refused.status_code == 400 and 'cabeçalho' in refused.json['error']
    assert E.query.filter_by(titulo='auto-dengue').count() == 0
    assert client.get(URL + '/conferencia.csv').status_code == 404


def test_update_requires_csrf_like_the_other_atlas_writes(client, app, monkeypatch):
    from models.entomologia import EntomologiaImportacao as E
    _served(monkeypatch, sheet(case('001', '9000001', 'RUA 11 2130')), reference(('Rua 11', '2130', east(0), 'Centro')))
    login(client)
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post(URL, json={}).status_code == 400
    assert E.query.filter_by(titulo='auto-dengue').count() == 0


def test_page_offers_the_update_to_administrators(client, app):
    login(client)
    html = client.get('/sfa/entomologia').get_data(as_text=True)
    for marker in ('id="atlas-auto-list"', 'id="atlas-auto-status"', 'id="atlas-auto-sync"', 'id="atlas-auto-report"',
                   'id="atlas-hot-notifications"', '/sfa/entomologia/atlas/dengue-automatizados'):
        assert marker in html, marker
