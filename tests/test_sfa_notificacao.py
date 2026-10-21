"""Área "Notificação SINAN": unidades de saúde, responsáveis, fichas da unidade e panorama."""
import json
from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup
from flask import g
from werkzeug.datastructures import MultiDict

from extensions import db
from models import User
from models.sfa import SfaAuditoria, SfaPaciente, SfaSinanLog, SfaUnidadeResponsavel, SfaUnidadeSaude
from services import sfa_notificacao as notificacao
from services import sfa_service
from services.sfa_pre_t0 import (FULL_KEY, carregar_esquema_pre_t0, coletar_respostas_pre_t0,
                                 respostas_para_formulario)
from services.sfa_workflow import hoje_local
from tests.test_sfa_pre_t0_obrigatorios import OBRIGATORIOS

HTTPS = {'base_url': 'https://localhost'}


def conta(email, role='tutor', name='Pessoa da Unidade'):
    user = User(name=name, email=email, password_hash='x', role=role)
    db.session.add(user)
    db.session.commit()
    return user


def entrar(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    # O contexto do app de teste é compartilhado entre requisições.
    for chave in ('_login_user', '_entomologia_membro', '_sfa_unidades_usuario', 'user_experience'):
        g.pop(chave, None)


def unidade(nome='UBS Teste', cnes='7654321', apelidos=None):
    registro = SfaUnidadeSaude(nome=nome, cnes=cnes, apelidos=apelidos, criado_por='Teste')
    db.session.add(registro)
    db.session.commit()
    return registro


def responsavel(registro, email, name='Pessoa da Unidade'):
    user = conta(email, name=name)
    notificacao.conceder(registro, user, 'Admin')
    db.session.commit()
    return user


def ficha_form(**extra):
    dados = {'ficha_sinan': '2985999', 'agravo': '1', 'data_notificacao': '2026-10-12',
             'data_inicio_sintomas': '2026-10-10', 'nome': 'Maria Paciente', **OBRIGATORIOS}
    dados.update(extra)
    return dados


COMPLETA = dict(
    data_nascimento='1990-05-04', sexo='M', gestante='6', raca_cor='4', escolaridade='6',
    municipio_residencia='Orlândia', bairro='Centro', logradouro='Rua Um', zona='1',
    data_investigacao='2026-10-12', doencas_preexistentes__diabetes='2', hospitalizacao='2',
    caso_autoctone='1', classificacao='10', criterio_confirmacao='1', evolucao_caso='1',
    data_encerramento='2026-10-30',
)


def respostas(**extra):
    return coletar_respostas_pre_t0(MultiDict(ficha_form(**extra)))


def ficha_antiga(**form):
    """Respostas de uma ficha gravada antes de a ficha exigir campos: qualquer um pode estar em branco."""
    schema = carregar_esquema_pre_t0()
    sem_exigencia = [{**secao, 'fields': [{k: v for k, v in campo.items() if k not in ('required', 'required_with')}
                                          for campo in secao['fields']]} for secao in schema['sections']]
    return coletar_respostas_pre_t0(MultiDict(form), {**schema, 'sections': sem_exigencia})


def chaves(itens):
    return [item['chave'] for item in itens]


@pytest.fixture()
def restrito(app, monkeypatch):
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    return app


@pytest.fixture()
def ubs(app):
    return unidade()


@pytest.fixture()
def autora(app, client, ubs):
    user = responsavel(ubs, 'autora@example.test', 'Ana Autora')
    entrar(client, user)
    return user


def registrar(client, **extra):
    resposta = client.post('/sfa/notificacao/ficha', data=ficha_form(**extra), **HTTPS)
    assert resposta.status_code == 302, resposta.get_data(as_text=True)[:400]
    return SfaSinanLog.query.order_by(SfaSinanLog.id.desc()).first()


# ---------------------------------------------------------------------------
# Unidades e responsáveis
# ---------------------------------------------------------------------------

def test_admin_cadastra_unidade_e_indica_responsavel(app, client):
    admin = conta('admin-sinan@example.test', role='admin', name='Admin')
    pessoa = conta('Enfermeira@Example.test', name='Enfermeira')
    entrar(client, admin)
    assert client.get('/sfa/notificacao/unidades', **HTTPS).status_code == 200

    client.post('/sfa/notificacao/unidades', data={'nome': '  UBS  Nova ', 'cnes': '1234567', 'apelidos': 'UBS 9; Posto Novo'}, **HTTPS)
    criada = SfaUnidadeSaude.query.one()
    assert (criada.nome, criada.cnes, criada.apelidos, criada.criado_por) == ('UBS Nova', '1234567', 'UBS 9\nPosto Novo', 'Admin')
    for repetida in ({'nome': 'ubs nova'}, {'nome': 'Outra', 'cnes': '1234567'}, {'nome': 'Outra', 'cnes': '12'}, {'nome': ''}):
        client.post('/sfa/notificacao/unidades', data=repetida, **HTTPS)
    assert SfaUnidadeSaude.query.count() == 1

    url = f'/sfa/notificacao/unidades/{criada.id}/responsaveis'
    client.post(url, data={'email': ' enfermeira@example.TEST '}, **HTTPS)
    client.post(url, data={'email': 'enfermeira@example.test'}, **HTTPS)
    client.post(url, data={'email': 'ninguem@example.test'}, **HTTPS)
    vinculo = SfaUnidadeResponsavel.query.one()
    assert (vinculo.user_id, vinculo.concedido_por, vinculo.revogado_em) == (pessoa.id, 'Admin', None)
    assert [u.id for u in notificacao.unidades_do_usuario(pessoa)] == [criada.id]
    assert db.session.get(User, pessoa.id).role == 'tutor'
    pagina = client.get('/sfa/notificacao/unidades', **HTTPS).get_data(as_text=True)
    assert 'Enfermeira' in pagina and 'enfermeira@example.test' in pagina.lower()

    client.post(f'/sfa/notificacao/responsaveis/{vinculo.id}/revogar', **HTTPS)
    g.pop('_sfa_unidades_usuario', None)
    assert notificacao.unidades_do_usuario(pessoa) == []
    assert client.post(f'/sfa/notificacao/responsaveis/{vinculo.id}/revogar', **HTTPS).status_code == 404
    funcoes = [a.funcao for a in SfaAuditoria.query.filter_by(categoria='NOTIFICACAO_SINAN').order_by(SfaAuditoria.id)]
    assert funcoes == ['criar_unidade', 'conceder_responsavel', 'revogar_responsavel']


def test_unidade_recebe_varios_responsaveis_de_uma_vez(app, client, ubs):
    admin = conta('admin5@example.test', role='admin', name='Admin')
    ana, bia, caio = (conta(f'{n}@example.test', name=n.title()) for n in ('ana', 'bia', 'caio'))
    entrar(client, admin)
    url = f'/sfa/notificacao/unidades/{ubs.id}/responsaveis'

    def ativos():
        return sorted(v.user.name for v in SfaUnidadeResponsavel.query.filter_by(unidade_id=ubs.id, revogado_em=None))

    client.post(url, data={'email': 'ana@example.test'}, **HTTPS)
    varios = 'Bia@Example.test, ana@example.test;\ncaio@example.test  fantasma@example.test'
    resposta = client.post(url, data={'email': varios}, follow_redirects=True, **HTTPS)
    assert ativos() == ['Ana', 'Bia', 'Caio']
    pagina = BeautifulSoup(resposta.data, 'html.parser')
    avisos = ' | '.join(a.get_text(' ', strip=True) for a in pagina.select('.alert'))
    assert 'Bia e Caio agora respondem por UBS Teste.' in avisos and 'Ana já respondia por esta unidade.' in avisos
    assert 'Nenhuma conta no site com este e-mail: fantasma@example.test.' in avisos
    secao = pagina.select_one(f'#unidade-{ubs.id}').get_text(' ')
    assert '3 responsáveis' in secao and 'Adicionar mais responsáveis' in secao
    assert [u.id for u in notificacao.unidades_do_usuario(bia)] == [ubs.id]
    assert SfaAuditoria.query.filter_by(funcao='conceder_responsavel').count() == 3

    client.post(url, data={'email': '  '}, **HTTPS)
    client.post(url, data={'email': ' '.join(f'p{n}@example.test' for n in range(31))}, **HTTPS)
    assert ativos() == ['Ana', 'Bia', 'Caio']
    # A mesma pessoa também pode responder por outra unidade.
    outra = unidade('UBS Vizinha', '1111111')
    client.post(f'/sfa/notificacao/unidades/{outra.id}/responsaveis', data={'email': 'caio@example.test'}, **HTTPS)
    g.pop('_sfa_unidades_usuario', None)
    assert sorted(u.nome for u in notificacao.unidades_do_usuario(caio)) == ['UBS Teste', 'UBS Vizinha']


def test_unidade_desativada_suspende_o_acesso(app, client, ubs):
    admin = conta('admin2@example.test', role='admin')
    pessoa = responsavel(ubs, 'pessoa@example.test')
    entrar(client, admin)
    client.post(f'/sfa/notificacao/unidades/{ubs.id}', data={'nome': 'UBS Renomeada', 'cnes': ubs.cnes}, **HTTPS)
    assert (ubs.nome, ubs.ativa) == ('UBS Renomeada', False)
    entrar(client, pessoa)
    assert client.get('/sfa/notificacao', **HTTPS).status_code == 404


def test_responsavel_acessa_so_a_propria_area(client, restrito, autora):
    home = BeautifulSoup(client.get('/', **HTTPS).data, 'html.parser')
    links = [a['href'] for a in home.select('[data-dashboard-area="sinan"] a')]
    assert [h.rsplit('/sfa/', 1)[-1] for h in links] == ['notificacao/ficha', 'notificacao', 'notificacao/panorama']

    pagina = client.get('/sfa/notificacao', **HTTPS)
    assert pagina.status_code == 200 and pagina.headers['Cache-Control'] == 'private, no-store'
    sidebar = BeautifulSoup(pagina.data, 'html.parser').select_one('.sfa-sidebar').get_text(' ')
    assert 'Fichas da unidade' in sidebar and 'Panorama das unidades' in sidebar
    for ausente in ('Pacientes', 'Sync SINAN', 'Dados entomológicos', 'Unidades e responsáveis'):
        assert ausente not in sidebar
    assert client.get('/sfa/notificacao/panorama', **HTTPS).status_code == 200
    assert client.get('/sfa/notificacao/ficha', **HTTPS).status_code == 200
    for rota in ('/sfa/', '/sfa/pacientes', '/sfa/pre-t0', '/sfa/entomologia', '/sfa/notificacao/unidades'):
        assert client.get(rota, **HTTPS).status_code in (403, 404), rota
    assert client.post('/sfa/notificacao/unidades', data={'nome': 'Intrusa'}, **HTTPS).status_code in (403, 404)
    assert SfaUnidadeSaude.query.count() == 1 and db.session.get(User, autora.id).role == 'tutor'


def test_sem_conta_ou_sem_unidade_nao_entra(client, restrito, ubs):
    for rota in ('/sfa/notificacao', '/sfa/notificacao/ficha', '/sfa/notificacao/panorama', '/sfa/notificacao/unidades'):
        anonimo = client.get(rota, **HTTPS)
        assert anonimo.status_code == 302 and '/login' in anonimo.headers['Location'], rota
    entrar(client, conta('tutor@example.test'))
    for rota in ('/sfa/notificacao', '/sfa/notificacao/ficha', '/sfa/notificacao/panorama'):
        assert client.get(rota, **HTTPS).status_code in (403, 404), rota
    home = BeautifulSoup(client.get('/', **HTTPS).data, 'html.parser')
    assert not home.select('[data-dashboard-area="sinan"]')


# ---------------------------------------------------------------------------
# Conta da própria unidade: perfil "somente Notificação SINAN"
# ---------------------------------------------------------------------------

def conta_da_unidade(registro, email='ubs2@example.test', name='UBS 2'):
    user = responsavel(registro, email, name)
    user.worker = notificacao.PERFIL_SO_NOTIFICACAO
    db.session.commit()
    return user


def test_conta_da_unidade_so_ve_a_notificacao_e_registra_sem_escolher(client, restrito, ubs):
    unidade('UBS Vizinha', '1111111')
    ubs2 = conta_da_unidade(ubs)
    entrar(client, ubs2)

    inicio = client.get('/', **HTTPS)
    assert inicio.status_code == 302 and inicio.headers['Location'].endswith('/sfa/notificacao')
    for rota in ('/painel/user/', '/profile', '/sfa/', '/sfa/pacientes', '/sfa/entomologia'):
        bloqueada = client.get(rota, **HTTPS)
        assert bloqueada.status_code == 302 and bloqueada.headers['Location'].endswith('/sfa/notificacao'), rota
    assert client.get('/sfa/pacientes', headers={'Accept': 'application/json'}, **HTTPS).status_code == 404
    assert client.post('/profile', data={'name': 'Trocado'}, **HTTPS).status_code == 404
    assert client.get('/sfa/notificacao/unidades', **HTTPS).status_code == 404
    assert client.get('/change_password', **HTTPS).status_code == 200

    pagina = client.get('/sfa/notificacao', **HTTPS)
    assert pagina.status_code == 200
    sidebar = BeautifulSoup(pagina.data, 'html.parser').select_one('.sfa-sidebar')
    textos = sidebar.get_text(' ')
    assert 'Nova ficha' in textos and 'Fichas da unidade' in textos and 'Sair' in textos and 'Alterar senha' in textos
    assert 'Página inicial' not in textos and 'Pacientes' not in textos

    formulario = client.get('/sfa/notificacao/ficha', **HTTPS).get_data(as_text=True)
    assert 'name="ficha_sinan"' in formulario and 'value="UBS Teste"' in formulario
    log = registrar(client)
    assert (log.unidade_id, log.preenchido_por_id) == (ubs.id, ubs2.id)
    assert 'Maria Paciente' in client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    assert client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS).status_code == 200
    assert client.get(f'/sfa/notificacao/fichas/{log.id}/imprimir', **HTTPS).status_code == 200
    assert client.get('/sfa/notificacao/panorama', **HTTPS).status_code == 200

    saida = client.get('/logout', **HTTPS)
    assert saida.status_code == 302 and '/sfa/' not in saida.headers['Location']


