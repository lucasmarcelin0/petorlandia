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


def test_base_leva_o_nome_das_ruas_para_o_mapa_em_branco(base):
    vias = servico.base()['vias']
    assert len(vias['nomes']) > 200 and len(vias['pontos']) > 1500
    # Mesmo formato da lista de casas: número em algarismo, não por extenso.
    assert 'Rua 12' in vias['nomes'] and 'Rua 26' in vias['nomes'] and 'Rua Doze' not in vias['nomes']
    assert servico.nome_de_rua('Rua  Vinte e Seis') == 'Rua 26' and servico.nome_de_rua('Avenida do Café') == 'Avenida do Café'
    for x, y, giro, indice in vias['pontos']:
        # Dentro do município, texto nunca de cabeça para baixo, nome existente.
        assert -48.2 < x < -47.6 and -21.0 < y < -20.4 and -90 <= giro <= 90 and 0 <= indice < len(vias['nomes'])
    # Rua comprida tem o nome repetido ao longo dela; via que ainda não existe fica de fora.
    por_nome = {}
    for _x, _y, _giro, indice in vias['pontos']:
        por_nome[vias['nomes'][indice]] = por_nome.get(vias['nomes'][indice], 0) + 1
    assert por_nome['Rua 12'] >= 5 and min(por_nome.values()) >= 1
    from services import entomologia_atlas_editor as editor
    propostas = {servico.nome_de_rua(f['properties']['name']) for f in editor.references()['features']
                 if f['properties'].get('category') == 'proposed'}
    construidas = {servico.nome_de_rua(f['properties']['name']) for f in editor.references()['features']
                   if f['geometry']['type'] == 'LineString' and f['properties'].get('category') != 'proposed'}
    assert not (propostas - construidas) & set(vias['nomes'])


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

def test_plano_desatualizado_nao_sobrescreve_o_lote(client, base):
    ana, bia = agente(), agente('bia@example.test', 'Bia')
    entrar(client, ana)
    resposta = planejar(client, 'planejar', [base['a']], responsavel_id=ana.id)
    antigo = resposta.json['planos'][0]
    esperado = [{k: antigo[k] for k in ('b', 'id', 'ri', 'c', 'v')}, {'b': base['b']}]
    planejar(client, 'planejar', [base['a']], responsavel_id=bia.id)
    conflito = planejar(client, 'planejar', [base['a'], base['b']], responsavel_id=ana.id, esperado=esperado)
    assert conflito.status_code == 409
    assert Plano.query.count() == 1
    assert Plano.query.one().responsavel_id == bia.id


def test_reagendamento_move_sem_duplicar_e_preserva_visitas(client, base):
    ana = agente()
    entrar(client, ana)
    hoje = hoje_local()
    origem, destino = (hoje + timedelta(days=1)).isoformat(), (hoje + timedelta(days=4)).isoformat()
    resposta = planejar(client, 'planejar', [base['a'], base['b']], data=origem, responsavel_id=ana.id)
    esperado = [{k: p[k] for k in ('b', 'id', 'ri', 'c', 'v')} for p in resposta.json['planos']]
    movido = planejar(client, 'reagendar', [base['a'], base['b']], origem=origem, data=destino, responsavel_id=ana.id, esperado=esperado)
    assert movido.status_code == 200 and movido.json['feitos'] == 2
    assert Plano.query.count() == 2
    assert all(p.data.isoformat() == destino for p in Plano.query.all())
    # O lote inteiro é preservado se um dos destinos já estiver ocupado.
    planejar(client, 'planejar', [base['b']], data=origem)
    bloqueado = planejar(client, 'reagendar', [base['a'], base['b']], origem=destino, data=origem)
    assert bloqueado.status_code == 409
    assert Plano.query.filter_by(bloco=base['a']).one().data.isoformat() == destino
    planejar(client, 'planejar', [base['a']], data=hoje.isoformat())
    enviar(client, visita(base['a']))
    assert planejar(client, 'reagendar', [base['a']], origem=hoje.isoformat(), data=origem).status_code == 400
    assert Visita.query.count() == 1


def test_reagendamento_valida_equipe_e_datas(client, base):
    ana = agente()
    entrar(client, ana)
    hoje = hoje_local().isoformat()
    planejar(client, 'planejar', [base['a']], data=hoje)
    for dados in ({'data': hoje}, {'data': '1900-01-01'}, {'data': '2100-01-01'},
                  {'data': (hoje_local() + timedelta(days=1)).isoformat(), 'responsavel_id': 999999}):
        assert planejar(client, 'reagendar', [base['a']], origem=hoje, **dados).status_code == 400
    assert Plano.query.count() == 1 and Plano.query.one().data.isoformat() == hoje

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


