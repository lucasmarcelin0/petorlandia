"""Índice do atlas pré-calculado e guardado no banco: busca instantânea mesmo depois de reiniciar o site."""

import gzip
import json

import pytest

from services import entomologia_atlas_artefatos as artefatos
from services import entomologia_atlas_editor as editor
from services import entomologia_atlas_search as fast
from tests.test_entomologia_atlas_search import BASE, QUERIES, _synthetic_layers
from tests.test_entomologia_atualizacao import login

CONSULTAS = QUERIES + ['14620-010', '14620', 'casa 12', 'rua quinze', 'rua 15', 'posto', 'quimera', '15',
                       'avenida i', 'Av. i', 'rua a', 'avenida in', 'avenida z', 'rua am', 'travessa b', 'rua a 5']


@pytest.fixture
def ligado(app, monkeypatch):
    """Artefatos ligados, camadas sintéticas e uma assinatura de dados controlada pelo teste."""
    layers = _synthetic_layers()
    estado = {'assinatura': ((1, 'a'),), 'montagens': 0}
    original_snapshot = fast.snapshot

    def contar():
        estado['montagens'] += 1
        return original_snapshot()

    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in json.loads(json.dumps(layers)).items() if allowed or not v['clinical']})
    monkeypatch.setattr(fast, '_signature', lambda: estado['assinatura'])
    app.config['ATLAS_ARTEFATOS'] = True
    fast.reset()
    artefatos._bytes.clear()
    artefatos._parsed.clear()
    artefatos._falhou_em[0] = 0.0
    artefatos._building[0] = False
    with app.app_context():
        from models.entomologia import EntomologiaAtlasArtefato
        EntomologiaAtlasArtefato.query.delete()
    yield estado
    import threading
    for thread in threading.enumerate():                  # montagens em segundo plano terminam dentro do teste
        if thread.name == 'atlas-artefatos':
            thread.join(10)
    artefatos._falhou_em[0] = 0.0
    app.config.pop('ATLAS_ARTEFATOS', None)
    fast.reset()
    artefatos._bytes.clear()
    artefatos._parsed.clear()


def _json(gz):
    return json.loads(gzip.decompress(gz))


def test_indice_pronto_e_identico_ao_montado_na_hora(app, ligado):
    with app.app_context():
        esperado = {c: json.loads(fast.client_index(c)[0]) for c in (True, False)}
        fast.reset()
        v = artefatos.construir()
        assert v == artefatos.versao_atual()
        for clinico in (True, False):
            gz, etag, br = artefatos.indice(clinico)
            assert _json(gz) == esperado[clinico]
            assert etag
            import brotli
            assert json.loads(brotli.decompress(br)) == esperado[clinico] and len(br) < len(gz)
        from models.entomologia import EntomologiaAtlasArtefato as A
        assert A.query.filter_by(versao=v, tipo='indice').count() == 2
        assert A.query.filter(A.tipo.like('lugares-%')).count() == artefatos.BALDES


def test_busca_de_reserva_sobre_o_indice_pronto_e_igual_a_do_servidor(app, ligado):
    with app.app_context():
        for clinico in (True, False):
            dados = json.loads(fast.client_index(clinico)[0])
            for consulta in CONSULTAS:
                servidor = [[i['layer_id'], str(i['feature']['id'])] for i in fast.search(consulta, clinico)]
                compacta = [[dados['layers'][e[0]]['id'], e[1]] for e in fast.search_compact(dados['entries'], consulta)]
                assert compacta == servidor, (consulta, clinico)


def test_com_indice_pronto_a_requisicao_nao_monta_nada(client, app, ligado, monkeypatch):
    login(client)
    with app.app_context():
        artefatos.construir()
    monkeypatch.setattr(fast, 'snapshot', lambda: pytest.fail('montou o índice durante a requisição'))
    r = client.get(BASE + '/busca/indice', headers={'Accept-Encoding': 'gzip'})
    assert r.status_code == 200 and r.headers['Content-Encoding'] == 'gzip'
    assert 'Accept-Encoding' in r.headers['Vary']
    assert set(_json(r.data)) == {'layers', 'entries'}
    assert r.headers['Cache-Control'] == 'private, no-store'      # admin: acesso clínico, nada guardado
    import brotli
    rb = client.get(BASE + '/busca/indice', headers={'Accept-Encoding': 'gzip, deflate, br'})
    assert rb.headers['Content-Encoding'] == 'br' and set(json.loads(brotli.decompress(rb.data))) == {'layers', 'entries'}
    # Navegador sem compressão recebe o JSON aberto.
    aberto = client.get(BASE + '/busca/indice')
    assert aberto.headers.get('Content-Encoding') is None and set(aberto.json) == {'layers', 'entries'}
    # Busca de reserva e geometria de rua também saem do que foi gravado.
    achados = client.get(BASE + '/busca', query_string={'q': 'rua quinze', 'compacto': '1'}).json
    assert set(achados) == {'layers', 'entries'} and achados['entries']
    rua = next(e for e in aberto.json['entries'] if e[5] == 2)
    camada = aberto.json['layers'][rua[0]]['id']
    lugar = client.get(BASE + '/busca/lugar', query_string={'layer': camada, 'feature': rua[1]})
    assert lugar.status_code == 200 and lugar.json['feature']['geometry']