def test_perfil_de_unidade_nao_restringe_admin_nem_outras_contas(client, restrito, ubs):
    admin = conta('admin6@example.test', role='admin')
    admin.worker = notificacao.PERFIL_SO_NOTIFICACAO
    db.session.commit()
    entrar(client, admin)
    assert client.get('/', **HTTPS).status_code == 200
    entrar(client, responsavel(ubs, 'enfermeira2@example.test'))
    assert client.get('/', **HTTPS).status_code == 200
    pagina = client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    assert 'Página inicial' in pagina and 'Alterar senha' not in pagina


def test_conta_master_ve_so_a_notificacao_de_todas_as_unidades(client, restrito, ubs, autora):
    vizinha = unidade('UBS Vizinha', '1111111')
    fechada = unidade('UBS Fechada', '2222222')
    fechada.ativa = False
    db.session.commit()
    da_ubs = registrar(client)
    carla = conta('carla@example.test', name='Carla')
    carla.worker = notificacao.PERFIL_MASTER_NOTIFICACAO
    db.session.commit()
    entrar(client, carla)

    inicio = client.get('/', **HTTPS)
    assert inicio.status_code == 302 and inicio.headers['Location'].endswith('/sfa/notificacao')
    for rota in ('/painel/user/', '/profile', '/sfa/', '/sfa/pacientes', '/sfa/entomologia', '/sfa/pre-t0'):
        bloqueada = client.get(rota, **HTTPS)
        assert bloqueada.status_code == 302 and bloqueada.headers['Location'].endswith('/sfa/notificacao'), rota
    assert client.get('/sfa/notificacao/unidades', **HTTPS).status_code == 404

    pagina = BeautifulSoup(client.get('/sfa/notificacao', **HTTPS).data, 'html.parser')
    sidebar = pagina.select_one('.sfa-sidebar').get_text(' ')
    assert 'Nova ficha' in sidebar and 'Fichas da unidade' in sidebar and 'Sair' in sidebar and 'Alterar senha' in sidebar
    assert 'Página inicial' not in sidebar and 'Pacientes' not in sidebar and 'Unidades e responsáveis' not in sidebar
    assert '2 unidades' in pagina.get_text() and 'Maria Paciente' in pagina.get_text()
    opcoes = [o.get_text() for o in pagina.select('#notif-unidade option')]
    assert opcoes == ['Todas', 'UBS Teste', 'UBS Vizinha']

    # A ficha de outra pessoa é vista e impressa; corrigir e excluir continuam com quem preencheu.
    assert client.get(f'/sfa/notificacao/fichas/{da_ubs.id}', **HTTPS).status_code == 200
    assert client.get(f'/sfa/notificacao/fichas/{da_ubs.id}/imprimir', **HTTPS).status_code == 200
    assert client.get(f'/sfa/notificacao/fichas/{da_ubs.id}/completar', **HTTPS).status_code == 404
    assert client.post(f'/sfa/notificacao/fichas/{da_ubs.id}/excluir', **HTTPS).status_code == 404

    escolha = client.get('/sfa/notificacao/ficha', **HTTPS).get_data(as_text=True)
    assert f'/sfa/notificacao/ficha?unidade={vizinha.id}' in escolha and f'?unidade={fechada.id}' not in escolha
    salva = client.post(f'/sfa/notificacao/ficha?unidade={vizinha.id}',
                        data=ficha_form(ficha_sinan='5550002', nome='Caso da Carla'), **HTTPS)
    assert salva.status_code == 302
    dela = SfaSinanLog.query.filter_by(ficha_sinan='5550002').one()
    assert (dela.unidade_id, dela.preenchido_por_id) == (vizinha.id, carla.id)
    assert client.get(f'/sfa/notificacao/fichas/{dela.id}/completar', **HTTPS).status_code == 200
    assert client.get('/sfa/notificacao/panorama', **HTTPS).status_code == 200
    assert [f['nome'] for f in notificacao.listar_fichas(carla)['fichas']] == ['Caso da Carla', 'Maria Paciente']

    # O perfil interno "Master" antigo não tem relação com a notificação e não restringe a conta.
    antiga = conta('master-antigo@example.test')
    antiga.worker = 'master'
    db.session.commit()
    entrar(client, antiga)
    assert client.get('/', **HTTPS).status_code == 200
    assert client.get('/sfa/notificacao', **HTTPS).status_code == 404