def test_recipientes_por_tipo_da_ficha_do_sisaweb(client, base):
    entrar(client, agente())
    tipos = [{'t': 30, 'e': 1}, {'t': 12, 'e': 2, 'a': 1, 'l': 1}, {'t': 12, 'e': 1}, {'t': 5, 'e': 0}]
    resposta = enviar(client,
                      visita(base['a'], '1001', 'TRABALHADO', 'visita-t1', recipientes_existentes=9, recipientes=tipos),
                      visita(base['a'], '1002', 'FECHADO', 'visita-t2', recipientes=tipos),
                      visita(base['a'], '1003-abc', 'TRABALHADO', 'visita-t3', recipientes=[{'t': 41, 'e': 1}]))
    assert resposta.json['aceitas'] == ['visita-t1', 'visita-t2']
    assert resposta.json['recusadas'] == [{'uuid': 'visita-t3', 'motivo': 'Tipo de recipiente inválido.'}]
    trabalhado, fechado = Visita.query.order_by(Visita.id).all()
    # Com tipo anotado, os totais do boletim são a soma dos tipos; um registro por tipo.
    assert (trabalhado.recipientes_existentes, trabalhado.recipientes_agua, trabalhado.recipientes_larva,
            trabalhado.larvas_encontradas) == (4, 1, 1, True)
    assert servico.recipientes_da_visita(trabalhado) == [{'t': 12, 'e': 3, 'a': 1, 'l': 1}, {'t': 30, 'e': 1, 'a': 0, 'l': 0}]
    assert fechado.recipientes_json is None and fechado.recipientes_existentes == 0

    estado = client.get(RAIZ + '/estado', **HTTPS).json
    assert next(v for v in estado['visitas'] if v['m'] == '1001')['rt'][0] == {'t': 12, 'e': 3, 'a': 1, 'l': 1}
    linhas = client.get(RAIZ + '/visitas.csv', **HTTPS).get_data(as_text=True).splitlines()
    assert linhas[0].endswith(';TIPOS DE RECIPIENTE')
    assert any(linha.endswith('C12 (3 exist., 1 água, 1 larva) | F30 (1 exist.)') for linha in linhas)
    planilha = client.get(RAIZ + '/recipientes.csv', **HTTPS)
    assert planilha.status_code == 200 and 'attachment' in planilha.headers['Content-Disposition']
    cabecalho, *corpo = planilha.get_data(as_text=True).lstrip('\ufeff').splitlines()
    assert cabecalho == 'DATA;SETOR;QUARTEIRAO;GRUPO;TIPO;RECIPIENTE;IMOVEIS;REC. EXIST.;REC. AGUA;REC. LARVA'
    assert [linha.split(';')[3:] for linha in corpo] == [['C', '12', 'Lata, frasco, plástico utilizáveis', '1', '3', '1', '1'],
                                                         ['F', '30', 'Lata, frasco, plástico', '1', '1', '0', '0']]


def test_tela_traz_os_40_tipos_de_recipiente_e_a_equipe(client, base):
    ana, bia = agente(), agente('bia@example.test', 'Bia Agente')
    entrar(client, ana)
    import json
    import re
    html = client.get(RAIZ, **HTTPS).get_data(as_text=True)
    config = json.loads(re.search(r'id="cac-config">(.*?)</script>', html, re.S).group(1))
    assert {pessoa['nome'] for pessoa in config['equipe']} == {'Ana Agente', 'Bia Agente'}
    assert config['recipientes'][0] == {'g': 'A', 'nome': 'Depósito elevado', 'tipos': [[1, 'Ligado à rede'], [2, 'Não ligado à rede']]}
    assert config['recipientes'][-1]['tipos'][1] == [39, 'Bromélias'] and config['urls']['recipientes_csv']
    assert sorted(servico.TIPOS_RECIPIENTE) == list(range(1, 41))
    assert [grupo['g'] for grupo in servico.grupos_recipiente()] == list('ABCDEFG')
    # O plano do dia aceita qualquer pessoa da equipe e troca o responsável com outro clique.
    assert planejar(client, 'planejar', [base['a']], responsavel_id=bia.id).json['feitos'] == 1
    assert planejar(client, 'planejar', [base['a']], responsavel_id=ana.id).json['planos'][0]['ri'] == ana.id


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
