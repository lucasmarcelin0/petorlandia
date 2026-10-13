"""Casa a casa: base em branco, plano do dia, visitas do boletim oficial e acesso."""
from datetime import timedelta

import pytest
from flask import g

from extensions import db
from models import User
from models.entomologia import EntomologiaQuarteiraoTrabalho as Plano, EntomologiaVisitaDomiciliar as Visita
from models.sfa import SfaAuditoria
from services import entomologia_casa_a_casa as servico
from services.entomologia_acesso import conceder
from services.sfa_workflow import hoje_local

HTTPS = {'base_url': 'https://localhost'}
RAIZ = '/sfa/entomologia/casa-a-casa'


def conta(email, role='tutor', name='Agente de Campo'):
    user = User(name=name, email=email, password_hash='x', role=role)
    db.session.add(user)
    db.session.commit()
    return user


def entrar(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    for chave in ('_login_user', '_entomologia_membro', '_sfa_unidades_usuario', 'user_experience'):
        g.pop(chave, None)


def agente(email='agente@example.test', name='Ana Agente'):
    user = conta(email, name=name)
    conceder(user, 'Coordenação')
    db.session.commit()
    return user


def endereco(identificador, x, y, rua, numero, extra=''):
    # Como no atlas: o id do endereço leva um resumo da linha, então dois usos do mesmo código têm ids distintos.
    sufixo = 'abc' if not extra else extra.strip(' ·').lower()[:6]
    return {'type': 'Feature', 'id': 'cnefe-' + identificador + '-' + sufixo, 'geometry': {'type': 'Point', 'coordinates': [x, y]},
            'properties': {'house_number': numero, 'street': rua, 'cnefe_id': identificador,
                           'address': f'{rua}, {numero}{extra} · Centro'}}


@pytest.fixture()
def base(app, monkeypatch):
    """Dois quarteirões reais da malha, com imóveis fictícios dentro do primeiro."""
    from services.entomologia_service import load_field_territory
    primeiro, segundo = load_field_territory()['features'][:2]
    cx, cy = primeiro['properties']['label']
    casas = [endereco('1001', cx + 0.00002, cy + 0.00003, 'Rua Um', '10'),
             endereco('1002', cx - 0.00003, cy + 0.00001, 'Rua Um', '12'),
             endereco('1003', cx + 0.00001, cy - 0.00003, 'Rua Dois', '5', ' · Fundos'),
             endereco('1003', cx + 0.00001, cy - 0.00003, 'Rua Dois', '5', ' · Frente'),   # mesmo código, dois imóveis
             endereco('1004', cx, cy, 'Rua Dois', ''),                                      # sem número: fica de fora
             endereco('1005', -40.0, -10.0, 'Rua Longe', '1')]                              # fora da malha
    monkeypatch.setattr(servico, '_enderecos', lambda: casas)
    monkeypatch.setattr(servico, '_assinatura', lambda: 'teste')
    servico.esquecer_base()
    yield {'a': primeiro['properties']['source_id'], 'b': segundo['properties']['source_id']}
    servico.esquecer_base()


@pytest.fixture()
def restrito(app, monkeypatch):
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    return app


def visita(bloco, imovel='1001', situacao='TRABALHADO', uuid='visita-0001', **extra):
    return {'uuid': uuid, 'bloco': bloco, 'imovel': imovel, 'situacao': situacao, 'logradouro': 'Rua Um', 'numero': '10', **extra}


def enviar(client, *visitas):
    return client.post(RAIZ + '/visitas', json={'visitas': list(visitas)}, **HTTPS)


def planejar(client, acao, blocos, **extra):
    return client.post(RAIZ + '/plano', json={'acao': acao, 'blocos': blocos, **extra}, **HTTPS)


# ---------------------------------------------------------------------------
# Base em branco
# ---------------------------------------------------------------------------

def test_base_tem_quarteiroes_e_imoveis_no_quarteirao_certo(base):
    dados = servico.base()
    assert len(dados['blocos']) > 900 and {'id', 'n', 's', 'c', 'g'} <= set(dados['blocos'][0])
    posicao = next(i for i, bloco in enumerate(dados['blocos']) if bloco['id'] == base['a'])
    casas = [casa for casa in dados['imoveis'] if casa[6] == posicao]
    assert len(casas) == 4 and len(dados['imoveis']) == 4 and dados['sem_quarteirao'] == 1
    ids = sorted(casa[0] for casa in casas)
    assert ids == ['1001', '1002', '1003-frente', '1003-fundos']
    assert sorted(dados['ruas']) == ['Rua Dois', 'Rua Um']
    assert sorted(casa[5] for casa in casas if casa[4] == '5') == ['Frente', 'Fundos']
    # A mesma base devolve os mesmos ids: as visitas apontam para eles.
    servico.esquecer_base()
    assert servico.base()['versao'] == dados['versao']
    assert servico.indice()['casas'][base['a']] == 4 and servico.indice()['casas'][base['b']] == 0


def test_base_responde_304_quando_nao_mudou(client, base):
    entrar(client, conta('admin@example.test', role='admin'))
    primeira = client.get(RAIZ + '/base.json', **HTTPS)
    assert primeira.status_code == 200 and primeira.json['versao']
    assert client.get(RAIZ + '/base.json', headers={'If-None-Match': primeira.headers['ETag']}, **HTTPS).status_code == 304


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------

def test_equipe_abre_e_registra_sem_ver_o_resto_do_sfa(client, restrito, base):
    membro = agente()
    entrar(client, membro)
    pagina = client.get(RAIZ, **HTTPS)
    assert pagina.status_code == 200 and pagina.headers['Cache-Control'] == 'private, no-store'
    html = pagina.get_data(as_text=True)
    assert 'id="cac-mapa"' in html and '"registra": true' in html and 'Ana Agente' in html
    assert client.get(RAIZ + '/estado', **HTTPS).json['registra'] is True
    assert enviar(client, visita(base['a'])).status_code == 200
    for rota in ('/sfa/', '/sfa/pacientes'):
        assert client.get(rota, **HTTPS).status_code in (403, 404), rota


def test_sem_conta_ou_sem_papel_nao_entra_nem_grava(client, restrito, base):
    for rota in ('', '/base.json', '/estado', '/visitas.csv', '/boletim.csv'):
        anonimo = client.get(RAIZ + rota, **HTTPS)
        assert anonimo.status_code == 302 and '/login' in anonimo.headers['Location'], rota
    assert enviar(client, visita(base['a'])).status_code in (302, 401, 403, 404)
    entrar(client, conta('tutor@example.test'))
    assert client.get(RAIZ, **HTTPS).status_code in (403, 404)
    assert enviar(client, visita(base['a'])).status_code in (403, 404)
    assert planejar(client, 'planejar', [base['a']]).status_code in (403, 404)
    assert Visita.query.count() == 0 and Plano.query.count() == 0


def test_token_interno_le_mas_nao_grava(client, restrito, base, monkeypatch):
    monkeypatch.setenv('SFA_ADMIN_TOKEN', 'token-de-teste')
    assert client.get(RAIZ + '?token=token-de-teste', **HTTPS).status_code == 200
    estado = client.get(RAIZ + '/estado?token=token-de-teste', **HTTPS)
    assert estado.status_code == 200 and estado.json['registra'] is False
    resposta = client.post(RAIZ + '/visitas?token=token-de-teste', json={'visitas': [visita(base['a'])]}, **HTTPS)
    assert resposta.status_code in (302, 401, 403, 404) and Visita.query.count() == 0


# ---------------------------------------------------------------------------
# Plano do dia
# ---------------------------------------------------------------------------

def test_escritorio_planeja_troca_responsavel_e_tira_do_plano(client, base):
    coordenadora, ana = agente('coord@example.test', 'Carla Coordenadora'), agente('ana@example.test', 'Ana Agente')
    entrar(client, coordenadora)
    hoje = hoje_local()

    resposta = planejar(client, 'planejar', [base['a'], base['b'], 'nao-existe'], responsavel_id=ana.id)
    assert resposta.status_code == 200 and resposta.json['feitos'] == 2
    planos = {p['b']: p for p in resposta.json['planos']}
    assert planos[base['a']]['r'] == 'Ana Agente' and planos[base['a']]['d'] == hoje.isoformat() and planos[base['a']]['c'] is None

    planejar(client, 'planejar', [base['a']])                      # de novo, sem responsável: troca, não duplica
    assert Plano.query.count() == 2 and Plano.query.filter_by(bloco=base['a']).one().responsavel is None
    amanha = (hoje + timedelta(days=1)).isoformat()
    assert planejar(client, 'planejar', [base['b']], data=amanha).json['feitos'] == 1
    assert Plano.query.filter_by(bloco=base['b']).count() == 2

    assert planejar(client, 'remover', [base['b']], data=amanha).json['feitos'] == 1
    assert planejar(client, 'planejar', [base['a']], data=(hoje - timedelta(days=1)).isoformat()).status_code == 400
    assert planejar(client, 'planejar', [base['a']], responsavel_id=999999).status_code == 400
    assert planejar(client, 'inventar', [base['a']]).status_code == 400
    assert planejar(client, 'planejar', []).status_code == 400
    assert SfaAuditoria.query.filter(SfaAuditoria.funcao.like('casa_a_casa_%')).count() == 4


def test_quarteirao_com_visita_nao_sai_do_plano_e_pode_ser_concluido_e_reaberto(client, base):
    ana = agente()
    entrar(client, ana)
    planejar(client, 'planejar', [base['a']], responsavel_id=ana.id)
    enviar(client, visita(base['a']))
    assert planejar(client, 'remover', [base['a']]).json['feitos'] == 0 and Plano.query.count() == 1

    concluido = planejar(client, 'concluir', [base['a']])
    plano = Plano.query.one()
    assert concluido.json['feitos'] == 1 and plano.concluido_em and plano.concluido_por == 'Ana Agente'
    eu = next(a for a in concluido.json['agentes'] if a['id'] == ana.id)
    assert (eu['visitas'], eu['hoje'], eu['quarteiroes'], eu['quarteiroes_hoje']) == (1, 1, 1, 1)
    assert planejar(client, 'concluir', [base['a']]).json['feitos'] == 0          # já concluído hoje
    assert planejar(client, 'reabrir', [base['a']]).json['feitos'] == 1 and Plano.query.one().concluido_em is None

    # Concluir quarteirão que nunca entrou no plano cria a linha já concluída.
    assert planejar(client, 'concluir', [base['b']]).json['feitos'] == 1
    assert Plano.query.filter_by(bloco=base['b']).one().concluido_por_id == ana.id


# ---------------------------------------------------------------------------
# Visitas
# ---------------------------------------------------------------------------

def test_visita_guarda_os_campos_do_boletim_e_reenvio_nao_duplica(client, base):
    ana = agente()
    entrar(client, ana)
    completa = visita(base['a'], recipientes_existentes=4, recipientes_agua=2, recipientes_larva=1, tubitos=2,
                      controle_mecanico=True, tratamento_focal=True, observacao=' Caixa d’água vedada ',
                      lat=-20.72, lng=-47.88, agente='Outra Pessoa')
    resposta = enviar(client, completa)
    assert resposta.json == {'ok': True, 'aceitas': ['visita-0001'], 'recusadas': [], 'novas': 1}
    v = Visita.query.one()
    assert (v.situacao, v.recipientes_existentes, v.recipientes_agua, v.recipientes_larva, v.tubitos) == ('TRABALHADO', 4, 2, 1, 2)
    assert (v.larvas_encontradas, v.controle_mecanico, v.controle_alternativo, v.tratamento_focal) == (True, True, False, True)
    assert (v.agente_id, v.agente, v.observacao, v.data_visita) == (ana.id, 'Ana Agente', 'Caixa d’água vedada', hoje_local())
    # Registrar em quarteirão fora do plano cria a linha dele.
    plano = Plano.query.one()
    assert (plano.bloco, plano.responsavel_id, plano.concluido_em) == (base['a'], ana.id, None)

    assert enviar(client, completa).json['novas'] == 0 and Visita.query.count() == 1 and Plano.query.count() == 1


def test_sem_inspecao_zera_recipientes_e_contagens_ficam_coerentes(client, base):
    entrar(client, agente())
    enviar(client,
           visita(base['a'], '1002', 'FECHADO', 'visita-0002', recipientes_existentes=9, tubitos=3, larvas=True, controle_mecanico=True),
           visita(base['a'], '1003-abc', 'PARCIAL', 'visita-0003', recipientes_existentes=1, recipientes_agua=0, recipientes_larva=3))
    fechado, parcial = Visita.query.order_by(Visita.id).all()
    assert (fechado.recipientes_existentes, fechado.tubitos, fechado.larvas_encontradas, fechado.controle_mecanico) == (0, 0, False, False)
    # existentes >= com água >= com larva, e recipiente com larva marca o imóvel.
    assert (parcial.recipientes_existentes, parcial.recipientes_agua, parcial.recipientes_larva, parcial.larvas_encontradas) == (3, 3, 3, True)


def test_lote_aceita_as_boas_e_explica_as_recusadas(client, base):
    entrar(client, agente())
    antiga = (hoje_local() - timedelta(days=servico.JANELA_DIAS + 5)).isoformat()
    resposta = enviar(client,
                      visita(base['a'], uuid='visita-boa-1'),
                      visita('quarteirao-inventado', uuid='visita-ruim-1'),
                      visita(base['a'], situacao='ABERTA', uuid='visita-ruim-2'),
                      visita(base['a'], uuid='visita-ruim-3', data=antiga),
                      visita(base['a'], uuid='visita-ruim-4', recipientes_existentes='muitos'),
                      visita(base['a'], uuid='x'))
    assert resposta.status_code == 200 and resposta.json['aceitas'] == ['visita-boa-1']
    motivos = {r['uuid']: r['motivo'] for r in resposta.json['recusadas']}
    assert motivos['visita-ruim-1'] == 'Quarteirão desconhecido.' and 'Situação' in motivos['visita-ruim-2']
    assert 'Data' in motivos['visita-ruim-3'] and 'recipientes existentes' in motivos['visita-ruim-4'] and 'x' in motivos
    assert Visita.query.count() == 1
    assert enviar(client).status_code == 400
    assert client.post(RAIZ + '/visitas', json={'visitas': [visita(base['a'])] * 301}, **HTTPS).status_code == 400


def test_recuperar_pendencia_fica_marcado(client, base):
    entrar(client, agente())
    enviar(client, visita(base['a'], situacao='FECHADO', uuid='visita-ida'))
    enviar(client, visita(base['a'], situacao='TRABALHADO', uuid='visita-volta'),
           visita(base['a'], '1002', 'TRABALHADO', 'visita-outra'))
    marcas = {v.uuid_local: v.recuperacao for v in Visita.query.all()}
    assert marcas == {'visita-ida': False, 'visita-volta': True, 'visita-outra': False}


# ---------------------------------------------------------------------------
# Ao vivo e exportação
# ---------------------------------------------------------------------------

def test_estado_traz_a_ultima_visita_de_cada_imovel_e_depois_so_as_novas(client, base):
    ana, bia = agente(), agente('bia@example.test', 'Bia Agente')
    entrar(client, ana)
    enviar(client, visita(base['a'], situacao='FECHADO', uuid='visita-ana-1'), visita(base['a'], uuid='visita-ana-2'))
    inicial = client.get(RAIZ + '/estado', **HTTPS).json
    assert inicial['parcial'] is False and inicial['hoje'] == hoje_local().isoformat() and inicial['csrf']
    assert [(v['u'], v['s'], v['rc']) for v in inicial['visitas']] == [('visita-ana-2', 'TRABALHADO', 1)]
    assert inicial['visitas'][0]['a'] == 'Ana Agente' and inicial['visitas'][0]['m'] == '1001'

    entrar(client, bia)
    enviar(client, visita(base['a'], '1002', 'RECUSA', 'visita-bia-1'))
    entrar(client, ana)
    depois = client.get(f"{RAIZ}/estado?desde={inicial['cursor']}", **HTTPS).json
    assert depois['parcial'] is True and [v['u'] for v in depois['visitas']] == ['visita-bia-1']
    assert depois['cursor'] > inicial['cursor'] and len(depois['planos']) == 1
    assert [(a['nome'], a['hoje'], a['recuperadas']) for a in depois['agentes']] == [('Ana Agente', 2, 1), ('Bia Agente', 1, 0)]
    assert client.get(f"{RAIZ}/estado?desde={depois['cursor']}", **HTTPS).json['visitas'] == []


def test_boletim_usa_as_colunas_do_arquivo_oficial(client, base):
    entrar(client, agente())
    enviar(client,
           visita(base['a'], '1001', 'FECHADO', 'visita-b1'),
           visita(base['a'], '1001', 'TRABALHADO', 'visita-b2', recipientes_existentes=5, recipientes_agua=2, recipientes_larva=1, controle_mecanico=True),
           visita(base['a'], '1002', 'RECUSA', 'visita-b3'),
           visita(base['a'], '1003-abc', 'TRABALHADO', 'visita-b4', recipientes_existentes=2, tratamento_focal=True))
    hoje = hoje_local()
    (linha,) = servico.boletim(hoje, hoje)
    # Vale a última visita de cada imóvel no dia: o 1001 conta como trabalhado, não como fechado.
    assert (linha['IM TRAB'], linha['IM FECH'], linha['IM RECUSA'], linha['IM. LARVA']) == (2, 0, 1, 1)
    assert (linha['REC. EXIST.'], linha['REC. AGUA'], linha['REC. LARVA'], linha['IM MECANICO'], linha['IM FOCAL']) == (7, 2, 1, 1, 1)
    from scripts.import_entomologia import METRICS
    assert set(servico.COLUNAS_BOLETIM) <= set(METRICS.values())

    planilha = client.get(RAIZ + '/boletim.csv', **HTTPS)
    assert planilha.status_code == 200 and 'attachment' in planilha.headers['Content-Disposition']
    texto = planilha.get_data(as_text=True)
    assert texto.splitlines()[0].lstrip('﻿').startswith('DATA;SETOR;QUARTEIRAO;IM TRAB;IM FECH') and len(texto.splitlines()) == 2
    visitas = client.get(RAIZ + '/visitas.csv', **HTTPS).get_data(as_text=True).splitlines()
    assert len(visitas) == 5 and 'Trabalhado' in visitas[2] and 'Ana Agente' in visitas[1]
    # Texto digitado na rua não vira fórmula na planilha.
    enviar(client, visita(base['a'], '1002', 'FECHADO', 'visita-b5', observacao='=SOMA(A1:A9)'))
    assert ";'=SOMA(A1:A9)" in client.get(RAIZ + '/visitas.csv', **HTTPS).get_data(as_text=True)
    assert client.get(RAIZ + '/boletim.csv?inicio=2026-13-40', **HTTPS).status_code == 400


def test_pagina_inicial_e_aba_levam_ao_casa_a_casa(client, base):
    entrar(client, agente())
    assert '/sfa/entomologia/casa-a-casa' in client.get('/', **HTTPS).get_data(as_text=True)
    painel = client.get('/sfa/entomologia', **HTTPS).get_data(as_text=True)
    assert 'Abrir o Casa a Casa' in painel and 'sfa_fieldwork' not in painel