def test_conta_da_unidade_sem_unidade_ativa_ve_aviso(client, restrito, ubs):
    pessoa = conta('ubs9@example.test')
    pessoa.worker = notificacao.PERFIL_SO_NOTIFICACAO
    db.session.commit()
    entrar(client, pessoa)
    for rota in ('/', '/sfa/notificacao', '/sfa/notificacao/ficha'):
        aviso = client.get(rota, **HTTPS)
        assert aviso.status_code == 403 and 'ainda não está ligada a uma unidade' in aviso.get_data(as_text=True), rota
    assert client.get('/logout', **HTTPS).status_code == 302


def editar_conta(client, user, **campos):
    dados = {'name': user.name, 'email': user.email, 'new_password': '', 'role': user.role or 'adotante',
             'worker': user.worker or ''}
    dados.update(campos)
    return client.post(f'/painel/user/edit/?id={user.id}', data=dados, **HTTPS)


def test_painel_de_usuarios_deixa_a_conta_so_com_a_propria_unidade(client, ubs):
    ubs2 = unidade('UBS 2', '2222222')
    ubs2_conta = responsavel(ubs, 'ubs2@example.test', 'UBS 2')
    notificacao.conceder(ubs2, ubs2_conta, 'Admin')  # indicada por engano nas duas unidades
    db.session.commit()
    admin = conta('admin7@example.test', role='admin', name='Admin')
    entrar(client, admin)

    tela = BeautifulSoup(client.get(f'/painel/user/edit/?id={ubs2_conta.id}', **HTTPS).data, 'html.parser')
    opcoes = {o['value']: o.get_text() for o in tela.select('select[name="unidade_sinan"] option')}
    assert opcoes == {'': 'Nenhuma', str(ubs.id): 'UBS Teste', str(ubs2.id): 'UBS 2'}
    assert 'responde por 2 unidades' in tela.get_text()
    perfis = [o['value'] for o in tela.select('select[name="worker"] option')]
    assert notificacao.PERFIL_SO_NOTIFICACAO in perfis

    # Perfil de unidade exige a unidade; nada muda enquanto ela não é escolhida.
    sem_unidade = editar_conta(client, ubs2_conta, worker=notificacao.PERFIL_SO_NOTIFICACAO, unidade_sinan='')
    assert sem_unidade.status_code == 200 and 'Escolha a unidade desta conta' in sem_unidade.get_data(as_text=True)
    db.session.refresh(ubs2_conta)
    assert ubs2_conta.worker is None and len(notificacao.vinculos_ativos(ubs2_conta)) == 2

    salvo = editar_conta(client, ubs2_conta, worker=notificacao.PERFIL_SO_NOTIFICACAO, unidade_sinan=str(ubs2.id))
    assert salvo.status_code == 302
    db.session.refresh(ubs2_conta)
    assert ubs2_conta.worker == notificacao.PERFIL_SO_NOTIFICACAO and ubs2_conta.role == 'tutor'
    assert [v.unidade_id for v in notificacao.vinculos_ativos(ubs2_conta)] == [ubs2.id]
    revogado = SfaUnidadeResponsavel.query.filter_by(user_id=ubs2_conta.id, unidade_id=ubs.id).one()
    assert revogado.revogado_por == 'Admin'
    auditoria = SfaAuditoria.query.filter_by(funcao='revogar_responsavel').one()
    assert json.loads(auditoria.detalhes_json)['origem'] == 'painel_usuarios'

    tela = BeautifulSoup(client.get(f'/painel/user/edit/?id={ubs2_conta.id}', **HTTPS).data, 'html.parser')
    assert tela.select_one('select[name="unidade_sinan"] option[selected]')['value'] == str(ubs2.id)
    # Outra tela que grava o usuário sem o campo não mexe nos vínculos.
    assert editar_conta(client, ubs2_conta, name='UBS Dois').status_code == 302
    assert [v.unidade_id for v in notificacao.vinculos_ativos(ubs2_conta)] == [ubs2.id]
    unidades = client.get('/sfa/notificacao/unidades', **HTTPS).get_data(as_text=True)
    assert 'só SINAN' in unidades and f'/painel/user/edit/?id={ubs2_conta.id}' in unidades

    entrar(client, ubs2_conta)
    formulario = client.get('/sfa/notificacao/ficha', **HTTPS).get_data(as_text=True)
    assert 'name="ficha_sinan"' in formulario and 'value="UBS 2"' in formulario
    assert 'Por qual unidade' not in formulario


