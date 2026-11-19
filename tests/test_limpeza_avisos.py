"""Prefeitura integrada: responsáveis recebem aviso de tarefa nova, concluída e de volta à fila."""
import importlib.util
from pathlib import Path

import pytest

from extensions import db
from models.limpeza import LimpezaComprovacao, LimpezaSolicitacao
from services import limpeza_avisos
from services import limpeza_urbana as servico

_spec = importlib.util.spec_from_file_location(
    "_limpeza_base_avisos", Path(__file__).resolve().parent / "test_limpeza_urbana.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
conta, entrar, dar, limpar_g, comunicar, comprovar = (base.conta, base.entrar, base.dar, base.limpar_g,
                                                      base.comunicar, base.comprovar)
uploads, PONTO = base.uploads, base.PONTO


@pytest.fixture()
def avisos(monkeypatch):
    """Captura e-mails e pushes: [(canal, e-mail ou id da conta, título, texto, url)]."""
    enviados = []

    def email(destinatarios, assunto, corpo):
        enviados.extend(('email', d, assunto, corpo, None) for d in destinatarios)
        return True

    def push(user_id, titulo, texto, url=None, tag=None, session=None):
        enviados.append(('push', user_id, titulo, texto, url))
        return 1

    monkeypatch.setattr('services.notifications._send_email', email)
    monkeypatch.setattr('services.push.push_to_user', push)
    return enviados


def _quem(enviados, canal='push'):
    return {e[1] for e in enviados if e[0] == canal}


def _papel(nome, permissoes, tipos):
    chave = servico.criar_papel(nome, permissoes, tipos, 'Coordenação').chave
    db.session.commit()
    return chave


@pytest.fixture()
def cidade(client):
    """Morador, equipe geral, equipe só de poda, equipe só de entulho, fiscal e administrador."""
    pessoas = dict(
        morador=conta('morador@example.test'), equipe=conta('gari@example.test', name='Gari Geral'),
        poda=conta('poda@example.test'), entulho=conta('entulho@example.test'),
        fiscal=conta('fiscal@example.test'), admin=conta('admin@example.test', role='admin'),
    )
    dar(pessoas['morador'], 'colaborador')
    dar(pessoas['equipe'], 'equipe')
    dar(pessoas['poda'], _papel('Equipe de poda', ['comprovar'], ['galhos']))
    dar(pessoas['entulho'], _papel('Equipe de entulho', ['comprovar'], ['entulho']))
    dar(pessoas['fiscal'], 'fiscal')
    return pessoas


def test_tarefa_nova_avisa_so_a_equipe_que_atende_aquele_tipo(client, uploads, avisos, cidade):
    entrar(client, cidade['morador'])
    assert comunicar(client, categoria='galhos', referencia='Praça da Matriz').status_code == 302
    item = LimpezaSolicitacao.query.one()

    assert _quem(avisos) == {cidade['equipe'].id, cidade['poda'].id}
    assert _quem(avisos, 'email') == {'gari@example.test', 'poda@example.test'}
    _canal, _uid, titulo, texto, url = next(e for e in avisos if e[0] == 'push')
    assert titulo == f'Nova tarefa nº {item.num}: Galhos e poda'
    assert 'Praça da Matriz' in texto and url.endswith(f'/limpeza-urbana/solicitacao/{item.id}')
    corpo = next(e[3] for e in avisos if e[0] == 'email')
    assert f'://localhost/limpeza-urbana/solicitacao/{item.id}' in corpo


def test_quem_comunica_nao_recebe_o_proprio_aviso(client, uploads, avisos, cidade):
    entrar(client, cidade['equipe'])
    comunicar(client, categoria='galhos')
    assert _quem(avisos) == {cidade['poda'].id}


def test_tarefa_concluida_avisa_equipe_e_fiscalizacao_menos_quem_comprovou(client, uploads, avisos, cidade):
    entrar(client, cidade['morador'])
    comunicar(client, categoria='galhos')
    item = LimpezaSolicitacao.query.one()
    avisos.clear()

    entrar(client, cidade['poda'])
    assert comprovar(client, item.id, lat=PONTO[0] + 0.003, lon=PONTO[1]).status_code == 302  # ~330 m
    assert _quem(avisos) == {cidade['equipe'].id, cidade['fiscal'].id}
    _canal, _uid, titulo, texto, _url = avisos[-1]
    assert titulo == f'Tarefa nº {item.num} concluída: Galhos e poda'
    assert 'por Poda' in texto and 'a 33' in texto and 'longe do ponto' in texto


def test_comprovacao_recusada_devolve_a_tarefa_e_avisa_quem_comprovou(client, uploads, avisos, cidade):
    entrar(client, cidade['morador'])
    comunicar(client, categoria='galhos')
    item = LimpezaSolicitacao.query.one()
    entrar(client, cidade['equipe'])
    comprovar(client, item.id)
    comprovacao = LimpezaComprovacao.query.one()
    avisos.clear()

    entrar(client, cidade['fiscal'])
    client.post(f'/limpeza-urbana/comprovacao/{comprovacao.id}/recusar', data={'motivo': 'Galhos continuam lá'})
    assert db.session.get(LimpezaSolicitacao, item.id).status == 'aberta'
    assert _quem(avisos) == {cidade['equipe'].id, cidade['poda'].id}
    _canal, _uid, titulo, texto, _url = avisos[-1]
    assert titulo == f'Tarefa nº {item.num} voltou para a fila: Galhos e poda'
    assert 'Galhos continuam lá' in texto


def test_envio_que_falha_nao_avisa_ninguem(client, uploads, avisos, cidade):
    entrar(client, cidade['morador'])
    assert comunicar(client, categoria='galhos', lat=None).status_code == 400  # sem localização
    assert LimpezaSolicitacao.query.count() == 0 and avisos == []


def test_falha_no_aviso_nao_impede_a_comunicacao(client, uploads, avisos, cidade, monkeypatch):
    def quebra(*args, **kwargs):
        raise RuntimeError('falha simulada')

    monkeypatch.setattr(limpeza_avisos, 'responsaveis', quebra)
    entrar(client, cidade['morador'])
    assert comunicar(client, categoria='galhos').status_code == 302
    assert LimpezaSolicitacao.query.count() == 1 and avisos == []


def test_papel_revogado_ou_fora_do_periodo_nao_recebe(client, uploads, avisos, cidade):
    from datetime import timedelta
    acesso = next(a for a in servico.acessos_ativos() if a.user_id == cidade['poda'].id)
    servico.revogar(acesso.id, 'Coordenação')
    futuro = servico.hoje() + timedelta(days=5)
    servico.alterar_acesso(next(a for a in servico.acessos_ativos() if a.user_id == cidade['equipe'].id).id,
                           futuro, None, 'Coordenação')
    db.session.commit()
    limpar_g()
    entrar(client, cidade['morador'])
    comunicar(client, categoria='galhos')
    assert avisos == []


def test_mapa_convida_a_equipe_a_ativar_os_avisos_no_aparelho(client, cidade):
    entrar(client, cidade['equipe'])
    assert 'Ativar avisos neste aparelho' in client.get('/limpeza-urbana/mapa').get_data(as_text=True)
    entrar(client, cidade['admin'])
    assert 'Ativar avisos neste aparelho' not in client.get('/limpeza-urbana/mapa').get_data(as_text=True)


def test_aviso_espera_o_commit_final_e_nao_o_do_savepoint(app, uploads, avisos, cidade):
    """Casa a Casa usa begin_nested na mesma transação: liberar o savepoint não pode disparar o aviso."""
    item = LimpezaSolicitacao(numero=servico.proximo_numero(), autor_id=cidade['morador'].id, categorias='galhos',
                              latitude=PONTO[0], longitude=PONTO[1], origem_local='aparelho',
                              foto_url='https://fotos.example.test/a.jpg', status='aberta')
    db.session.add(item)
    db.session.flush()
    servico.registrar_evento('comunicada', item.id, cidade['morador'])
    with db.session.begin_nested():
        pass
    assert avisos == []
    db.session.commit()
    assert _quem(avisos) == {cidade['equipe'].id, cidade['poda'].id}


def test_rollback_descarta_o_aviso(app, uploads, avisos, cidade):
    item = LimpezaSolicitacao(numero=servico.proximo_numero(), autor_id=cidade['morador'].id, categorias='galhos',
                              latitude=PONTO[0], longitude=PONTO[1], origem_local='aparelho',
                              foto_url='https://fotos.example.test/a.jpg', status='aberta')
    db.session.add(item)
    db.session.flush()
    servico.registrar_evento('comunicada', item.id, cidade['morador'])
    db.session.rollback()
    db.session.commit()
    assert avisos == []