def test_geometria_pronta_e_a_mesma_do_caminho_completo_e_respeita_a_regra_clinica(app, ligado):
    with app.app_context():
        snap = fast.snapshot()
        esperado = fast.places(snap)
        assert esperado, 'os dados sintéticos têm ruas/áreas'
        artefatos.construir()
        for (camada, feicao), item in esperado.items():
            if item['clinical']:
                assert artefatos.lugar(camada, feicao, False) is False
                assert artefatos.lugar(camada, feicao, True) == item['item']
            else:
                assert artefatos.lugar(camada, feicao, False) == item['item']
                assert artefatos.lugar(camada, feicao, False) == fast.place(camada, feicao, False)
        assert artefatos.lugar('nao-existe', '1', True) is None       # o caminho completo responde (404)


def test_dado_novo_serve_a_versao_anterior_enquanto_a_nova_e_montada(app, ligado):
    with app.app_context():
        artefatos.construir()
        antigo, etag_antiga, _ = artefatos.indice(True)
        ligado['assinatura'] = ((1, 'a'), (2, 'b'))                  # uma importação nova
        servido, etag, _ = artefatos.indice(True, app)
        assert etag == etag_antiga                                   # responde já, com a anterior
        artefatos.atualizar_em_segundo_plano(app)                    # (já em andamento: não duplica)
        for _ in range(100):
            if artefatos.existe(artefatos.versao_atual()):
                break
            import time
            time.sleep(0.05)
        novo, etag_nova, _ = artefatos.indice(True)
        assert etag_nova != etag_antiga


def test_guarda_so_a_versao_atual_e_a_anterior(app, ligado):
    from models.entomologia import EntomologiaAtlasArtefato as A
    with app.app_context():
        versoes = []
        for n in range(3):
            ligado['assinatura'] = ((n, 'x'),)
            versoes.append(artefatos.construir())
        guardadas = {row.versao for row in A.query.with_entities(A.versao).distinct()}
        assert guardadas == set(versoes[1:])


def test_sem_banco_cai_no_caminho_direto(client, app, ligado, monkeypatch):
    login(client)
    monkeypatch.setattr(fast, '_signature', lambda: None)
    with app.app_context():
        assert artefatos.indice(True) is None and artefatos.construir() is None
    r = client.get(BASE + '/busca/indice')
    assert r.status_code == 200 and r.json['entries']


def test_desligado_fora_do_heroku(app, monkeypatch):
    monkeypatch.delenv('DYNO', raising=False)
    monkeypatch.delenv('ATLAS_ARTEFATOS', raising=False)
    app.config.pop('ATLAS_ARTEFATOS', None)
    with app.app_context():
        assert artefatos.ativo() is False
        assert artefatos.versao_atual() is None
    monkeypatch.setenv('DYNO', 'web.1')
    with app.app_context():
        assert artefatos.ativo() is True


def test_editar_o_atlas_ja_dispara_a_montagem_nova(client, app, ligado, monkeypatch):
    login(client)
    disparos = []
    monkeypatch.setattr(artefatos, 'atualizar_em_segundo_plano', lambda a: disparos.append(a))
    layer = client.post(BASE + '/editor', json=dict(action='create_layer', revision=0, reason='teste',
                                                     title='Equipamentos', color='#087f81'))
    assert layer.status_code == 200 and disparos
    with app.app_context():
        artefatos.construir()
    disparos.clear()
    client.get(BASE + '/busca/indice')                               # versão pronta: a leitura não dispara nada
    assert not disparos


def test_versao_muda_com_os_arquivos_de_dados_e_o_formato(app, ligado, monkeypatch):
    with app.app_context():
        base = artefatos.versao(((1, 'a'),))
        monkeypatch.setattr(artefatos, 'fingerprint_estatico', lambda: 'outro')
        assert artefatos.versao(((1, 'a'),)) != base
        monkeypatch.setattr(fast, 'INDEX_FORMAT', 'formato-novo')
        assert artefatos.versao(((1, 'a'),)) != base
        outra = artefatos.versao(((1, 'a'),))
        monkeypatch.setattr(artefatos, 'ARTEFATOS_FORMATO', 'mapa-seguinte')  # saídas novas: monta tudo de novo
        assert artefatos.versao(((1, 'a'),)) != outra