def test_painel_de_usuarios_torna_a_conta_master_sem_escolher_unidade(client, ubs):
    entrar(client, conta('admin10@example.test', role='admin', name='Admin'))
    carla = conta('carla2@example.test', name='Carla')
    tela = BeautifulSoup(client.get(f'/painel/user/edit/?id={carla.id}', **HTTPS).data, 'html.parser')
    assert notificacao.PERFIL_MASTER_NOTIFICACAO in [o['value'] for o in tela.select('select[name="worker"] option')]

    # Administrador continua vendo o site inteiro: o painel avisa em vez de gravar um perfil sem efeito.
    recusada = editar_conta(client, carla, worker=notificacao.PERFIL_MASTER_NOTIFICACAO, role='admin', unidade_sinan='')
    assert recusada.status_code == 200 and 'O administrador continua vendo o site inteiro' in recusada.get_data(as_text=True)
    db.session.refresh(carla)
    assert (carla.worker, carla.role) == (None, 'tutor')

    salvo = editar_conta(client, carla, worker=notificacao.PERFIL_MASTER_NOTIFICACAO, unidade_sinan='')
    assert salvo.status_code == 302
    db.session.refresh(carla)
    assert carla.worker == notificacao.PERFIL_MASTER_NOTIFICACAO and notificacao.vinculos_ativos(carla) == []
    assert notificacao.conta_so_notificacao(carla) and notificacao.pode_acessar(carla)
    assert [u.id for u in notificacao.unidades_para_registrar(carla)] == [ubs.id]


def test_painel_de_usuarios_troca_soma_ou_retira_unidade_das_demais_contas(client, ubs):
    vizinha = unidade('UBS Vizinha', '1111111')
    terceira = unidade('UBS Três', '3333333')
    entrar(client, conta('admin8@example.test', role='admin', name='Admin'))

    # Uma unidade só aparece no campo: escolher outra troca a unidade; esvaziar retira o acesso.
    enfermeira = responsavel(ubs, 'enfermeira3@example.test', 'Enfermeira')
    assert editar_conta(client, enfermeira, unidade_sinan=str(vizinha.id)).status_code == 302
    assert [v.unidade_id for v in notificacao.vinculos_ativos(enfermeira)] == [vizinha.id]
    assert db.session.get(User, enfermeira.id).worker is None
    assert editar_conta(client, enfermeira, unidade_sinan='').status_code == 302
    assert notificacao.vinculos_ativos(enfermeira) == []

    # Várias unidades (campo em branco): fora do perfil de unidade, a escolhida é somada.
    coordenadora = responsavel(ubs, 'coordenadora@example.test', 'Coordenadora')
    notificacao.conceder(vizinha, coordenadora, 'Admin')
    db.session.commit()
    assert editar_conta(client, coordenadora, unidade_sinan='').status_code == 302
    assert len(notificacao.vinculos_ativos(coordenadora)) == 2
    assert editar_conta(client, coordenadora, unidade_sinan=str(terceira.id)).status_code == 302
    assert len(notificacao.vinculos_ativos(coordenadora)) == 3

    vizinha.ativa = False
    db.session.commit()
    desativada = client.post('/painel/user/new/', data={'name': 'UBS 5', 'email': 'ubs5@example.test', 'new_password': 'senha-123',
                                                        'role': 'adotante', 'worker': notificacao.PERFIL_SO_NOTIFICACAO,
                                                        'unidade_sinan': str(vizinha.id)}, **HTTPS)
    assert desativada.status_code == 200 and 'UBS Vizinha está desativada' in desativada.get_data(as_text=True)
    assert User.query.filter_by(email='ubs5@example.test').first() is None
    nova = client.post('/painel/user/new/', data={'name': 'UBS 5', 'email': 'ubs5@example.test', 'new_password': 'senha-123',
                                                  'role': 'adotante', 'worker': notificacao.PERFIL_SO_NOTIFICACAO,
                                                  'unidade_sinan': str(terceira.id)}, **HTTPS)
    assert nova.status_code == 302
    criada = User.query.filter_by(email='ubs5@example.test').one()
    assert [v.unidade_id for v in notificacao.vinculos_ativos(criada)] == [terceira.id]


def test_ficha_enviada_pelo_navegador_passa_no_csrf_em_https(app, client, ubs, autora):
    """Em produção a ficha voltava em branco: o CSRF em HTTPS exige o Referer e a página mandava não enviá-lo."""
    app.config['WTF_CSRF_ENABLED'] = True
    pagina = client.get('/sfa/notificacao/ficha', **HTTPS)
    assert pagina.headers['Referrer-Policy'] == 'same-origin'
    tela = BeautifulSoup(pagina.data, 'html.parser')
    assert tela.select_one('meta[name="referrer"]')['content'] == 'same-origin'
    token = tela.select_one('input[name="csrf_token"]')['value']
    for rota in ('/sfa/notificacao', '/sfa/notificacao/panorama'):
        assert client.get(rota, **HTTPS).headers['Referrer-Policy'] == 'same-origin', rota

    # Sem a origem (o que no-referrer fazia o navegador mandar), o envio é recusado e nada é gravado.
    navegador = {'Accept': 'text/html'}
    recusada = client.post('/sfa/notificacao/ficha', data={**ficha_form(), 'csrf_token': token},
                           headers=navegador, **HTTPS)
    assert recusada.status_code == 303 and SfaSinanLog.query.count() == 0
    # Com same-origin o navegador manda o endereço do próprio site, e a ficha é gravada.
    aceita = client.post('/sfa/notificacao/ficha', data={**ficha_form(), 'csrf_token': token},
                         headers={**navegador, 'Referer': 'https://localhost/sfa/notificacao/ficha'}, **HTTPS)
    assert aceita.status_code == 302 and '/sfa/notificacao/fichas/' in aceita.headers['Location']
    assert SfaSinanLog.query.one().unidade_id == ubs.id


# ---------------------------------------------------------------------------
# Registrar e consultar fichas
# ---------------------------------------------------------------------------

def test_ficha_fica_com_autor_e_unidade_fixa(client, ubs, autora):
    formulario = client.get('/sfa/notificacao/ficha', **HTTPS).get_data(as_text=True)
    assert 'value="UBS Teste"' in formulario and 'value="7654321"' in formulario and 'value="Ana Autora"' in formulario
    assert 'NOTIFICAÇÃO SINAN · UBS TESTE' in formulario

    log = registrar(client, unidade_notificante='Outra unidade', codigo_unidade_notificante='1111111')
    assert (log.unidade_id, log.preenchido_por_id, log.unidade_notificante, log.agravo) == (ubs.id, autora.id, 'UBS Teste', 'DENGUE')
    payload = json.loads(log.dados_json)
    assert payload[FULL_KEY]['respostas']['unidade_notificante'] == {'valor': 'UBS Teste', 'codigo': '7654321'}
    assert payload['unidade_notificante'] == 'UBS Teste'
    paciente = SfaPaciente.query.one()
    assert (paciente.nome, paciente.status_t0, log.id_estudo_vinculado) == ('Maria Paciente', 'SINAN_Aguardando_T0', paciente.id_estudo)

    repetida = client.post('/sfa/notificacao/ficha', data=ficha_form(nome='Outro Nome'), **HTTPS)
    assert repetida.status_code == 302 and repetida.headers['Location'].endswith(f'/sfa/notificacao/fichas/{log.id}')
    assert SfaSinanLog.query.count() == 1 and SfaPaciente.query.one().nome == 'Maria Paciente'
    assert client.get(f'/sfa/notificacao/fichas/{log.id}/imprimir', **HTTPS).status_code == 200


