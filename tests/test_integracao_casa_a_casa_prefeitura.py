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


def test_botao_da_prefeitura_no_mapa_so_para_quem_pode_comunicar(client, base, monkeypatch):
    from services import limpeza_urbana as servico_limpeza
    _entrar_agente(client)

    monkeypatch.setattr(servico_limpeza, 'pode_comunicar', lambda _user: False)
    pagina = client.get(RAIZ, **HTTPS).get_data(as_text=True)
    assert 'id="cac-cidade"' in pagina and 'id="cac-prefeitura"' not in pagina

    monkeypatch.setattr(servico_limpeza, 'pode_comunicar', lambda _user: True)
    pagina = client.get(RAIZ, **HTTPS).get_data(as_text=True)
    assert 'id="cac-prefeitura" href="/limpeza-urbana/comunicar"' in pagina
    # O botão fica logo abaixo dos três ícones do mapa.
    assert pagina.index('id="cac-cidade"') < pagina.index('id="cac-prefeitura"') < pagina.index('cac-legenda')
    # Abre numa janela por cima do mapa, com a página da Prefeitura embutida.
    assert 'id="cac-pi-janela"' in pagina and 'casa_a_casa_prefeitura.js' in pagina

    def quebra(_user):
        raise RuntimeError('fora do ar')

    monkeypatch.setattr(servico_limpeza, 'pode_comunicar', quebra)
    resposta = client.get(RAIZ, **HTTPS)
    assert resposta.status_code == 200 and 'id="cac-prefeitura"' not in resposta.get_data(as_text=True)


def test_camada_da_prefeitura_so_para_quem_ve_o_mapa(client, base, monkeypatch):
    from services import limpeza_urbana as servico_limpeza
    _entrar_agente(client)
    monkeypatch.setattr(servico_limpeza, 'pode_comunicar', lambda _user: False)

    monkeypatch.setattr(servico_limpeza, 'pode_ver_mapa', lambda _user: False)
    pagina = client.get(RAIZ, **HTTPS).get_data(as_text=True)
    assert 'id="cac-pi"' not in pagina and 'id="cac-pi-janela"' not in pagina
    assert 'casa_a_casa_prefeitura.js' not in pagina and 'id="cac-legenda"' in pagina

    monkeypatch.setattr(servico_limpeza, 'pode_ver_mapa', lambda _user: True)
    pagina = client.get(RAIZ, **HTTPS).get_data(as_text=True)
    # A camada fica logo abaixo de "Cores".
    assert pagina.index('id="cac-legenda"') < pagina.index('id="cac-pi"')
    assert '"prefeitura_mapa": "/limpeza-urbana/mapa/dados"' in pagina
    assert '"prefeitura_item": "/limpeza-urbana/solicitacao/0"' in pagina
    assert 'id="cac-prefeitura"' not in pagina   # comunicar continua exigindo a própria permissão


def test_prefeitura_abre_embutida_so_no_proprio_site(client, base, monkeypatch):
    from services import limpeza_urbana as servico_limpeza
    _entrar_agente(client)
    monkeypatch.setattr(servico_limpeza, 'pode_comunicar', lambda _user: True)
    comunicar = client.get('/limpeza-urbana/comunicar', **HTTPS)
    assert comunicar.status_code == 200
    assert comunicar.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert "frame-ancestors 'self'" in comunicar.headers['Content-Security-Policy']
    assert "default-src 'self'" in comunicar.headers['Content-Security-Policy']
    assert 'limpeza-embutida' in comunicar.get_data(as_text=True)

    casa_a_casa = client.get(RAIZ, **HTTPS)
    assert casa_a_casa.headers['X-Frame-Options'] == 'DENY'
    assert "frame-ancestors 'none'" in casa_a_casa.headers['Content-Security-Policy']
    # A janela embutida pode usar câmera e local, como a página da Prefeitura.
    assert 'camera=(self)' in casa_a_casa.headers['Permissions-Policy']
    assert 'geolocation=(self)' in casa_a_casa.headers['Permissions-Policy']
