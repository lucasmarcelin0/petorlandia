"""Papel adicional "Combate à dengue": acesso só à área de território."""
import io
import json

import pytest
from bs4 import BeautifulSoup
from flask import g

from extensions import db
from models import User
from models.entomologia import EntomologiaEquipe, EntomologiaImportacao
from models.sfa import SfaAcao, SfaAuditoria, SfaPaciente
from services.entomologia_acesso import conceder, membro_equipe
from tests.test_entomologia_atualizacao import visitas_csv

HTTPS = {'base_url': 'https://localhost'}


def conta(role='tutor', email='equipe@example.test', worker=None):
    user = User(name='Pessoa da Equipe', email=email, password_hash='x', role=role, worker=worker)
    db.session.add(user)
    db.session.commit()
    return user


def entrar(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    # O contexto do app de teste é compartilhado entre requisições.
    for chave in ('_login_user', '_entomologia_membro', 'user_experience'):
        g.pop(chave, None)


@pytest.fixture()
def restrito(app, monkeypatch):
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    return app


@pytest.fixture()
def membro(app, client, restrito):
    # Vacinador de campanha que também entra na equipe: o role não muda.
    user = conta(role='vacinador')
    conceder(user, 'Coordenação')
    db.session.commit()
    entrar(client, user)
    return user


def test_membro_acessa_so_a_area_de_territorio(client, membro):
    painel = client.get('/sfa/entomologia', **HTTPS)
    assert painel.status_code == 200
    html = painel.get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    sidebar = soup.select_one('.sfa-sidebar').get_text(' ')
    assert 'Dados entomológicos' in sidebar and 'Atualizar dados' in sidebar
    assert 'Pacientes' not in sidebar and 'Sync SINAN' not in sidebar
    assert client.get('/sfa/entomologia/atualizar', **HTTPS).status_code == 200
    assert client.get('/sfa/entomologia/mapas/mapa-01.jpg', **HTTPS).status_code == 200
    for rota in ('/sfa/', '/sfa/pacientes', '/sfa/trabalho', '/sfa/vigilancia-semanal'):
        assert client.get(rota, **HTTPS).status_code in (403, 404), rota
    assert db.session.get(User, membro.id).role == 'vacinador'


def test_membro_envia_dados_e_nao_gerencia_equipe(client, membro):
    resposta = client.post('/sfa/entomologia/atualizar', data={
        'tipo': 'visitas', 'responsavel': 'Agente', 'arquivo': (io.BytesIO(visitas_csv([
            ('2026-09-12', '353430205000001', '7', '0')])), 'v.csv')},
        content_type='multipart/form-data', **HTTPS)
    assert resposta.status_code == 302
    envio = EntomologiaImportacao.query.one()
    assert client.post(f'/sfa/entomologia/envios/{envio.id}/confirmar',
                       data={'responsavel': 'Agente'}, **HTTPS).status_code == 302
    assert db.session.get(EntomologiaImportacao, envio.id).status == 'ATIVA'
    outro = conta(email='outra@example.test')
    negado = client.post('/sfa/entomologia/equipe', data={'email': outro.email, 'responsavel': 'x'}, **HTTPS)
    assert negado.status_code in (403, 404)
    assert EntomologiaEquipe.query.filter_by(user_id=outro.id).count() == 0


def test_membro_cria_e_conclui_acao_territorial_sem_tocar_acoes_de_pacientes(client, membro):
    criada = client.post('/sfa/entomologia/acoes', data={
        'setor': '353430205000017', 'tipo': 'Verificar foco registrado', 'motivo': 'Três achados no setor.',
        'prazo': '2099-01-01', 'responsavel': 'Agente',
        # Campos de vínculo com pacientes são ignorados nesta rota.
        'id_estudo': 'SFA-X', 'evento_id': '1'}, **HTTPS)
    assert criada.status_code == 302 and criada.headers['Location'].endswith('/sfa/entomologia#acao-criada')
    acao = SfaAcao.query.one()
    assert (acao.id_estudo, acao.evento_id, acao.status) == (None, None, 'ABERTA')
    url = f'/sfa/entomologia/acoes/{acao.id}/andamento'
    client.post(url, data={'status': 'EXECUTADA', 'resultado': 'Criadouros removidos', 'responsavel': 'Agente'}, **HTTPS)
    client.post(url, data={'status': 'VERIFICADA', 'resultado': 'Retorno sem larvas',
                           'evidencia_verificacao': 'Vistoria em 3 imóveis', 'responsavel': 'Supervisão'}, **HTTPS)
    assert db.session.get(SfaAcao, acao.id).status == 'VERIFICADA'
    assert SfaAuditoria.query.filter_by(categoria='FLUXO_TRABALHO').count() == 3

    db.session.add(SfaPaciente(id_estudo='SFA-900', nome='Participante', grupo='A'))
    db.session.flush()
    pessoal = SfaAcao(id_estudo='SFA-900', setor='353430205000017', tipo='Busca ativa', motivo='Paciente',
                      responsavel='Equipe SFA', prazo=acao.prazo, status='ABERTA')
    db.session.add(pessoal)
    db.session.commit()
    assert client.post(f'/sfa/entomologia/acoes/{pessoal.id}/andamento', data={
        'status': 'EXECUTADA', 'resultado': 'x', 'responsavel': 'x'}, **HTTPS).status_code in (403, 404)
    assert db.session.get(SfaAcao, pessoal.id).status == 'ABERTA'
    html = client.get('/sfa/entomologia', **HTTPS).get_data(as_text=True)
    dataset = json.loads(html.split('id="ento-dataset">', 1)[1].split('</script>', 1)[0])
    assert [a['id'] for a in dataset['actions']] == [acao.id]
    assert 'Paciente' not in json.dumps(dataset['actions'])


def test_sem_papel_nao_entra_e_nao_ve_a_area(client, restrito):
    tutor = conta()
    entrar(client, tutor)
    assert client.get('/sfa/entomologia', **HTTPS).status_code in (403, 404)
    assert client.post('/sfa/entomologia/acoes', data={'setor': '1'}, **HTTPS).status_code in (403, 404)
    home = BeautifulSoup(client.get('/', **HTTPS).data, 'html.parser')
    assert not home.select('[data-dashboard-area="dengue"]')


def test_pagina_inicial_mostra_combate_a_dengue_sem_perder_outras_areas(client, membro):
    home = BeautifulSoup(client.get('/', **HTTPS).data, 'html.parser')
    areas = [a['data-dashboard-area'] for a in home.select('[data-dashboard-area]')]
    assert 'vaccinator' in areas and 'dengue' in areas
    links = [a['href'] for a in home.select('[data-dashboard-area="dengue"] a')]
    assert any(h.endswith('/sfa/entomologia') for h in links)
    assert any(h.endswith('/aedes') for h in links)


def test_admin_concede_e_revoga_pela_tela(client, restrito):
    admin = conta(role='admin', email='admin-dengue@example.test')
    pessoa = conta(email='CVteste@Example.test')
    entrar(client, admin)
    pagina = client.get('/sfa/entomologia/atualizar', **HTTPS).get_data(as_text=True)
    assert 'Equipe “Combate à dengue”' in pagina
    home = BeautifulSoup(client.get('/', **HTTPS).data, 'html.parser')
    assert home.select('[data-dashboard-area="dengue"]')

    client.post('/sfa/entomologia/equipe', data={'email': ' cvteste@example.TEST ', 'responsavel': 'Admin'}, **HTTPS)
    client.post('/sfa/entomologia/equipe', data={'email': 'cvteste@example.test', 'responsavel': 'Admin'}, **HTTPS)
    assert EntomologiaEquipe.query.filter_by(user_id=pessoa.id, revogado_em=None).count() == 1
    assert membro_equipe(pessoa)
    assert SfaAuditoria.query.filter_by(funcao='conceder_papel').count() == 1
    client.post('/sfa/entomologia/equipe', data={'email': 'ninguem@example.test', 'responsavel': 'Admin'}, **HTTPS)
    assert EntomologiaEquipe.query.count() == 1

    client.post(f'/sfa/entomologia/equipe/{pessoa.id}/revogar', data={'responsavel': 'Admin'}, **HTTPS)
    g.pop('_entomologia_membro', None)
    assert not membro_equipe(pessoa)
    assert db.session.get(User, pessoa.id).role == 'tutor'
    entrar(client, pessoa)
    assert client.get('/sfa/entomologia', **HTTPS).status_code in (403, 404)


def test_comando_de_linha_concede_lista_e_revoga_sem_imprimir_email(app):
    pessoa = conta(email='cvlinha@example.test')
    runner = app.test_cli_runner()
    saida = runner.invoke(args=['entomologia-equipe', 'conceder', 'CVLINHA@example.test', '--por', 'Deploy'])
    assert saida.exit_code == 0, saida.output
    assert f'conta #{pessoa.id}' in saida.output and 'cvlinha@' not in saida.output
    assert membro_equipe(pessoa)
    listagem = runner.invoke(args=['entomologia-equipe', 'listar'])
    assert '1 conta(s)' in listagem.output and 'cv***@example.test' in listagem.output
    assert runner.invoke(args=['entomologia-equipe', 'conceder', 'nao@existe.test']).exit_code != 0
    runner.invoke(args=['entomologia-equipe', 'revogar', 'cvlinha@example.test'])
    g.pop('_entomologia_membro', None)
    assert not membro_equipe(pessoa)
    assert SfaAuditoria.query.filter_by(categoria='ENTOMOLOGIA').count() == 2


def test_team_reads_operational_atlas_but_not_clinical_sources(client, membro, monkeypatch):
    from services import entomologia_atlas as atlas
    point={'type':'Point','coordinates':[-47.88,-20.72]}
    earth={'type':'FeatureCollection','source':{'title':'Atlas'},'features':[
        {'type':'Feature','geometry':point,'properties':{'layer':'Rotina','category':'IE','month':'01'}},
        {'type':'Feature','geometry':point,'properties':{'layer':'Casos Dengue','category':'Positivo','sinan':'123'}}]}
    monkeypatch.setattr(atlas,'active_earth',lambda:earth)
    monkeypatch.setattr(atlas,'live_sheet',lambda *args,**kwargs:pytest.fail('Team must not consult the clinical sheet'))
    catalog=client.get('/sfa/entomologia/atlas/camadas',**HTTPS)
    assert catalog.status_code==200
    clinical=next(layer for layer in catalog.json['layers'] if layer['title']=='Casos Dengue')
    assert clinical['allowed'] is False and clinical['count'] is None
    assert client.get('/sfa/entomologia/atlas/camadas/'+atlas.layer_id('Rotina'),**HTTPS).status_code==200
    assert client.get('/sfa/entomologia/atlas/camadas/'+atlas.layer_id('Casos Dengue'),**HTTPS).status_code in (401,403,404)
    assert client.get('/sfa/entomologia/atlas/sinan',**HTTPS).status_code in (401,403,404)