def test_colega_da_unidade_ve_e_so_o_autor_completa(client, ubs, autora):
    log = registrar(client)
    colega = responsavel(ubs, 'colega@example.test', 'Carla Colega')
    de_fora = responsavel(unidade('UBS Vizinha', '1111111'), 'fora@example.test', 'Fábio de Fora')

    entrar(client, colega)
    assert 'Maria Paciente' in client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    ficha = client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS)
    assert ficha.status_code == 200 and 'Ana Autora' in ficha.get_data(as_text=True)
    for acao in ('Completar ficha', 'Editar ficha', 'Excluir ficha'):
        assert acao not in ficha.get_data(as_text=True)
    assert client.get(f'/sfa/notificacao/fichas/{log.id}/completar', **HTTPS).status_code == 404
    assert client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=ficha_form(nome='Trocado'), **HTTPS).status_code == 404
    assert client.post(f'/sfa/notificacao/fichas/{log.id}/excluir', **HTTPS).status_code == 404

    entrar(client, de_fora)
    assert 'Maria Paciente' not in client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    for rota in ('', '/completar', '/imprimir'):
        assert client.get(f'/sfa/notificacao/fichas/{log.id}{rota}', **HTTPS).status_code == 404
    assert client.get(f'/sfa/notificacao?unidade={ubs.id}', **HTTPS).status_code == 404
    assert client.get(f'/sfa/notificacao/ficha?unidade={ubs.id}', **HTTPS).status_code == 404
    mesma = client.post('/sfa/notificacao/ficha', data=ficha_form(nome='Homônimo'), **HTTPS)
    assert mesma.status_code == 200
    corpo = mesma.get_data(as_text=True)
    assert 'Já existe uma ficha registrada com esse número' in corpo and 'Maria Paciente' not in corpo
    assert SfaSinanLog.query.count() == 1 and SfaPaciente.query.one().nome == 'Maria Paciente'


def test_autor_completa_depois_e_o_que_falta_some(client, ubs, autora):
    # NS1 com data já exige o resultado no envio; o RT-PCR pode ficar aguardando o laboratório.
    log = registrar(client, rt_pcr_data='2026-10-11')
    detalhe = client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS).get_data(as_text=True)
    assert 'O que ainda falta nesta ficha' in detalhe and 'aguardando resultado' in detalhe
    assert f'/sfa/notificacao/fichas/{log.id}/completar?campo=classificacao' in detalhe
    lista = client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    assert '1 ficha ainda tem campos a completar' in lista and 'Exames · 1' in lista

    edicao = BeautifulSoup(client.get(f'/sfa/notificacao/fichas/{log.id}/completar?campo=classificacao', **HTTPS).data, 'html.parser')
    assert edicao.select_one('#input-nome')['value'] == 'Maria Paciente'
    assert edicao.select_one('#input-rt_pcr_data')['value'] == '2026-10-11'
    assert edicao.select_one('#input-ficha_sinan').has_attr('readonly')
    assert edicao.select_one('form[data-step-form]')['data-focus-field'] == 'classificacao'
    assert edicao.select_one('[data-ir-para="rt_pcr_resultado"]') and edicao.select_one('#campo-classificacao.is-pending')
    assert not edicao.select_one('#campo-nome.is-pending')

    completa = ficha_form(ficha_sinan='9999999', nome='Maria Paciente Corrigida', rt_pcr_data='2026-10-11',
                          rt_pcr_resultado='2', ns1_data_coleta='2026-10-11', ns1_resultado='1',
                          unidade_notificante='Trocada', **COMPLETA)
    salva = client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=completa, **HTTPS)
    assert salva.status_code == 302
    db.session.refresh(log)
    payload = json.loads(log.dados_json)[FULL_KEY]
    assert payload['respostas']['ficha_sinan'] == '2985999' and log.ficha_sinan == '2985999'
    assert payload['respostas']['unidade_notificante']['valor'] == 'UBS Teste'
    assert payload['respostas']['classificacao'] == '10' and log.nome == 'Maria Paciente Corrigida'
    revisao = payload['revisoes'][0]
    assert revisao['por'] == autora.id and 'classificacao' in revisao['campos'] and 'ficha_sinan' not in revisao['campos']
    assert revisao['antes']['nome'] == 'Maria Paciente'
    assert SfaPaciente.query.one().nome == 'Maria Paciente Corrigida'
    assert json.loads(log.dados_json)['ns1_resultado'] == 'Positivo'
    assert SfaAuditoria.query.filter_by(funcao='atualizar_ficha_pre_t0').count() == 1

    detalhe = client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS).get_data(as_text=True)
    assert 'O que ainda falta' not in detalhe and 'Alterações depois do envio' in detalhe and 'Editar ficha' in detalhe
    lista = client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    assert 'campos a completar' not in lista and 'Completa' in lista
    assert 'Nenhuma ficha com esse filtro' in client.get('/sfa/notificacao?pendentes=1', **HTTPS).get_data(as_text=True)

    # Salvar de novo sem mudar nada não cria outra revisão.
    client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=completa, **HTTPS)
    db.session.refresh(log)
    assert len(json.loads(log.dados_json)[FULL_KEY]['revisoes']) == 1


def test_ficha_sem_numero_e_registrada_e_recebe_o_numero_depois(client, ubs, autora):
    log = registrar(client, ficha_sinan='')
    outra = registrar(client, ficha_sinan='', nome='Outra Paciente')
    # Sem número, cada ficha é um caso próprio: nada se junta por engano.
    assert log.id != outra.id and log.id_estudo_vinculado != outra.id_estudo_vinculado
    assert log.ficha_sinan == '' and log.chave_dedup.startswith('DIGITAL-') and log.chave_dedup != outra.chave_dedup
    assert SfaPaciente.query.count() == 2
    detalhe = client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS).get_data(as_text=True)
    assert 'Ficha sem número' in detalhe and f'/sfa/notificacao/fichas/{log.id}/completar?campo=ficha_sinan' in detalhe
    assert 'sem número' in client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)

    edicao = BeautifulSoup(client.get(f'/sfa/notificacao/fichas/{log.id}/completar?campo=ficha_sinan', **HTTPS).data,
                           'html.parser')
    assert not edicao.select_one('#input-ficha_sinan').has_attr('readonly')
    assert edicao.select_one('#campo-ficha_sinan.is-pending')
    salva = client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=ficha_form(ficha_sinan='2985-999'), **HTTPS)
    assert salva.status_code == 302
    db.session.refresh(log)
    payload = json.loads(log.dados_json)
    assert (log.ficha_sinan, log.chave_dedup, payload[FULL_KEY]['respostas']['ficha_sinan']) == (
        '2985999', 'FICHA-2985999', '2985999')
    assert payload['numero_controle'] == '2985999' and 'ficha_sinan' in payload[FULL_KEY]['revisoes'][0]['campos']
    assert SfaPaciente.query.filter_by(id_estudo=log.id_estudo_vinculado).one().ficha_sinan == '2985999'
    # Depois de informado, o número não muda mais.
    edicao = BeautifulSoup(client.get(f'/sfa/notificacao/fichas/{log.id}/completar', **HTTPS).data, 'html.parser')
    assert edicao.select_one('#input-ficha_sinan').has_attr('readonly')
    client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=ficha_form(ficha_sinan='5550001'), **HTTPS)
    db.session.refresh(log)
    assert log.ficha_sinan == '2985999'

    # O número de outra ficha não é aceito, e a ficha continua como estava.
    recusada = client.post(f'/sfa/notificacao/fichas/{outra.id}/completar', data=ficha_form(ficha_sinan='2985999'), **HTTPS)
    assert recusada.status_code == 200 and 'Já existe uma ficha registrada com esse número' in recusada.get_data(as_text=True)
    assert BeautifulSoup(recusada.data, 'html.parser').select_one('form[data-step-form]')['data-error-field'] == 'ficha_sinan'
    db.session.refresh(outra)
    assert outra.ficha_sinan == '' and outra.chave_dedup.startswith('DIGITAL-')
    # Registrar de novo o número já informado leva à ficha existente, como antes.
    repetida = client.post('/sfa/notificacao/ficha', data=ficha_form(ficha_sinan='2985999'), **HTTPS)
    assert repetida.headers['Location'].endswith(f'/sfa/notificacao/fichas/{log.id}') and SfaSinanLog.query.count() == 2


