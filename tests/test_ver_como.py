"""Ver como: o administrador vê o site como outra conta, só lendo (services.ver_como)."""
import json
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup
from flask import g

from extensions import db
from models import User
from models.sfa import SfaAuditoria, SfaSinanLog
from services import sfa_notificacao as notificacao
from services.ver_como import CHAVE_SESSAO
from time_utils import utcnow

HTTPS = {'base_url': 'https://localhost'}
NAVEGADOR = {'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}


def conta(email, role='tutor', name='Pessoa', worker=None):
    user = User(name=name, email=email, password_hash='x', role=role, worker=worker)
    db.session.add(user)
    db.session.commit()
    return user


def nova_requisicao():
    # O contexto do app de teste é compartilhado entre requisições.
    for chave in ('_login_user', 'ver_como', '_entomologia_membro', '_sfa_unidades_usuario', 'user_experience'):
        g.pop(chave, None)


def entrar(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    nova_requisicao()


def get(client, rota, **kwargs):
    nova_requisicao()
    return client.get(rota, **HTTPS, **kwargs)


def post(client, rota, **kwargs):
    nova_requisicao()
    return client.post(rota, **HTTPS, **kwargs)


@pytest.fixture()
def restrito(app, monkeypatch):
    app.config['TESTING'] = False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS', '0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN', raising=False)
    return app


@pytest.fixture()
def cenario(app):
    from models.sfa import SfaUnidadeSaude
    unidade = SfaUnidadeSaude(nome='UBS Teste', cnes='7654321', criado_por='Teste')
    db.session.add(unidade)
    db.session.commit()
    admin = conta('admin-ver@example.test', role='admin', name='Admin')
    carla = conta('carla-ver@example.test', name='Carla', worker=notificacao.PERFIL_MASTER_NOTIFICACAO)
    return {'unidade': unidade, 'admin': admin, 'carla': carla}


def auditorias(funcao):
    return [json.loads(a.detalhes_json) for a in SfaAuditoria.query.filter_by(categoria='VER_COMO', funcao=funcao)]


def test_admin_ve_como_a_conta_so_lendo_e_volta(client, restrito, cenario):
    admin, carla, unidade = cenario['admin'], cenario['carla'], cenario['unidade']
    entrar(client, admin)
    lista = get(client, '/painel/user/').get_data(as_text=True)
    assert f'/ver-como/{carla.id}' in lista

    confirmar = get(client, f'/ver-como/{carla.id}')
    assert confirmar.status_code == 200 and 'Começar' in confirmar.get_data(as_text=True)
    with client.session_transaction() as session:
        assert CHAVE_SESSAO not in session  # abrir a confirmação não liga nada
    comecou = post(client, f'/ver-como/{carla.id}')
    assert comecou.status_code == 302
    assert auditorias('ver_como_iniciar') == [{'admin_id': admin.id, 'alvo_id': carla.id}]

    # Carla só usa a Notificação SINAN: o administrador vê exatamente isso, com a faixa de aviso.
    inicio = get(client, '/')
    assert inicio.status_code == 302 and inicio.headers['Location'].endswith('/sfa/notificacao')
    pagina = BeautifulSoup(get(client, '/sfa/notificacao').data, 'html.parser')
    faixa = pagina.select_one('[data-ver-como]')
    assert faixa is not None and 'Vendo como Carla' in faixa.get_text() and 'somente leitura' in faixa.get_text()
    assert faixa.select_one('a')['href'].endswith('/ver-como/sair')
    sidebar = pagina.select_one('.sfa-sidebar').get_text(' ')
    assert 'Alterar senha' in sidebar and 'Unidades e responsáveis' not in sidebar
    painel = get(client, '/painel/user/')
    assert painel.status_code == 302 and painel.headers['Location'].endswith('/sfa/notificacao')

    # Nada é gravado em nome dela.
    ficha = {'ficha_sinan': '2985999', 'agravo': '1', 'data_notificacao': '2026-10-12',
             'data_inicio_sintomas': '2026-10-10', 'nome': 'Maria Paciente'}
    recusado = post(client, f'/sfa/notificacao/ficha?unidade={unidade.id}', data=ficha, headers=NAVEGADOR)
    assert recusado.status_code == 303 and SfaSinanLog.query.count() == 0
    with client.session_transaction() as session:
        assert 'somente leitura' in str(session.get('_flashes'))
    api = post(client, f'/sfa/notificacao/ficha?unidade={unidade.id}', data=ficha,
               headers={'Accept': 'application/json'})
    assert api.status_code == 403 and api.get_json()['message'].startswith('Modo Ver como')
    assert SfaSinanLog.query.count() == 0
    assert post(client, '/change_password', data={'current_password': 'x', 'new_password': 'y'},
                headers=NAVEGADOR).status_code == 303

    # "Sair" na conta vista devolve o administrador à própria conta, sem deslogar.
    sair = get(client, '/logout')
    assert sair.status_code == 302 and sair.headers['Location'].endswith('/ver-como/sair')
    voltou = get(client, '/ver-como/sair')
    assert voltou.status_code == 302 and voltou.headers['Location'].endswith('/painel/user/')
    assert auditorias('ver_como_encerrar') == [{'admin_id': admin.id, 'alvo_id': carla.id}]
    with client.session_transaction() as session:
        assert CHAVE_SESSAO not in session and session['_user_id'] == str(admin.id)
    de_volta = get(client, '/painel/user/')
    assert de_volta.status_code == 200 and 'data-ver-como' not in de_volta.get_data(as_text=True)


def test_ver_como_so_para_admin_nunca_sobre_outro_admin_e_com_prazo(client, cenario):
    admin, carla = cenario['admin'], cenario['carla']
    outro_admin = conta('admin-dois@example.test', role='admin', name='Outro Admin')
    entrar(client, admin)

    recusado = post(client, f'/ver-como/{outro_admin.id}')
    assert recusado.status_code == 200 and 'outro administrador' in recusado.get_data(as_text=True)
    assert 'Começar' not in recusado.get_data(as_text=True)
    assert get(client, f'/ver-como/{admin.id}').get_data(as_text=True).count('Esta já é a sua conta') == 1
    assert get(client, '/ver-como/999999').status_code == 404
    with client.session_transaction() as session:
        assert CHAVE_SESSAO not in session

    post(client, f'/ver-como/{carla.id}')
    assert 'data-ver-como' in get(client, '/sfa/notificacao').get_data(as_text=True)
    with client.session_transaction() as session:
        session[CHAVE_SESSAO]['ate'] = (utcnow() - timedelta(seconds=1)).isoformat()
        session.modified = True
    # Prazo vencido: a pessoa volta a ser o administrador, sem faixa.
    perfil = get(client, '/painel/user/')
    assert perfil.status_code == 200 and 'data-ver-como' not in perfil.get_data(as_text=True)
    with client.session_transaction() as session:
        assert CHAVE_SESSAO not in session

    # Conta comum não usa o Ver como, nem com a sessão montada à mão.
    tutor = conta('tutor-ver@example.test', name='Tutor')
    entrar(client, tutor)
    assert get(client, f'/ver-como/{carla.id}').status_code == 404
    assert post(client, f'/ver-como/{carla.id}').status_code == 404
    with client.session_transaction() as session:
        session[CHAVE_SESSAO] = {'admin_id': tutor.id, 'alvo_id': carla.id,
                                 'ate': (utcnow() + timedelta(minutes=5)).isoformat()}
    pagina = get(client, '/profile')
    assert pagina.status_code == 200 and 'data-ver-como' not in pagina.get_data(as_text=True)
    assert g._login_user.id == tutor.id
    with client.session_transaction() as session:
        assert CHAVE_SESSAO not in session
