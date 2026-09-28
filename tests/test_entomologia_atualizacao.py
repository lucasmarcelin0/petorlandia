"""Atualização da base entomológica pela equipe, camadas KML e boletim público."""
import csv
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from flask import g

from extensions import db
from models import User
from models.entomologia import EntomologiaImportacao, EntomologiaPublicacao
from models.sfa import SfaAcao, SfaAuditoria
from scripts.import_entomologia import METRICS
from services import entomologia_service as service

ROOT = Path(__file__).resolve().parents[1]
BASE_ROWS = 2371


def login(client, role='admin'):
    user = User(name='Coordenação', email=f'{role}-ento@test', password_hash='x', role=role)
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    g.pop('_login_user', None)  # o contexto do app de teste é compartilhado entre requisições
    return user


@pytest.fixture()
def admin(app, client):
    return login(client)


def visitas_csv(linhas, encoding='cp1252'):
    headers = ['LOGIN', 'AGENTE', 'DATA', 'AREA', 'CENSITARIO', 'QUARTEIRÃO', *METRICS.values()]
    stream = io.StringIO()
    stream.write('Visita a Imóvel\nExportação do sistema\n\n')
    writer = csv.DictWriter(stream, fieldnames=headers, delimiter=';')
    writer.writeheader()
    for dia, setor, quarteirao, larva in linhas:
        row = dict.fromkeys(headers, '')
        row.update({'LOGIN': 'login.privado', 'AGENTE': 'Nome Privado', 'DATA': dia, 'AREA': '1',
                    'CENSITARIO': setor, 'QUARTEIRÃO': quarteirao, 'IM TRAB': '4', 'IM FECH': '1',
                    'IM MECANICO': '1', 'IM. LARVA': larva})
        writer.writerow(row)
    return stream.getvalue().encode(encoding)


def enviar(client, blob, nome, tipo='visitas', **extra):
    return client.post('/sfa/entomologia/atualizar', data={
        'tipo': tipo, 'responsavel': 'Equipe de campo', 'arquivo': (io.BytesIO(blob), nome), **extra,
    }, content_type='multipart/form-data')


def confirmar_ultimo(client):
    envio = EntomologiaImportacao.query.order_by(EntomologiaImportacao.id.desc()).first()
    response = client.post(f'/sfa/entomologia/envios/{envio.id}/confirmar', data={'responsavel': 'Coordenação'})
    assert response.status_code == 302
    return envio


def test_consolidacao_substitui_somente_os_dias_enviados():
    base = [{'date': '2026-01-01', 'sector': 'A', 'block': '1', 'v': 1},
            {'date': '2026-01-02', 'sector': 'A', 'block': '1', 'v': 2},
            {'date': '2026-01-02', 'sector': 'B', 'block': '1', 'v': 3}]
    primeiro = [{'date': '2026-01-02', 'sector': 'C', 'block': '9', 'v': 4},
                {'date': '2026-01-03', 'sector': 'A', 'block': '1', 'v': 5}]
    segundo = [{'date': '2026-01-03', 'sector': 'Z', 'block': '1', 'v': 6}]
    result = service.consolidar_visitas(base, [primeiro, segundo])
    assert [r['v'] for r in result] == [1, 4, 6]
    assert service.consolidar_visitas(base, []) == base