def test_numero_informado_depois_nao_junta_a_ficha_com_a_planilha(client, ubs, autora):
    log = registrar(client, ficha_sinan='')
    db.session.add(SfaSinanLog(chave_dedup='FICHA-7000001', ficha_sinan='7000001', nome='Nome da Planilha'))
    db.session.add(SfaPaciente(id_estudo='SFA-701', ficha_sinan='7000002', nome='Caso da Planilha'))
    db.session.commit()
    for numero in ('7000001', '7000002'):
        resposta = client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=ficha_form(ficha_sinan=numero), **HTTPS)
        assert resposta.status_code == 200 and 'fale com a vigilância' in resposta.get_data(as_text=True), numero
    db.session.refresh(log)
    assert log.ficha_sinan == '' and SfaSinanLog.query.filter_by(ficha_sinan='7000001').one().nome == 'Nome da Planilha'


def test_autor_edita_e_exclui_a_ficha_com_o_caso_que_ela_criou(client, ubs, autora):
    log = registrar(client, **COMPLETA)
    log_id, id_estudo = log.id, log.id_estudo_vinculado
    lista = BeautifulSoup(client.get('/sfa/notificacao', **HTTPS).data, 'html.parser')
    assert lista.select_one(f'a[href$="/sfa/notificacao/fichas/{log_id}/completar"]').get_text() == 'Editar'
    detalhe = client.get(f'/sfa/notificacao/fichas/{log_id}', **HTTPS).get_data(as_text=True)
    assert 'Editar ficha' in detalhe and 'Excluir ficha' in detalhe

    excluida = client.post(f'/sfa/notificacao/fichas/{log_id}/excluir', **HTTPS)
    assert excluida.status_code == 302 and excluida.headers['Location'].endswith('/sfa/notificacao')
    assert db.session.get(SfaSinanLog, log_id) is None
    assert SfaPaciente.query.filter_by(id_estudo=id_estudo).first() is None
    auditoria = json.loads(SfaAuditoria.query.filter_by(funcao='excluir_ficha').one().detalhes_json)
    assert (auditoria['ficha_sinan'], auditoria['caso_removido'], auditoria['ator_autenticado']) == ('2985999', True, str(autora.id))
    assert 'Maria Paciente' not in client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    assert client.get(f'/sfa/notificacao/fichas/{log_id}', **HTTPS).status_code == 404
    # O mesmo número pode ser registrado de novo depois de excluído.
    assert registrar(client).ficha_sinan == '2985999'


def test_ficha_com_caso_em_acompanhamento_ou_da_planilha_nao_e_excluida(client, ubs, autora):
    log = registrar(client)
    paciente = SfaPaciente.query.one()
    paciente.status_whatsapp = 'ENVIADO'
    db.session.commit()
    detalhe = client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS).get_data(as_text=True)
    assert 'Excluir ficha' not in detalhe and 'já entrou no acompanhamento do estudo' in detalhe
    recusada = client.post(f'/sfa/notificacao/fichas/{log.id}/excluir', **HTTPS)
    assert recusada.status_code == 302 and recusada.headers['Location'].endswith(f'/sfa/notificacao/fichas/{log.id}')
    assert db.session.get(SfaSinanLog, log.id) is not None and SfaPaciente.query.count() == 1

    paciente.status_whatsapp = 'NAO_ENVIADO'
    log.n_caso = '17'
    db.session.commit()
    client.post(f'/sfa/notificacao/fichas/{log.id}/excluir', **HTTPS)
    assert db.session.get(SfaSinanLog, log.id) is not None
    assert 'veio da planilha do SINAN' in client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS).get_data(as_text=True)


def test_excluir_mantem_o_caso_que_nao_nasceu_da_ficha(app, client, ubs, autora):
    existente = SfaPaciente(id_estudo='SFA-9001', ficha_sinan='2985999', nome='Caso da Planilha')
    db.session.add(existente)
    db.session.commit()
    log = registrar(client)
    assert log.id_estudo_vinculado == 'SFA-9001'
    entrar(client, conta('admin9@example.test', role='admin'))
    assert client.post(f'/sfa/notificacao/fichas/{log.id}/excluir', **HTTPS).status_code == 302
    assert SfaSinanLog.query.count() == 0 and SfaPaciente.query.one().id_estudo == 'SFA-9001'


def test_correcao_nao_sobrescreve_o_que_a_equipe_ajustou_no_caso(client, ubs, autora):
    log = registrar(client, telefone='16991112222')
    paciente = SfaPaciente.query.one()
    paciente.nome = 'Nome Conferido pela Equipe'
    db.session.commit()
    client.post(f'/sfa/notificacao/fichas/{log.id}/completar',
                data=ficha_form(nome='Maria P. Corrigida', telefone='16993334444'), **HTTPS)
    db.session.refresh(paciente)
    assert paciente.nome == 'Nome Conferido pela Equipe' and paciente.telefone == '5516993334444'


def test_admin_registra_escolhendo_a_unidade_e_completa_qualquer_ficha(client, ubs, autora):
    log = registrar(client)
    outra = unidade('UBS Vizinha', '1111111')
    admin = conta('admin3@example.test', role='admin', name='Admin')
    entrar(client, admin)
    escolha = client.get('/sfa/notificacao/ficha', **HTTPS).get_data(as_text=True)
    assert f'/sfa/notificacao/ficha?unidade={outra.id}' in escolha and 'name="ficha_sinan"' not in escolha
    client.post(f'/sfa/notificacao/ficha?unidade={outra.id}', data=ficha_form(ficha_sinan='5550001', nome='Caso da Vizinha'), **HTTPS)
    do_admin = SfaSinanLog.query.filter_by(ficha_sinan='5550001').one()
    assert (do_admin.unidade_id, do_admin.preenchido_por_id) == (outra.id, admin.id)
    lista = client.get('/sfa/notificacao', **HTTPS).get_data(as_text=True)
    assert 'Maria Paciente' in lista and 'Caso da Vizinha' in lista
    assert client.get(f'/sfa/notificacao/fichas/{log.id}/completar', **HTTPS).status_code == 200


def test_numero_que_ja_esta_na_planilha_nao_revela_o_que_veio_de_la(client, ubs, autora):
    db.session.add(SfaPaciente(id_estudo='SFA-700', ficha_sinan='7000001', nome='Nome da Planilha', grupo='A'))
    db.session.add(SfaSinanLog(chave_dedup='FICHA-7000001', ficha_sinan='7000001', nome='Nome da Planilha',
                               data_notificacao='01/09/2026', unidade_notificante='Hospital',
                               id_estudo_vinculado='SFA-700'))
    db.session.commit()
    log = registrar(client, ficha_sinan='7000001', nome='Nome Digitado')
    assert (SfaSinanLog.query.count(), log.unidade_id, log.nome) == (1, ubs.id, 'Nome da Planilha')
    for rota in ('/sfa/notificacao', f'/sfa/notificacao/fichas/{log.id}', f'/sfa/notificacao/fichas/{log.id}/completar'):
        pagina = client.get(rota, **HTTPS).get_data(as_text=True)
        assert 'Nome Digitado' in pagina and 'Nome da Planilha' not in pagina and '01/09/2026' not in pagina, rota

    # A busca também só enxerga o que a unidade digitou, sem acento nem maiúscula.
    registrar(client, ficha_sinan='7000002', nome='José Antônio')

    def achados(busca):
        return notificacao.listar_fichas(autora, busca=busca)['fichas']

    assert [f['nome'] for f in achados('jose antonio')] == ['José Antônio']
    assert [f['ficha_sinan'] for f in achados('7000001')] == ['7000001']
    assert achados('planilha') == [] and len(achados('')) == 2


