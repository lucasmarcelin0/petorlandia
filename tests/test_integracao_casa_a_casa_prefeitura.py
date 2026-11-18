"""Casa a Casa e Prefeitura integrada: a solicitação de campo vira comunicação no mapa e o andamento volta."""
import importlib.util
from pathlib import Path

from extensions import db
from models.entomologia import EntomologiaSolicitacao
from models.limpeza import LimpezaComprovacao, LimpezaSolicitacao
from services import integracao_casa_a_casa_prefeitura as integracao


def _carregar(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, Path(__file__).resolve().parent / arquivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


casa = _carregar("_integracao_casa", "test_entomologia_casa_a_casa.py")
limpeza = _carregar("_integracao_limpeza", "test_limpeza_urbana.py")
base = casa.base
uploads = limpeza.uploads
RAIZ, HTTPS = casa.RAIZ, casa.HTTPS


def _entrar_agente(client):
    ana = casa.agente()
    casa.entrar(client, ana)
    return ana


def test_solicitacao_com_foto_abre_comunicacao_e_comprovacao_resolve(client, base, uploads):
    ana = _entrar_agente(client)
    resposta = casa.enviar_solicitacao(client, casa.solicitacao(base['a']))
    assert resposta.status_code == 200
    s = EntomologiaSolicitacao.query.one()
    comunicacao = LimpezaSolicitacao.query.one()
    assert comunicacao.entomologia_solicitacao_id == s.id and comunicacao.autor_id == ana.id
    assert comunicacao.categorias == 'lixo,entulho' and comunicacao.status == 'aberta'
    assert (comunicacao.latitude, comunicacao.longitude, comunicacao.origem_local) == (-20.72, -47.88, 'aparelho')
    assert comunicacao.foto_url == s.foto_url
    assert 'Casa a Casa' in comunicacao.descricao and 'Rua Um, 10' in comunicacao.referencia
    # Na volta para o aparelho e no escritório aparece o número da comunicação.
    assert resposta.json['solicitacao']['prefeitura']['numero'] == comunicacao.num
    assert s.status == 'ABERTA' and s.destino == 'Obras' and not s.historico_json
    html = client.get(RAIZ + '/solicitacoes', **HTTPS).get_data(as_text=True)
    assert f'Comunicação nº {comunicacao.num}' in html and f'/limpeza-urbana/solicitacao/{comunicacao.id}' in html
    # Reenvio do aparelho não duplica a comunicação.
    casa.enviar_solicitacao(client, casa.solicitacao(base['a']))
    assert LimpezaSolicitacao.query.count() == 1

    # A equipe da Prefeitura comprova com foto: a solicitação do Casa a Casa fica Resolvida.
    gari, fiscal = limpeza.conta('gari@example.test'), limpeza.conta('fiscal@example.test')
    limpeza.dar(gari, 'equipe')
    limpeza.dar(fiscal, 'fiscal')
    limpeza.entrar(client, gari)
    ficha = client.get(f'/limpeza-urbana/solicitacao/{comunicacao.id}').get_data(as_text=True)
    assert 'Casa a Casa (visita de campo)' in ficha
    limpeza.comprovar(client, comunicacao.id, lat=-20.72, lon=-47.88)
    assert db.session.get(LimpezaSolicitacao, comunicacao.id).status == 'concluida'
    s = db.session.get(EntomologiaSolicitacao, s.id)
    assert s.status == 'RESOLVIDA' and 'atendimento comprovado' in s.historico_json

    # Fiscalização recusa a comprovação: as duas voltam para a fila.
    limpeza.entrar(client, fiscal)
    comprovacao = LimpezaComprovacao.query.one()
    client.post(f'/limpeza-urbana/comprovacao/{comprovacao.id}/recusar', data={'motivo': 'Entulho continua'})
    assert db.session.get(EntomologiaSolicitacao, s.id).status == 'ABERTA'

    # Descartada na Prefeitura: segue Aberta no Casa a Casa, com o motivo, para seguir por ofício.
    client.post(f'/limpeza-urbana/solicitacao/{comunicacao.id}/descartar', data={'motivo': 'Imóvel particular'})
    s = db.session.get(EntomologiaSolicitacao, s.id)
    assert s.status == 'ABERTA' and 'Imóvel particular' in s.historico_json


def test_sem_foto_fica_so_no_casa_a_casa_e_vai_quando_ganha_foto(client, base, uploads):
    _entrar_agente(client)
    casa.enviar_solicitacao(client, casa.solicitacao(base['a'], categoria='VAZAMENTO', precisao=None, destino=''), foto=False)
    s = EntomologiaSolicitacao.query.one()
    assert LimpezaSolicitacao.query.count() == 0 and s.status == 'ABERTA'

    corpo = {'dados': '{}', 'foto': (casa._jpeg(), 'foto.jpg', 'image/jpeg')}
    resposta = client.post(f'{RAIZ}/solicitacoes/{s.id}', data=corpo, content_type='multipart/form-data', **HTTPS)
    assert resposta.status_code == 200, resposta.get_data(as_text=True)
    comunicacao = LimpezaSolicitacao.query.one()
    # Sem equivalente no catálogo vai como "Outro"; sem GPS vale a posição do imóvel.
    assert comunicacao.categorias == 'outro' and comunicacao.origem_local == 'imovel'
    assert db.session.get(EntomologiaSolicitacao, s.id).status == 'ABERTA'


def test_excluir_no_casa_a_casa_descarta_e_restaurar_reabre(client, base, uploads):
    ana = _entrar_agente(client)
    casa.enviar_solicitacao(client, casa.solicitacao(base['a']))
    s = EntomologiaSolicitacao.query.one()
    client.post(f'{RAIZ}/solicitacoes/{s.id}/excluir', json={}, **HTTPS)
    comunicacao = LimpezaSolicitacao.query.one()
    assert comunicacao.status == 'descartada' and comunicacao.motivo_descarte == integracao.MOTIVO_EXCLUIDA
    assert db.session.get(EntomologiaSolicitacao, s.id).excluida_em is not None

    client.post(f'{RAIZ}/solicitacoes/{s.id}/excluir', json={'restaurar': True}, **HTTPS)
    comunicacao = LimpezaSolicitacao.query.one()
    assert comunicacao.status == 'aberta' and comunicacao.motivo_descarte is None
    assert ana.id == comunicacao.autor_id


def test_falha_na_prefeitura_nao_perde_a_solicitacao_de_campo(client, base, uploads, monkeypatch):
    _entrar_agente(client)

    def quebra(*_args, **_kwargs):
        raise RuntimeError('fora do ar')

    monkeypatch.setattr(integracao, 'enviar', quebra)
    resposta = casa.enviar_solicitacao(client, casa.solicitacao(base['a']))
    assert resposta.status_code == 200 and EntomologiaSolicitacao.query.count() == 1
    assert LimpezaSolicitacao.query.count() == 0