def test_saidas_novas_remontam_mas_o_indice_anterior_segue_para_quem_ve_tudo(app, ligado, monkeypatch):
    with app.app_context():
        artefatos.construir()
        monkeypatch.setattr(artefatos, 'ARTEFATOS_FORMATO', 'mapa-proximo')   # deploy que acrescenta saídas
        monkeypatch.setattr(artefatos, 'atualizar_em_segundo_plano', lambda a: None)
        assert artefatos.indice(True, app) not in (None, artefatos.PREPARANDO)   # mesmo formato de índice
        assert artefatos.indice(False, app) == artefatos.PREPARANDO
        assert artefatos.catalogo() is None                                      # mapa: caminho direto, fresco


# --------------------------------------------------------------------------
# Nenhuma requisição espera a montagem, e nada que virou clínico vaza
# --------------------------------------------------------------------------

def _esperar_versao_atual():
    import time
    for _ in range(200):
        if artefatos.existe(artefatos.versao_atual()):
            return True
        time.sleep(0.05)
    return False


def test_sem_acesso_clinico_nunca_recebe_a_versao_anterior(client, app, ligado):
    with app.app_context():
        artefatos.construir()
        ligado['assinatura'] = ((1, 'a'), (3, 'camada virou clínica'))
        assert artefatos.indice(False, app) == artefatos.PREPARANDO      # não serve a anterior
        assert artefatos.indice(True, app) not in (None, artefatos.PREPARANDO)   # quem vê tudo, sim
        assert artefatos.busca_compacta('rua', False, app) == {'layers': [], 'entries': [], 'preparando': True}
        snap = fast.snapshot()
        (camada, feicao), _ = next(iter(fast.places(snap).items()))
        assert artefatos.lugar(camada, feicao, False) == artefatos.PREPARANDO
        assert _esperar_versao_atual()                                   # a montagem já tinha começado
        assert artefatos.indice(False) not in (None, artefatos.PREPARANDO)


def test_indice_em_preparo_responde_na_hora_com_503(client, app, ligado, monkeypatch):
    login(client)
    monkeypatch.setattr(artefatos, 'atualizar_em_segundo_plano', lambda a: None)   # montagem "em andamento"
    monkeypatch.setattr(artefatos, 'indice', lambda clinico, app=None: artefatos.PREPARANDO)
    r = client.get(BASE + '/busca/indice')
    assert r.status_code == 503 and r.headers['Retry-After'] == '5' and r.json['preparando'] is True
    assert 'no-store' in r.headers['Cache-Control']
    reserva = client.get(BASE + '/busca', query_string={'q': 'rua', 'compacto': '1'})
    assert reserva.status_code == 200


def test_primeira_vez_nao_prende_a_requisicao(app, ligado):
    with app.app_context():
        assert artefatos.indice(True, app) == artefatos.PREPARANDO      # nada gravado: monta em segundo plano
        assert _esperar_versao_atual()
        assert artefatos.indice(True) not in (None, artefatos.PREPARANDO)


def test_versao_anterior_de_outro_formato_nao_e_servida(app, ligado, monkeypatch):
    with app.app_context():
        artefatos.construir()
        monkeypatch.setattr(fast, 'INDEX_FORMAT', 'formato-novo')        # deploy que mudou o índice
        monkeypatch.setattr(artefatos, 'atualizar_em_segundo_plano', lambda a: None)
        assert artefatos.indice(True, app) == artefatos.PREPARANDO


def test_montagem_com_erro_volta_ao_caminho_direto(client, app, ligado, monkeypatch):
    login(client)
    with app.app_context():
        monkeypatch.setattr(artefatos, 'construir', lambda **k: (_ for _ in ()).throw(RuntimeError('falhou')))
        artefatos._building[0] = False
        thread = artefatos.atualizar_em_segundo_plano(app)
        thread.join(5)
        assert artefatos.indice(True, app) is None                       # sem "preparando" eterno
    r = client.get(BASE + '/busca/indice')
    assert r.status_code == 200 and r.json['entries']
    artefatos._falhou_em[0] = 0.0

# Catálogo, endereços e camadas prontos (o mapa abre sem remontar as camadas)
# --------------------------------------------------------------------------

def _com_cores(monkeypatch):
    layers = _synthetic_layers()
    for layer in layers.values():
        layer.setdefault('color', '#087f81')
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in json.loads(json.dumps(layers)).items() if allowed or not v['clinical']})