def test_formulario_reabre_com_erro_no_campo(client, ubs, autora):
    resposta = client.post('/sfa/notificacao/ficha', data=ficha_form(cep='14620-abc'), **HTTPS)
    assert resposta.status_code == 200 and SfaSinanLog.query.count() == 0
    form = BeautifulSoup(resposta.data, 'html.parser').select_one('form[data-step-form]')
    assert form['data-error-field'] == 'cep' and form['action'].endswith(f'/sfa/notificacao/ficha?unidade={ubs.id}')


def test_ficha_sem_campo_obrigatorio_nao_e_registrada_e_volta_no_campo(client, ubs, autora):
    for extra, campo in (({'nome_mae': ''}, 'nome_mae'), ({'numero_residencia': ''}, 'numero_residencia'),
                         ({'sinais_clinicos__febre': ''}, 'sinais_clinicos__febre'),
                         ({'ns1_data_coleta': '2026-10-11'}, 'ns1_resultado')):
        resposta = client.post('/sfa/notificacao/ficha', data=ficha_form(**extra), **HTTPS)
        assert resposta.status_code == 200, campo
        pagina = BeautifulSoup(resposta.data, 'html.parser')
        assert pagina.select_one('form[data-step-form]')['data-error-field'] == campo
        assert pagina.select_one('#input-nome')['value'] == 'Maria Paciente'
    assert SfaSinanLog.query.count() == 0 and SfaPaciente.query.count() == 0


def test_ficha_antiga_mostra_o_que_ficou_obrigatorio_e_salva_quando_completa(client, ubs, autora):
    from services.sfa_pre_t0 import salvar_ficha_pre_t0

    salvo = salvar_ficha_pre_t0(ficha_antiga(ficha_sinan='2985999', agravo='1', data_notificacao='2026-10-12',
                                             data_inicio_sintomas='2026-10-10', nome='Maria Paciente'),
                                autor_id=autora.id, unidade=ubs)
    log = db.session.get(SfaSinanLog, salvo['log_id'])
    detalhe = client.get(f'/sfa/notificacao/fichas/{log.id}', **HTTPS).get_data(as_text=True)
    assert f'/sfa/notificacao/fichas/{log.id}/completar?campo=nome_mae' in detalhe
    edicao = BeautifulSoup(client.get(f'/sfa/notificacao/fichas/{log.id}/completar', **HTTPS).data, 'html.parser')
    assert edicao.select_one('#campo-nome_mae.is-pending') and edicao.select_one('#campo-doencas_preexistentes.is-pending')
    # Como na ficha nova, as doenças pré-existentes já vêm marcadas como "Não".
    assert edicao.select_one('input[name="doencas_preexistentes__diabetes"][checked]')['value'] == '2'

    recusada = client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=ficha_form(nome_mae=''), **HTTPS)
    assert recusada.status_code == 200
    assert BeautifulSoup(recusada.data, 'html.parser').select_one('form[data-step-form]')['data-error-field'] == 'nome_mae'
    db.session.refresh(log)
    assert 'revisoes' not in json.loads(log.dados_json)[FULL_KEY]

    assert client.post(f'/sfa/notificacao/fichas/{log.id}/completar', data=ficha_form(), **HTTPS).status_code == 302
    db.session.refresh(log)
    gravadas = json.loads(log.dados_json)[FULL_KEY]['respostas']
    assert gravadas['nome_mae'] == 'Joana da Silva' and gravadas['numero_residencia'] == '100'
    pendentes = set(chaves(notificacao.pendencias(gravadas)))
    assert not pendentes & {'nome_mae', 'numero_residencia', 'ocupacao', 'sinais_clinicos', 'doencas_preexistentes'}


# ---------------------------------------------------------------------------
# O que ainda falta
# ---------------------------------------------------------------------------

def test_ficha_completa_nao_tem_pendencia(app):
    assert notificacao.pendencias(respostas(**COMPLETA)) == []
    assert notificacao.pendencias_por_grupo([]) == []


def test_pendencias_seguem_o_que_a_ficha_ja_diz(app):
    # Ficha gravada antes de a ficha exigir campos: tudo o que hoje é obrigatório aparece como pendente.
    minima = notificacao.pendencias(ficha_antiga(ficha_sinan='2985999', agravo='1', nome='Maria Paciente'))
    assert [g['chave'] for g in notificacao.pendencias_por_grupo(minima)] == ['notificacao', 'encerramento']
    assert [i['chave'] for i in minima if i['grupo'] == 'notificacao'] == [
        'data_nascimento', 'sexo', 'raca_cor', 'escolaridade', 'nome_mae', 'municipio_residencia', 'bairro',
        'logradouro', 'numero_residencia', 'telefone', 'zona', 'data_investigacao', 'ocupacao', 'sinais_clinicos',
        'doencas_preexistentes', 'hospitalizacao']
    assert {'classificacao', 'criterio_confirmacao', 'evolucao_caso', 'data_encerramento', 'caso_autoctone',
            'sinais_alarme', 'dengue_grave'} <= set(chaves(minima))
    assert 'data_internacao' not in chaves(minima) and 'gestante' not in chaves(minima)

    def falta(**extra):
        return notificacao.pendencias(ficha_antiga(**{**ficha_form(**COMPLETA), **extra}))

    assert falta() == []
    # A idade não substitui mais a data de nascimento; gestante só não se aplica ao sexo masculino.
    assert chaves(falta(data_nascimento='', idade_valor='36', idade_unidade='4')) == ['data_nascimento']
    # Sem o número da notificação, ele fica listado para ser informado depois.
    assert [(i['grupo'], i['chave'], i['numero']) for i in falta(ficha_sinan='')] == [('notificacao', 'ficha_sinan', 'Nº')]
    assert chaves(falta(sexo='F', gestante='')) == ['gestante'] == chaves(falta(sexo='I', gestante=''))
    assert falta(sexo='M', gestante='') == []
    assert chaves(falta(nome_mae='', numero_residencia='', telefone='', ocupacao='')) == [
        'nome_mae', 'numero_residencia', 'telefone', 'ocupacao']
    # Sinais clínicos e doenças pré-existentes: item sem resposta. O atalho leva ao item.
    assert falta(sinais_clinicos__febre='2', sinais_clinicos__mialgia='9') == []
    assert [(i['chave'], i['campo']) for i in falta(sinais_clinicos__mialgia='')] == [
        ('sinais_clinicos', 'sinais_clinicos__mialgia')]
    assert [(i['chave'], i['campo']) for i in falta(doencas_preexistentes__hepatopatias='')] == [
        ('doencas_preexistentes', 'doencas_preexistentes__hepatopatias')]
    # Exame: coleta espera resultado; resultado espera a data; "não realizado" não espera nada.
    aguardando = falta(rt_pcr_data='2026-10-11')
    assert [(i['grupo'], i['chave'], i['detalhe']) for i in aguardando] == [
        ('exames', 'rt_pcr_resultado', 'coleta em 11/10/2026, aguardando resultado')]
    assert chaves(falta(dengue_igm_resultado='1')) == ['dengue_igm_data']
    assert falta(dengue_igm_resultado='4') == [] and falta(rt_pcr_data='2026-10-11', rt_pcr_resultado='2') == []
    chik = falta(chikungunya_s1_data='2026-10-11')
    assert [(i['campo'], i['numero']) for i in chik] == [('prnt_resultado__res__s1', '38')]
    assert falta(chikungunya_s1_data='2026-10-11', prnt_resultado__res__s1='2') == []
    # Internação, óbito e gravidade só pedem detalhe quando aconteceram.
    assert chaves(falta(hospitalizacao='1')) == ['data_internacao', 'nome_hospital']
    assert chaves(falta(evolucao_caso='2')) == ['data_obito']
    # Sinais de alarme (68) e dengue grave (70): resposta sempre exigida; a data, no caso classificado assim.
    assert chaves(falta(sinais_alarme='', dengue_grave='')) == ['sinais_alarme', 'dengue_grave']
    assert falta(sinais_alarme='1') == []
    assert chaves(falta(classificacao='11', sinais_alarme='1')) == ['data_inicio_sinais_alarme']
    assert chaves(falta(classificacao='12', dengue_grave='2')) == []
    assert chaves(falta(classificacao='13')) == ['apresentacao_clinica']
    # Caso descartado encerra sem evolução; o caso autóctone (56) é sempre exigido.
    assert falta(classificacao='5', evolucao_caso='') == []
    assert chaves(falta(classificacao='5', caso_autoctone='')) == ['caso_autoctone']
    assert chaves(falta(classificacao='5', data_encerramento='')) == ['data_encerramento']


