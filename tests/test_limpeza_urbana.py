"""Limpeza urbana: comunicação com foto e GPS, comprovação da equipe, fiscalização e papéis."""
import io
from datetime import datetime, timedelta

import pytest
from flask import g
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from extensions import db
from models import User
from models.limpeza import LimpezaAcesso, LimpezaComprovacao, LimpezaEvento, LimpezaSolicitacao
from services import limpeza_urbana as servico
from time_utils import now_in_brazil

PONTO = (-20.7205, -47.8750)
# Sem Accept: text/html o app responde 404 em vez de 403 (não revela que a rota existe).
NEGADO = (403, 404)


def conta(email, role='adotante', name=None):
    user = User(name=name or email.split('@')[0].title(), email=email, password_hash='x', role=role)
    db.session.add(user)
    db.session.commit()
    return user


def entrar(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    limpar_g()


def limpar_g():
    for chave in ('_login_user', '_limpeza_papeis', 'user_experience', '_site_flag_cache'):
        g.pop(chave, None)


def dar(user, *papeis, inicio=None, fim=None):
    servico.conceder(user, papeis, inicio, fim, 'Coordenação')
    db.session.commit()
    limpar_g()


def _gps(valor):
    graus = int(valor)
    minutos_f = (valor - graus) * 60
    minutos = int(minutos_f)
    segundos = round((minutos_f - minutos) * 60 * 1000)
    return (IFDRational(graus, 1), IFDRational(minutos, 1), IFDRational(segundos, 1000))


def foto(lat=None, lon=None, tirada_em=None):
    imagem = Image.new('RGB', (64, 48), (120, 160, 90))
    exif = Image.Exif()
    if tirada_em is not None:
        exif.get_ifd(0x8769)[0x9003] = tirada_em.strftime('%Y:%m:%d %H:%M:%S')
    if lat is not None:
        gps = exif.get_ifd(0x8825)
        gps[1] = 'S' if lat < 0 else 'N'
        gps[2] = _gps(abs(lat))
        gps[3] = 'W' if lon < 0 else 'E'
        gps[4] = _gps(abs(lon))
    buffer = io.BytesIO()
    imagem.save(buffer, format='JPEG', exif=exif)
    buffer.seek(0)
    return buffer


@pytest.fixture()
def uploads(monkeypatch):
    import app as app_module
    enviados = []

    def falso(stream, filename, folder='uploads', **kwargs):
        enviados.append((folder, filename))
        return f'https://fotos.example.test/{folder}/{filename}'

    monkeypatch.setattr(app_module, 'upload_to_s3', falso)
    return enviados


def comunicar(client, categoria='galhos', lat=PONTO[0], lon=PONTO[1], arquivo=None, **extra):
    # Como o navegador envia: o campo da câmera com a foto e o da galeria vazio.
    dados = {'categoria': categoria, 'foto': [(arquivo or foto(), 'foto.jpg'), (io.BytesIO(b''), '')], **extra}
    if lat is not None:
        dados.update(latitude=str(lat), longitude=str(lon), precisao='8')
    return client.post('/limpeza-urbana/comunicar', data=dados, content_type='multipart/form-data')


def comprovar(client, solicitacao_id, lat=PONTO[0], lon=PONTO[1], arquivo=None):
    return client.post(f'/limpeza-urbana/solicitacao/{solicitacao_id}/comprovar', data={
        'latitude': str(lat), 'longitude': str(lon), 'precisao': '6',
        'foto': (arquivo or foto(), 'depois.jpg')}, content_type='multipart/form-data')


def test_sem_papel_nao_acessa_nada(app, client):
    user = conta('sem@example.test')
    entrar(client, user)
    for rota in ('/limpeza-urbana/', '/limpeza-urbana/comunicar', '/limpeza-urbana/mapa',
                 '/limpeza-urbana/mapa/dados', '/limpeza-urbana/acessos', '/limpeza-urbana/relatorio.csv'):
        assert client.get(rota).status_code in NEGADO, rota
    from services.workspaces import current_experience
    with app.test_request_context():
        from flask_login import login_user
        login_user(user)
        assert 'limpeza' not in current_experience().capabilities


def test_colaborador_comunica_com_gps_do_aparelho(app, client, uploads):
    user = conta('morador@example.test')
    dar(user, 'colaborador')
    entrar(client, user)
    resposta = comunicar(client, referencia='Canteiro da Av. 3', descricao='Galhos da poda')
    assert resposta.status_code == 302 and resposta.headers['Location'].endswith('/limpeza-urbana/minhas')
    item = LimpezaSolicitacao.query.one()
    assert (item.latitude, item.longitude, item.origem_local, item.precisao_m) == (PONTO[0], PONTO[1], 'aparelho', 8.0)
    assert item.status == 'aberta' and item.autor_id == user.id and item.categorias == 'galhos'
    assert item.foto_url.startswith('https://fotos.example.test/limpeza/comunicacoes/')
    assert uploads[0][0] == 'limpeza/comunicacoes'
    assert LimpezaEvento.query.filter_by(tipo='comunicada', solicitacao_id=item.id).count() == 1
    # Acompanha as próprias, mas não vê o mapa de todos.
    limpar_g()
    assert 'Galhos e poda' in client.get('/limpeza-urbana/minhas').get_data(as_text=True)
    assert client.get(f'/limpeza-urbana/solicitacao/{item.id}').status_code == 200
    assert client.get('/limpeza-urbana/mapa').status_code in NEGADO
    assert comprovar(client, item.id).status_code in NEGADO


def test_comunicacao_sem_localizacao_e_recusada(client, uploads):
    user = conta('semgps@example.test')
    dar(user, 'colaborador')
    entrar(client, user)
    resposta = comunicar(client, lat=None)
    assert resposta.status_code == 400
    assert 'localização' in resposta.get_data(as_text=True)
    assert LimpezaSolicitacao.query.count() == 0 and uploads == []


def test_gps_gravado_na_foto_vale_mais_que_o_do_aparelho(client, uploads):
    user = conta('galeria@example.test')
    dar(user, 'colaborador')
    entrar(client, user)
    tirada = datetime(2026, 11, 10, 7, 45, 12)
    resposta = comunicar(client, lat=-23.55, lon=-46.63, arquivo=foto(-20.71234, -47.88765, tirada))
    assert resposta.status_code == 302
    item = LimpezaSolicitacao.query.one()
    assert item.origem_local == 'foto'
    assert abs(item.latitude - -20.71234) < 1e-4 and abs(item.longitude - -47.88765) < 1e-4
    assert servico.hora_local(item.foto_capturada_em) == '10/11/2026 07:45'


def test_comunicacao_de_outra_pessoa_nao_aparece(client, uploads):
    autor, curioso = conta('a@example.test'), conta('b@example.test')
    dar(autor, 'colaborador')
    dar(curioso, 'colaborador')
    entrar(client, autor)
    comunicar(client)
    item = LimpezaSolicitacao.query.one()
    entrar(client, curioso)
    assert client.get(f'/limpeza-urbana/solicitacao/{item.id}').status_code in NEGADO
    assert 'Nº' not in client.get('/limpeza-urbana/minhas').get_data(as_text=True)


def _comunicada(client):
    morador = conta('morador@example.test')
    dar(morador, 'colaborador')
    entrar(client, morador)
    comunicar(client, categoria='moveis')
    return LimpezaSolicitacao.query.one()


def test_equipe_ve_mapa_e_comprova_no_local(client, uploads):
    item = _comunicada(client)
    equipe = conta('gari@example.test')
    dar(equipe, 'equipe')
    entrar(client, equipe)
    assert client.get('/limpeza-urbana/').headers['Location'].endswith('/limpeza-urbana/mapa')
    assert client.get('/limpeza-urbana/mapa').status_code == 200
    dados = client.get('/limpeza-urbana/mapa/dados').get_json()
    assert [p['id'] for p in dados['pontos']] == [item.id]
    assert 'autor' not in dados['pontos'][0]  # a equipe não precisa saber quem comunicou
    assert dados['indicadores']['abertas'] == 1
    assert 'Comprovar limpeza' in client.get(f'/limpeza-urbana/solicitacao/{item.id}').get_data(as_text=True)

    resposta = comprovar(client, item.id, lat=PONTO[0] + 0.0001, lon=PONTO[1])
    assert resposta.status_code == 302
    item = db.session.get(LimpezaSolicitacao, item.id)
    assert item.status == 'concluida' and item.concluida_em is not None
    comprovacao = item.comprovacao_valida
    assert comprovacao.autor_id == equipe.id and 10 < comprovacao.distancia_m < 12
    assert uploads[-1][0] == 'limpeza/comprovacoes'
    limpar_g()
    dados = client.get('/limpeza-urbana/mapa/dados').get_json()
    assert dados['pontos'][0]['comprovacao']['longe'] is False
    assert dados['indicadores']['concluidas'] == 1
    # Uma vez comprovada, não aceita outra comprovação.
    assert comprovar(client, item.id).status_code == 302
    assert LimpezaComprovacao.query.count() == 1


def test_comprovacao_longe_do_ponto_fica_marcada(client, uploads):
    item = _comunicada(client)
    equipe = conta('gari@example.test')
    dar(equipe, 'equipe')
    entrar(client, equipe)
    comprovar(client, item.id, lat=PONTO[0] + 0.003, lon=PONTO[1])  # ~330 m
    dados = client.get('/limpeza-urbana/mapa/dados').get_json()
    assert dados['pontos'][0]['comprovacao']['longe'] is True
    assert dados['indicadores']['comprovacoes_longe'] == 1


def test_comprovacao_com_foto_antiga_e_recusada(client, uploads):
    item = _comunicada(client)
    equipe = conta('gari@example.test')
    dar(equipe, 'equipe')
    entrar(client, equipe)
    antiga = now_in_brazil().replace(tzinfo=None) - timedelta(days=2)
    comprovar(client, item.id, arquivo=foto(PONTO[0], PONTO[1], antiga))
    assert db.session.get(LimpezaSolicitacao, item.id).status == 'aberta'
    assert LimpezaComprovacao.query.count() == 0


def test_fiscal_recusa_comprovacao_e_comunicacao_volta_para_fila(client, uploads):
    item = _comunicada(client)
    equipe, fiscal = conta('gari@example.test'), conta('fiscal@example.test')
    dar(equipe, 'equipe')
    dar(fiscal, 'fiscal')
    entrar(client, equipe)
    comprovar(client, item.id)
    comprovacao = LimpezaComprovacao.query.one()
    assert client.post(f'/limpeza-urbana/comprovacao/{comprovacao.id}/recusar',
                       data={'motivo': 'x'}).status_code in NEGADO

    entrar(client, fiscal)
    dados = client.get('/limpeza-urbana/mapa/dados').get_json()
    assert dados['pontos'][0]['autor'] == 'Morador'
    client.post(f'/limpeza-urbana/comprovacao/{comprovacao.id}/recusar', data={'motivo': ''})
    assert db.session.get(LimpezaComprovacao, comprovacao.id).status == 'valida'
    client.post(f'/limpeza-urbana/comprovacao/{comprovacao.id}/recusar', data={'motivo': 'Sofá continua lá'})
    comprovacao = db.session.get(LimpezaComprovacao, comprovacao.id)
    assert comprovacao.status == 'recusada' and comprovacao.motivo_recusa == 'Sofá continua lá'
    assert db.session.get(LimpezaSolicitacao, item.id).status == 'aberta'
    pagina = client.get(f'/limpeza-urbana/solicitacao/{item.id}').get_data(as_text=True)
    assert 'Comprovações recusadas' in pagina and 'Sofá continua lá' in pagina and 'Histórico' in pagina

    csv = client.get('/limpeza-urbana/relatorio.csv')
    assert csv.status_code == 200 and 'attachment' in csv.headers['Content-Disposition']
    texto = csv.get_data(as_text=True)
    assert 'Móveis e objetos grandes' in texto and 'Aguardando limpeza' in texto

    client.post(f'/limpeza-urbana/solicitacao/{item.id}/descartar', data={'motivo': 'Duplicada'})
    item = db.session.get(LimpezaSolicitacao, item.id)
    assert item.status == 'descartada' and item.motivo_descarte == 'Duplicada'


def test_equipe_nao_exporta_nem_descarta(client, uploads):
    item = _comunicada(client)
    equipe = conta('gari@example.test')
    dar(equipe, 'equipe')
    entrar(client, equipe)
    assert client.get('/limpeza-urbana/relatorio.csv').status_code in NEGADO
    assert client.post(f'/limpeza-urbana/solicitacao/{item.id}/descartar', data={'motivo': 'x'}).status_code in NEGADO


def test_acesso_vale_somente_no_periodo(client):
    user = conta('mutirao@example.test')
    hoje = servico.hoje()
    dar(user, 'equipe', fim=hoje - timedelta(days=1))
    assert servico.papeis_de(user) == frozenset()
    dar(user, 'equipe', inicio=hoje + timedelta(days=1))
    assert servico.papeis_de(user) == frozenset()
    dar(user, 'equipe', inicio=hoje, fim=hoje)
    assert servico.papeis_de(user) == {'equipe'}
    # Um vínculo ativo por papel: o novo período substituiu os anteriores.
    assert LimpezaAcesso.query.filter_by(user_id=user.id, revogado_em=None).count() == 1
    entrar(client, user)
    assert client.get('/limpeza-urbana/mapa').status_code == 200


def test_admin_atribui_e_revoga_acessos(app, client):
    admin = conta('admin@example.test', role='admin')
    pessoa = conta('fiscal@example.test')
    entrar(client, admin)
    assert client.get('/limpeza-urbana/acessos').status_code == 200
    resposta = client.post('/limpeza-urbana/acessos', data={
        'email': 'FISCAL@example.test', 'papel': ['fiscal', 'colaborador'], 'inicio': '', 'fim': ''})
    assert resposta.status_code == 302
    assert {a.papel for a in LimpezaAcesso.query.filter_by(user_id=pessoa.id)} == {'fiscal', 'colaborador'}
    client.post('/limpeza-urbana/acessos', data={'email': 'ninguem@example.test', 'papel': 'equipe'})
    client.post('/limpeza-urbana/acessos', data={'email': pessoa.email, 'papel': 'equipe',
                                                 'inicio': '2026-12-10', 'fim': '2026-12-01'})
    assert LimpezaAcesso.query.count() == 2
    pagina = client.get('/limpeza-urbana/acessos').get_data(as_text=True)
    assert 'fiscal@example.test' in pagina and 'Fiscalização' in pagina

    fiscal = LimpezaAcesso.query.filter_by(papel='fiscal').one()
    client.post(f'/limpeza-urbana/acessos/{fiscal.id}/revogar')
    limpar_g()
    assert servico.papeis_de(db.session.get(User, pessoa.id)) == {'colaborador'}
    assert db.session.get(User, pessoa.id).role == 'adotante'
    assert LimpezaEvento.query.filter_by(tipo='acesso_revogado').count() == 1

    entrar(client, pessoa)
    assert client.get('/limpeza-urbana/acessos').status_code in NEGADO
    assert client.post(f'/limpeza-urbana/acessos/{fiscal.id}/revogar').status_code in NEGADO


def test_comunicacao_aberta_libera_qualquer_conta(app, client, uploads):
    admin, morador = conta('admin@example.test', role='admin'), conta('qualquer@example.test')
    entrar(client, morador)
    assert client.get('/limpeza-urbana/comunicar').status_code in NEGADO
    entrar(client, admin)
    client.post('/limpeza-urbana/acessos/comunicacao-aberta', data={'aberta': '1'})
    entrar(client, morador)
    assert client.get('/limpeza-urbana/comunicar').status_code == 200
    assert comunicar(client).status_code == 302
    assert client.get('/limpeza-urbana/mapa').status_code in NEGADO  # o mapa continua restrito


def test_cartao_na_pagina_inicial_segue_os_papeis(app):
    from flask_login import login_user
    from services.workspaces import current_experience

    colaborador, equipe = conta('c@example.test'), conta('e@example.test')
    dar(colaborador, 'colaborador')
    dar(equipe, 'equipe')
    for user, tem_mapa in ((colaborador, False), (equipe, True)):
        with app.test_request_context():
            limpar_g()
            login_user(user)
            area = next(w for w in current_experience().workspaces if w.key == 'limpeza')
            rotulos = [a.label for a in area.actions]
            assert rotulos == ['Acessar Prefeitura integrada']
            assert area.actions[0].url.endswith('/limpeza-urbana/')


def test_paginas_renderizam_para_o_admin(client, uploads):
    admin = conta('admin@example.test', role='admin')
    entrar(client, admin)
    comunicar(client)
    item = LimpezaSolicitacao.query.one()
    for rota in ('/limpeza-urbana/comunicar', '/limpeza-urbana/minhas', '/limpeza-urbana/mapa',
                 f'/limpeza-urbana/solicitacao/{item.id}', '/limpeza-urbana/acessos'):
        resposta = client.get(rota)
        assert resposta.status_code == 200, rota
        assert 'Quem acessa' in resposta.get_data(as_text=True), rota


def test_ler_exif_sem_metadados_nao_quebra():
    dados = servico.ler_exif(foto().getvalue())
    assert dados.latitude is None and dados.capturada_em is None
    assert servico.ler_exif(b'nao e imagem').latitude is None


def test_comunicacao_com_varios_tipos_e_foto_da_galeria(client, uploads):
    user = conta('varios@example.test')
    dar(user, 'colaborador')
    entrar(client, user)
    resposta = client.post('/limpeza-urbana/comunicar', data={
        'categoria': ['moveis', 'galhos', 'moveis', 'inventado'],
        'foto': [(io.BytesIO(b''), ''), (foto(), 'galeria.jpg')],
        'latitude': str(PONTO[0]), 'longitude': str(PONTO[1])}, content_type='multipart/form-data')
    assert resposta.status_code == 302
    item = LimpezaSolicitacao.query.one()
    assert item.categorias == 'moveis,galhos' and item.lista_categorias == ['moveis', 'galhos']
    assert servico.rotulo_categorias(item.categorias) == 'Móveis e objetos grandes, Galhos e poda'
    pagina = client.get(f'/limpeza-urbana/solicitacao/{item.id}').get_data(as_text=True)
    assert 'Móveis e objetos grandes, Galhos e poda' in pagina

    sem_tipo = comunicar(client, categoria=[])
    assert sem_tipo.status_code == 400 and 'Marque o que precisa ser limpo' in sem_tipo.get_data(as_text=True)
    sem_foto = client.post('/limpeza-urbana/comunicar', data={
        'categoria': 'lixo', 'foto': [(io.BytesIO(b''), ''), (io.BytesIO(b''), '')],
        'latitude': str(PONTO[0]), 'longitude': str(PONTO[1])}, content_type='multipart/form-data')
    assert sem_foto.status_code == 400 and 'Tire a foto do local' in sem_foto.get_data(as_text=True)
    assert LimpezaSolicitacao.query.count() == 1


def test_filtro_por_tipo_encontra_comunicacao_com_varios_tipos(client, uploads):
    fiscal = conta('fiscal@example.test')
    dar(fiscal, 'fiscal')
    entrar(client, fiscal)
    comunicar(client, categoria=['entulho', 'lixo'])
    comunicar(client, categoria='galhos')
    ids = lambda q: [p['id'] for p in client.get(f'/limpeza-urbana/mapa/dados?{q}').get_json()['pontos']]
    assert len(ids('categoria=lixo')) == 1 and len(ids('categoria=galhos')) == 1 and len(ids('')) == 2


def test_tirar_foto_agora_e_camera_liberada_so_na_limpeza(client):
    user = conta('camera@example.test')
    dar(user, 'equipe')
    entrar(client, user)
    pagina = client.get('/limpeza-urbana/comunicar')
    html = pagina.get_data(as_text=True)
    assert 'Tirar foto agora' in html and 'capture="environment"' in html and 'Escolher da galeria' in html
    assert 'camera=(self)' in pagina.headers['Permissions-Policy']
    assert 'camera=()' in client.get('/').headers['Permissions-Policy']


def test_comprovacao_so_aceita_foto_na_hora(client, uploads):
    item = _comunicada(client)
    equipe = conta('gari@example.test')
    dar(equipe, 'equipe')
    entrar(client, equipe)
    html = client.get(f'/limpeza-urbana/solicitacao/{item.id}').get_data(as_text=True)
    assert 'Tirar foto agora' in html and 'Escolher da galeria' not in html


@pytest.mark.parametrize('papeis,ve,nao_ve', [
    (('colaborador',), ['Comunicar', 'Minhas comunicações'], ['Mapa', 'Quem acessa', 'Exportar relatório']),
    (('equipe',), ['Mapa', 'Comunicar'], ['Quem acessa', 'Exportar relatório']),
    (('fiscal',), ['Mapa', 'Exportar relatório'], ['Quem acessa']),
])
def test_cada_papel_ve_somente_o_que_pode(client, papeis, ve, nao_ve):
    user = conta('papel@example.test')
    dar(user, *papeis)
    entrar(client, user)
    destino = '/limpeza-urbana/mapa' if 'Mapa' in ve else '/limpeza-urbana/comunicar'
    html = client.get(destino).get_data(as_text=True)
    nav = html[html.index('limpeza-nav'):html.index('</nav>', html.index('limpeza-nav'))]
    pagina = html
    for rotulo in ve:
        assert rotulo in pagina, rotulo
    for rotulo in nao_ve:
        assert rotulo not in nav and rotulo not in pagina.split('</nav>', 1)[-1].split('<footer', 1)[0], rotulo
    assert client.get('/limpeza-urbana/acessos').status_code in NEGADO


def test_contabilidade_vem_logo_depois_da_area_profissional(app):
    from flask_login import login_user
    from services.workspaces import resolve_experience

    admin = conta('admin@example.test', role='admin')
    with app.test_request_context():
        limpar_g()
        login_user(admin)
        chaves = [w.key for w in resolve_experience(admin, accounting=True).workspaces]
    assert chaves.index('accounting') == chaves.index('professional') + 1
    assert chaves.index('accounting') < chaves.index('delivery')


def test_envio_ajax_devolve_erro_sem_redirecionar_e_aceita_correcao(client, uploads):
    user = conta('ajax@example.test')
    dar(user, 'colaborador')
    entrar(client, user)
    headers = {'X-Requested-With': 'XMLHttpRequest'}
    dados = {'foto': (foto(), 'foto.jpg'), 'latitude': str(PONTO[0]), 'longitude': str(PONTO[1])}
    resposta = client.post('/limpeza-urbana/comunicar', data=dados, headers=headers)
    assert resposta.status_code == 400
    assert 'Marque' in resposta.json['erro']
    assert not uploads
    dados['foto'] = (foto(), 'foto.jpg')
    dados['categoria'] = 'galhos'
    resposta = client.post('/limpeza-urbana/comunicar', data=dados, headers=headers)
    assert resposta.status_code == 200
    assert resposta.json['destino'].endswith('/limpeza-urbana/minhas')
    assert LimpezaSolicitacao.query.count() == 1
