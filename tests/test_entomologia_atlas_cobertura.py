"""Cobertura do atlas para a lista de vacinação: só rua, número e bairro; nada de posição estimada."""
import pytest

from services import entomologia_atlas_cobertura as cobertura
from services import entomologia_atlas_editor as editor
from services import entomologia_atlas_search as search


def _feature(i, name, geometry, **props):
    return {'type': 'Feature', 'id': 'f%d' % i, 'geometry': geometry,
            'properties': {'name': name, 'address': props.pop('address', name), 'category': '', **props}}


def _point(i):
    return {'type': 'Point', 'coordinates': [-47.9 + i / 1000, -20.7]}


def _layers():
    houses = {'id': 'cnefe', 'title': 'Endereços', 'clinical': False, 'deleted': False, 'origin': {'type': 'cnefe'},
              'features': [_feature(1, 'Rua 6, 20', _point(1)), _feature(2, 'Rua 6, 22', _point(2)),
                           _feature(3, 'Rua 9, 5', None),                      # cadastro sem posição: não conta
                           _feature(4, 'Avenida 3, 874', _point(4))]}
    streets = {'id': 'ref', 'title': 'Ruas', 'clinical': False, 'deleted': False, 'origin': {'type': 'reference'},
               'features': [_feature(10, 'Rua 6', {'type': 'LineString', 'coordinates': [[-47.9, -20.7], [-47.89, -20.7]]}),
                            _feature(11, 'Rua 9', {'type': 'LineString', 'coordinates': [[-47.9, -20.71], [-47.89, -20.71]]})]}
    return {'cnefe': houses, 'ref': streets}


@pytest.fixture
def atlas(app, monkeypatch):
    layers = _layers()
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: dict(layers))
    search.reset()
    with app.app_context():
        yield
    search.reset()


@pytest.mark.parametrize('street,number,expected', [
    ('Rua 6', '20', 'ponto'),
    ('R. 6', '22', 'ponto'),                # abreviação da planilha
    ('Rua Seis', '20', 'ponto'),            # por extenso
    ('rua 6', '020', 'ponto'),              # zero à esquerda
    ('Rua 6', '99', 'rua'),                 # a rua existe, a casa não
    ('Rua 9', '5', 'rua'),                  # número cadastrado sem posição não vale como ponto
    ('Avenida 3', '874', 'ponto'),
    ('Av. 3', '874', 'ponto'),
    ('Rua 77', '1', 'nenhum'),
    ('', '10', 'sem_rua'),
])
def test_situacao_de_cada_endereco(atlas, street, number, expected):
    assert cobertura.status_of(street, number) == expected


def test_sem_numero_cai_na_rua(atlas):
    assert cobertura.status_of('Rua 6', '') == 'rua'
    assert cobertura.status_of('Rua 6', 'S/N') == 'rua'


def test_totais_por_bairro_e_lista_do_que_ficou_de_fora(atlas):
    rows = [{'linha': 2, 'rua': 'Rua 6', 'numero': '20', 'bairro': 'Centro'},
            {'linha': 3, 'rua': 'Rua 6', 'numero': '99', 'bairro': 'Centro'},
            {'linha': 4, 'rua': 'Rua 77', 'numero': '1', 'bairro': 'Jardim Siena'},
            {'linha': 5, 'rua': '', 'numero': '1', 'bairro': ''}]
    result = cobertura.coverage(rows)
    assert (result['total'], result['ponto'], result['rua'], result['nenhum'], result['sem_rua']) == (4, 1, 1, 1, 1)
    assert result['por_bairro']['Centro'] == {'total': 2, 'ponto': 1, 'rua': 1, 'nenhum': 0, 'sem_rua': 0}
    assert result['por_bairro']['NÃO INFORMADO']['sem_rua'] == 1
    assert [(i['linha'], i['situacao']) for i in result['nao_resolvidos']] == [(3, 'rua'), (4, 'nenhum'), (5, 'sem_rua')]
    assert set(result['nao_resolvidos'][0]) == {'linha', 'rua', 'numero', 'situacao'}


def test_limite_de_linhas_por_chamada(atlas):
    rows = [{'linha': i, 'rua': 'Rua 6', 'numero': '20', 'bairro': 'Centro'} for i in range(cobertura.MAX_ROWS + 50)]
    result = cobertura.coverage(rows)
    assert result['total'] == cobertura.MAX_ROWS and result['cortado'] is True


def test_webhook_exige_token_e_devolve_contagens(client, atlas, monkeypatch):
    monkeypatch.setenv('PMO_SYNC_WEBHOOK_TOKEN', 'segredo-de-teste')
    body = {'rows': [{'linha': 2, 'rua': 'Rua 6', 'numero': '20', 'bairro': 'Centro', 'tutor': 'não deve ser lido'}]}
    assert client.post('/vacina-pmo/webhook/cobertura-atlas', json=body).status_code in (403, 404)   # o app esconde o 403 em JSON
    assert client.post('/vacina-pmo/webhook/cobertura-atlas', json=body, headers={'X-PMO-Token': 'errado'}).status_code in (403, 404)
    ok = client.post('/vacina-pmo/webhook/cobertura-atlas', json=body, headers={'X-PMO-Token': 'segredo-de-teste'})
    assert ok.status_code == 200
    data = ok.get_json()
    assert data['success'] and data['ponto'] == 1 and data['total'] == 1
    assert 'tutor' not in ok.get_data(as_text=True)
    bad = client.post('/vacina-pmo/webhook/cobertura-atlas', json={'x': 1}, headers={'X-PMO-Token': 'segredo-de-teste'})
    assert bad.status_code == 400


def test_webhook_sem_token_configurado_nega(client, monkeypatch):
    monkeypatch.delenv('PMO_SYNC_WEBHOOK_TOKEN', raising=False)
    assert client.post('/vacina-pmo/webhook/cobertura-atlas', json={'rows': []}, headers={'X-PMO-Token': ''}).status_code in (403, 404)