def test_respostas_voltam_ao_formulario_sem_perda(app):
    schema = carregar_esquema_pre_t0()
    original = coletar_respostas_pre_t0(MultiDict(ficha_form(
        **COMPLETA, idade_valor='36', idade_unidade='4', cep='14620000', codigo_logradouro='123',
        sinais_clinicos__febre='1', sinais_clinicos__mialgia='2', doencas_preexistentes__hepatopatias='9',
        prnt_resultado__res__s2='1', sinais_alarme='1', sinais_alarme__queda_plaquetas='1',
        dengue_grave='1', dengue_grave__melena='1', outros_orgaos_especificar='Rim',
        investigador__nome='Ana', observacoes_adicionais='Texto livre')), schema)
    assert coletar_respostas_pre_t0(MultiDict(respostas_para_formulario(original, schema)), schema) == original
    # Fichas antigas guardavam um só resultado para as amostras marcadas.
    antigo = {**original, 'prnt_resultado': {'amostras': ['s1'], 'resultado': '2', 'resultados': {}}}
    assert respostas_para_formulario(antigo, schema)['prnt_resultado__res__s1'] == '2'


# ---------------------------------------------------------------------------
# Panorama
# ---------------------------------------------------------------------------

def test_semana_epidemiologica():
    assert notificacao.semana_epidemiologica(date(2026, 10, 13)) == (2026, 41, date(2026, 10, 11))
    assert notificacao.semana_epidemiologica(date(2026, 1, 1)) == (2025, 53, date(2025, 12, 28))
    assert notificacao.semana_epidemiologica(date(2026, 1, 4)) == (2026, 1, date(2026, 1, 4))


def linha_da_planilha(chave, unidade_origem, dia, agravo='Dengue', nome='Pessoa da Planilha', ficha=''):
    db.session.add(SfaSinanLog(chave_dedup=chave, nome=nome, ficha_sinan=ficha, agravo=agravo,
                               unidade_notificante=unidade_origem, data_notificacao=dia.strftime('%d/%m/%Y')))


def test_panorama_conta_por_unidade_e_so_mostra_numeros(client, ubs, autora):
    hoje = hoje_local()
    inicio_semana = notificacao.semana_epidemiologica(hoje)[2]
    ubs.apelidos = 'Posto do Centro\nUBS T'
    vizinha = unidade('UBS Vizinha', '1111111')
    registrar(client, data_notificacao=hoje.isoformat())                      # ficha digital da própria unidade
    linha_da_planilha('N-001', ' posto do  CENTRO ', inicio_semana)           # outro nome da mesma unidade
    linha_da_planilha('N-002', '1111111', hoje, agravo='Febre de Chikungunya')  # CNES da vizinha
    linha_da_planilha('N-003', 'UBS Vizinha', inicio_semana - timedelta(days=10))
    linha_da_planilha('N-004', 'Clínica Particular', hoje)
    linha_da_planilha('N-005', 'UBS Vizinha', hoje, ficha='TESTE-1')          # registro de teste não conta
    linha_da_planilha('N-006', 'UBS Vizinha', date(hoje.year - 1, 1, 15))     # ano anterior
    db.session.add(SfaSinanLog(chave_dedup='N-007', nome='Sem Data', unidade_notificante='UBS Vizinha'))
    # Importado antes das colunas: agravo e unidade só nas variáveis estruturadas.
    db.session.add(SfaSinanLog(chave_dedup='N-008', nome='Antigo', data_notificacao=hoje.strftime('%d/%m/%Y'),
                               dados_json=json.dumps({'agravo': 'Dengue', 'unidade_notificante': 'ubs vizinha'})))
    db.session.commit()

    dados = notificacao.panorama(hoje, minhas=(ubs.id,), detalhar=True)
    por_nome = {linha['nome']: linha for linha in dados['linhas']}
    assert (por_nome['UBS Teste']['semana'], por_nome['UBS Teste']['ano'], por_nome['UBS Teste']['minha']) == (2, 2, True)
    assert (por_nome['UBS Vizinha']['semana'], por_nome['UBS Vizinha']['quatro'], por_nome['UBS Vizinha']['ano']) == (
        2, 3, 3 if (inicio_semana - timedelta(days=10)).year == hoje.year else 2)
    assert dados['sem_unidade'] == {'semana': 1, 'quatro': 1, 'ano': 1}
    assert dados['total']['semana'] == 5 and dados['sem_data'] == 1
    assert dados['nomes_sem_unidade'] == [('Clínica Particular', 1)]
    assert notificacao.panorama(hoje, agravo='Chikungunya')['total']['ano'] == 1
    assert notificacao.panorama(hoje)['nomes_sem_unidade'] == []

    pagina = client.get('/sfa/notificacao/panorama', **HTTPS).get_data(as_text=True)
    assert 'sua unidade' in pagina and 'UBS Vizinha' in pagina and 'Unidade não identificada' in pagina
    for restrito_ao_admin in ('Maria Paciente', 'Pessoa da Planilha', 'Clínica Particular', '2985999'):
        assert restrito_ao_admin not in pagina
    entrar(client, conta('admin4@example.test', role='admin'))
    assert 'Clínica Particular' in client.get('/sfa/notificacao/panorama', **HTTPS).get_data(as_text=True)
    assert vizinha.ativa


def test_sincronizacao_guarda_agravo_e_unidade_da_planilha(app, monkeypatch):
    def linha(**campos):
        row = [''] * 20
        for key, value in campos.items():
            row[sfa_service.COLS_SINAN[key]] = value
        return row

    rows = [['cabeçalho'] * 20, linha(NOME='Registro para validação', N='1', FICHA_SINAN='7000001')]

    class Sheets:
        def spreadsheets(self): return self
        def values(self): return self
        def get(self, **kwargs): return self
        def execute(self): return {'values': rows}

    monkeypatch.setattr(sfa_service, 'SHEET_ID_SINAN', 'sheet-test')
    monkeypatch.setattr(sfa_service, '_get_sheets_service', lambda: Sheets())
    monkeypatch.setattr(sfa_service, '_resolve_sinan_sheet_target', lambda unused: ('sheet-test', 'A:T'))
    assert sfa_service.sincronizar_sinan()['novos'] == 1
    log = SfaSinanLog.query.one()
    assert (log.agravo, log.unidade_notificante) == (None, None)

    # Linha importada antes das colunas é completada na sincronização seguinte, uma vez só.
    rows[1][sfa_service.COLS_SINAN['AGRAVO']] = 'Dengue'
    rows[1][sfa_service.COLS_SINAN['UNIDADE_NOTIFICANTE']] = 'UBS  I'
    rows.append(linha(NOME='Segundo registro', N='2', FICHA_SINAN='7000002', AGRAVO='Chikungunya', UNIDADE_NOTIFICANTE='Hospital'))
    resultado = sfa_service.sincronizar_sinan()
    assert (resultado['novos'], resultado['atualizados']) == (1, 1)
    db.session.refresh(log)
    assert (log.agravo, log.unidade_notificante) == ('Dengue', 'UBS I')
    novo = SfaSinanLog.query.filter_by(ficha_sinan='7000002').one()
    assert (novo.agravo, novo.unidade_notificante) == ('Chikungunya', 'Hospital')
    assert sfa_service.sincronizar_sinan()['atualizados'] == 0