def test_envio_passa_por_previa_confirmacao_e_desfazer(app, client, admin):
    blob = visitas_csv([('2026-09-08', '353430205000017', '901', '1'),
                        ('2026-09-10', '353430205000017', '902', ''),
                        ('2026-09-10', '353430205000045', '903', '0')])
    response = enviar(client, blob, 'Visita a Imóvel.csv')
    assert response.status_code == 302 and 'previa=' in response.headers['Location']
    envio = EntomologiaImportacao.query.one()
    assert envio.status == 'PREVIA'
    assert 'login.privado' not in envio.dados_json and 'Nome Privado' not in envio.dados_json
    resumo = json.loads(envio.resumo_json)
    assert (resumo['dias_novos'], resumo['dias_substituidos'], resumo['linhas']) == (1, 1, 3)
    assert any('menos registros' in aviso for aviso in resumo['avisos'])
    # A prévia não altera a base usada pelos painéis.
    assert len(service.dataset_atual()['records']) == BASE_ROWS

    page = client.get(envio_url := f'/sfa/entomologia/atualizar?previa={envio.id}')
    assert page.status_code == 200 and 'PRÉVIA — AINDA NÃO APLICADA' in page.get_data(as_text=True), envio_url

    base_08 = sum(r['date'] == '2026-09-08' for r in service.load_entomologia()['records'])
    confirmar_ultimo(client)
    atual = service.dataset_atual()
    assert len(atual['records']) == BASE_ROWS - base_08 + 3
    assert atual['source']['end'] == '2026-09-10'
    assert atual['source']['imported_at']
    assert [u['id'] for u in atual['updates']] == [envio.id]
    assert sum(r['date'] == '2026-09-08' for r in atual['records']) == 1
    assert '353430205000017' in service.setores_operacionais()
    assert SfaAuditoria.query.filter_by(categoria='ENTOMOLOGIA', funcao='confirmar_envio').count() == 1

    # Reenviar o mesmo conteúdo não duplica nada.
    enviar(client, blob, 'Visita a Imóvel.csv')
    assert EntomologiaImportacao.query.count() == 1

    response = client.post(f'/sfa/entomologia/envios/{envio.id}/desfazer', data={'responsavel': 'Coordenação'})
    assert response.status_code == 302
    assert db.session.get(EntomologiaImportacao, envio.id).status == 'DESFEITA'
    assert len(service.dataset_atual()['records']) == BASE_ROWS
    assert service.dataset_atual()['source'] == service.load_entomologia()['source']


def test_zip_utf8_e_arquivo_invalido(app, client, admin):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('Dados/Leia-me.csv', 'nada')
        archive.writestr('Dados/Visita a Imóvel.csv', visitas_csv([('2026-09-12', '353430205000001', '1', '0')], 'utf-8'))
    enviar(client, buffer.getvalue(), 'Dados.zip')
    envio = EntomologiaImportacao.query.one()
    assert envio.titulo == 'Visita a Imóvel.csv' and envio.linhas == 1

    response = enviar(client, b'sem cabecalho\n1;2;3\n', 'errado.csv')
    assert response.status_code == 302
    with client.session_transaction() as session:
        mensagens = [m for _, m in session.get('_flashes', [])]
    assert any('LOGIN' in m for m in mensagens)
    outro_municipio = visitas_csv([('2026-09-12', '353530205000001', '1', '0')])
    enviar(client, outro_municipio, 'outro.csv')
    assert EntomologiaImportacao.query.count() == 1