def _respostas(client, https=None):
    https = https or {}
    return {
        'catalogo': client.get('/sfa/entomologia/atlas/camadas', **https),
        'enderecos': client.get(BASE + '/enderecos', **https),
        'ref': client.get('/sfa/entomologia/atlas/camadas/ref', **https),
        'cad': client.get('/sfa/entomologia/atlas/camadas/cad', **https),
        'clin': client.get('/sfa/entomologia/atlas/camadas/clin', **https),
    }


def _comparar(antes, depois):
    for nome in antes:
        assert depois[nome].status_code == antes[nome].status_code, nome
        assert depois[nome].headers.get('Cache-Control') == antes[nome].headers.get('Cache-Control'), nome
        if antes[nome].status_code == 200:
            assert depois[nome].json == antes[nome].json, nome


def test_mapa_pronto_responde_igual_ao_montado_na_hora(client, app, ligado, monkeypatch):
    _com_cores(monkeypatch)
    login(client)
    app.config['ATLAS_ARTEFATOS'] = False
    antes = _respostas(client)
    assert antes['clin'].status_code == 200 and antes['enderecos'].json['layers']
    app.config['ATLAS_ARTEFATOS'] = True
    with app.app_context():
        artefatos.construir()
    monkeypatch.setattr(editor, 'layers', lambda *a, **k: pytest.fail('remontou as camadas na requisição'))
    depois = _respostas(client)
    _comparar(antes, depois)
    comprimida = client.get('/sfa/entomologia/atlas/camadas/ref', headers={'Accept-Encoding': 'br, gzip'})
    assert comprimida.headers['Content-Encoding'] == 'br'


def test_mapa_pronto_mantem_a_regra_clinica_para_quem_nao_tem_acesso(client, app, ligado, monkeypatch):
    from extensions import db
    from models.entomologia import EntomologiaEquipe
    _com_cores(monkeypatch)
    member = login(client, 'tutor')
    db.session.add(EntomologiaEquipe(user_id=member.id, concedido_por='admin'))
    db.session.commit()
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    https = {'base_url': 'https://localhost'}
    app.config['ATLAS_ARTEFATOS'] = False
    antes = _respostas(client, https)
    app.config['ATLAS_ARTEFATOS'] = True
    with app.app_context():
        artefatos.construir()
    depois = _respostas(client, https)
    _comparar(antes, depois)
    assert depois['clin'].status_code == 404
    restrita = next(i for i in depois['catalogo'].json['layers'] if i['id'] == 'clin')
    assert restrita['allowed'] is False and 'features' not in restrita


def test_mapa_logo_depois_de_editar_vem_fresco_e_nao_da_versao_anterior(client, app, ligado, monkeypatch):
    _com_cores(monkeypatch)
    login(client)
    with app.app_context():
        artefatos.construir()
        ligado['assinatura'] = ((9, 'nova'),)            # alguém acabou de salvar
        assert artefatos.catalogo() is None and artefatos.enderecos(True) is None and artefatos.camada('ref') is None
    chamadas = []
    original = editor.layers
    monkeypatch.setattr(editor, 'layers', lambda *a, **k: chamadas.append(1) or original(*a, **k))
    assert client.get('/sfa/entomologia/atlas/camadas').status_code == 200 and chamadas


def test_camada_de_enderecos_marcada_como_clinica_chega_so_a_quem_tem_acesso(app, ligado, monkeypatch):
    layers = _synthetic_layers()
    for layer in layers.values():
        layer.setdefault('color', '#087f81')
    layers['many']['clinical'] = True                    # administrador marcou os endereços como clínicos
    monkeypatch.setattr(editor, 'layers', lambda allowed, include_deleted=False: {
        k: v for k, v in json.loads(json.dumps(layers)).items() if allowed or not v['clinical']})
    with app.app_context():
        artefatos.construir()
        com = json.loads(artefatos.descomprimir(artefatos.enderecos(True)[0]))
        sem = json.loads(artefatos.descomprimir(artefatos.enderecos(False)[0]))
    assert [l['id'] for l in com['layers']] == ['many'] and com['layers'][0]['features']
    assert sem['layers'] == []


def test_montagem_nao_acumula_textos_na_memoria(app, ligado, monkeypatch):
    """Grava uma saída por vez e não deixa os índices (5 MB cada em produção) no cache do processo."""
    vistos = []
    original = artefatos._gravar

    def gravar(v, linhas, qualidade=9):
        assert not isinstance(linhas, list)              # gerador consumido aos poucos
        return original(v, (vistos.append(t) or (var, t, c) for var, t, c in linhas), qualidade)
    monkeypatch.setattr(artefatos, '_gravar', gravar)
    with app.app_context():
        artefatos.construir(liberar_memoria=False)
        assert fast._payloads == {}
    assert 'indice' in vistos and 'catalogo' in vistos and any(t.startswith('lugares-') for t in vistos)