KML = b'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Projeto Earth</name>
<Folder><name>Pontos estrat\xc3\xa9gicos</name>
<Placemark><name>Borracharia</name><description><![CDATA[<b>Vistoria</b> &amp; orienta\xc3\xa7\xc3\xa3o<script>x</script>]]></description>
<Point><coordinates>-47.887,-20.719,0</coordinates></Point></Placemark>
<Placemark><name>Rota</name><LineString><coordinates>-47.89,-20.71 -47.88,-20.72</coordinates></LineString></Placemark>
<Placemark><name>Quarteir\xc3\xa3o</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
-47.89,-20.71 -47.88,-20.71 -47.88,-20.72 -47.89,-20.71</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Sem geometria</name></Placemark>
</Folder></Document></kml>'''


def test_camada_kml_kmz_e_xml_perigoso():
    camada = service.ler_camada(KML, 'projeto.kml')
    features = camada['geojson']['features']
    assert camada['titulo'] == 'Projeto Earth'
    assert [f['geometry']['type'] for f in features] == ['Point', 'LineString', 'Polygon']
    assert features[0]['properties'] == {'name': 'Borracharia', 'description': 'Vistoria & orientação x',
                                         'folder': 'Pontos estratégicos'}
    assert features[0]['geometry']['coordinates'] == [-47.887, -20.719]

    kmz = io.BytesIO()
    with zipfile.ZipFile(kmz, 'w') as archive:
        archive.writestr('doc.kml', KML)
    assert len(service.ler_camada(kmz.getvalue(), 'projeto.kmz')['geojson']['features']) == 3

    bomba = b'<?xml version="1.0"?><!DOCTYPE k [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><kml>&b;</kml>'
    with pytest.raises(ValueError):
        service.ler_camada(bomba, 'x.kml')
    with pytest.raises(ValueError):
        service.ler_camada(KML.replace(b'-47.887,-20.719', b'-247.887,-20.719'), 'x.kml')
    with pytest.raises(ValueError):
        service.ler_camada(b'<kml><Document/></kml>', 'vazio.kml')
    with pytest.raises(ValueError):
        service.ler_camada(KML, 'projeto.pdf')


def test_camada_confirmada_aparece_so_no_painel_interno(app, client, admin):
    enviar(client, KML, 'projeto.kml', tipo='camada', titulo='Pontos estratégicos 2026')
    confirmar_ultimo(client)
    layers = service.dataset_atual()['layers']
    assert [layer['title'] for layer in layers] == ['Pontos estratégicos 2026']
    html = client.get('/sfa/entomologia').get_data(as_text=True)
    assert 'Pontos estratégicos 2026' in html
    client.post('/sfa/entomologia/publicar', data={'responsavel': 'Coordenação', 'dias': '28'})
    assert 'Borracharia' not in client.get('/aedes').get_data(as_text=True)


def test_boletim_publico_agrega_por_setor_sem_identificadores():
    boletim = service.boletim_publico(service.load_entomologia(), dias=28)
    assert (boletim['inicio'], boletim['fim']) == ('2026-08-12', '2026-09-08')
    assert boletim['totais']['setores'] == 38
    texto = json.dumps(boletim)
    for proibido in ('login', 'agente', 'block', 'quarteirao'):
        assert proibido not in texto.lower()
    assert set(next(iter(boletim['setores'].values()))) == {
        'situacao', 'na_malha', 'quarteiroes', 'trabalhados', 'controle_mecanico', 'ultima_visita'}
    assert boletim['setores']['353430205000017']['situacao'] == 'foco'
    assert boletim['setores']['353430205000018']['situacao'] == 'sem_informacao'
    assert len(boletim['semanas']) == 8 and boletim['semanas'][-1]['parcial'] is True
    with pytest.raises(ValueError):
        service.boletim_publico(service.load_entomologia(), dias=30)


def test_publicacao_substitui_e_retirada_limpa_pagina_publica(app, client, admin):
    vazia = client.get('/aedes')
    assert vazia.status_code == 200
    assert 'ainda não foi publicado' in vazia.get_data(as_text=True)
    assert 'aedes-data' not in vazia.get_data(as_text=True)

    for mensagem in ('Primeiro boletim', 'Receba o agente com o crachá'):
        client.post('/sfa/entomologia/publicar', data={
            'responsavel': 'Coordenação', 'dias': '14', 'mensagem': mensagem,
            'contato': 'Telefone da equipe', 'assinatura': 'Equipe de Controle de Vetores'})
    assert [p.status for p in EntomologiaPublicacao.query.order_by(EntomologiaPublicacao.id)] == ['SUBSTITUIDA', 'PUBLICADA']
    html = client.get('/aedes').get_data(as_text=True)
    assert 'Receba o agente com o crachá' in html and 'Primeiro boletim' not in html
    assert 'Telefone da equipe' in html and 'aedes-data' in html
    assert 'population' not in html  # a malha pública leva só geometria, código e situação

    vigente = EntomologiaPublicacao.query.filter_by(status='PUBLICADA').one()
    client.post(f'/sfa/entomologia/publicacoes/{vigente.id}/retirar', data={'responsavel': 'Coordenação'})
    assert 'ainda não foi publicado' in client.get('/aedes').get_data(as_text=True)
    assert client.get('/sfa/entomologia/boletim/previa').status_code == 200


def test_planejamento_cria_acao_e_volta_ao_painel(app, client):
    response = client.post('/sfa/trabalho/registrar', data={
        'operacao': 'acao', 'responsavel': 'Supervisão', 'setor': '353430205000017',
        'tipo': 'Verificar foco registrado', 'motivo': 'Planejamento: 3 ocorrências com larvas.',
        'prazo': '2099-01-01', 'retorno': 'entomologia', 'id_estudo': ''})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/sfa/entomologia#acao-criada')
    acao = SfaAcao.query.one()
    assert acao.setor == '353430205000017' and acao.status == 'ABERTA'
    html = client.get('/sfa/entomologia').get_data(as_text=True)
    dataset = json.loads(html.split('id="ento-dataset">', 1)[1].split('</script>', 1)[0])
    assert dataset['actions'] == [{'id': acao.id, 'sector': '353430205000017', 'tipo': 'Verificar foco registrado',
                                   'status': 'ABERTA', 'prazo': '2099-01-01', 'criado_em': dataset['actions'][0]['criado_em'],
                                   'executado_em': None, 'verificado_em': None}]
    # Sem retorno explícito, o fluxo antigo continua indo para Organização do trabalho.
    antigo = client.post('/sfa/trabalho/registrar', data={
        'operacao': 'acao', 'responsavel': 'Supervisão', 'setor': '353430205000017',
        'tipo': 'Visita', 'motivo': 'Rotina', 'prazo': '2099-01-01', 'retorno': 'https://externo.example'})
    assert '/sfa/trabalho' in antigo.headers['Location'] and 'externo' not in antigo.headers['Location']


@pytest.mark.parametrize('method,url', [
    ('get', '/sfa/entomologia/atualizar'), ('post', '/sfa/entomologia/atualizar'),
    ('post', '/sfa/entomologia/envios/1/confirmar'), ('post', '/sfa/entomologia/envios/1/desfazer'),
    ('post', '/sfa/entomologia/publicar'), ('post', '/sfa/entomologia/publicacoes/1/retirar'),
    ('get', '/sfa/entomologia/boletim/previa'),
])
def test_rotas_internas_exigem_acesso(app, client, monkeypatch, method, url):
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.setenv('SFA_ADMIN_TOKEN', 'somente-este-token')
    response = getattr(client, method)(url)
    assert response.status_code in (302, 401)
    assert '/login' in response.headers.get('Location', '/login')
    assert client.get('/aedes').status_code == 200


def test_alteracoes_exigem_administrador_identificado(app, client, monkeypatch):
    blob = visitas_csv([('2026-09-12', '353430205000001', '1', '0')])
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.setenv('SFA_ADMIN_TOKEN', 'token-interno')
    token = {'X-SFA-Token': 'token-interno'}
    # O token continua abrindo o painel e a tela de atualização, só para leitura.
    assert client.get('/sfa/entomologia', headers=token).status_code == 200
    pagina = client.get('/sfa/entomologia/atualizar', headers=token)
    assert pagina.status_code == 200 and 'Somente leitura' in pagina.get_data(as_text=True)
    negado = client.post('/sfa/entomologia/atualizar', headers=token, data={
        'tipo': 'visitas', 'responsavel': 'x', 'arquivo': (io.BytesIO(blob), 'v.csv')},
        content_type='multipart/form-data')
    assert negado.status_code == 302 and '/login' in negado.headers['Location']
    assert client.post('/sfa/entomologia/publicar', headers=token, data={'responsavel': 'x'}).status_code == 302
    # Usuário logado sem papel de administrador também não altera nada
    # (403, ou 404 quando o app oculta a negação para clientes que aceitam JSON).
    login(client, role='veterinario')
    assert client.post('/sfa/entomologia/publicar', headers=token, data={'responsavel': 'x'}).status_code in (403, 404)
    assert client.post('/sfa/entomologia/atualizar', headers=token, data={
        'tipo': 'visitas', 'responsavel': 'x', 'arquivo': (io.BytesIO(blob), 'v.csv')},
        content_type='multipart/form-data').status_code in (403, 404)
    assert EntomologiaImportacao.query.count() == 0 and EntomologiaPublicacao.query.count() == 0


def test_sem_banco_o_painel_usa_a_fotografia(monkeypatch):
    monkeypatch.setattr(service, '_chave_ativas', lambda: None)
    atual = service.dataset_atual()
    assert atual['records'] is service.load_entomologia()['records']
    assert atual['layers'] == [] and atual['updates'] == []


@pytest.mark.parametrize('script', ['test_entomologia_model.js', 'test_entomologia_team_model.js'])
def test_modelos_javascript(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js não está disponível')
    result = subprocess.run([node, str(ROOT / 'tests' / script)], cwd=ROOT, capture_output=True,
                            text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
