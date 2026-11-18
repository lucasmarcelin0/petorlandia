"""Prefeitura integrada: parabéns gamificado depois de comunicar e de comprovar."""
import importlib.util
import json
import re
from pathlib import Path

from models import User
from services import limpeza_urbana as servico

_spec = importlib.util.spec_from_file_location(
    "_limpeza_base_parabens", Path(__file__).resolve().parent / "test_limpeza_urbana.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
conta, entrar, dar, limpar_g, comunicar, comprovar = (base.conta, base.entrar, base.dar, base.limpar_g,
                                                      base.comunicar, base.comprovar)
uploads = base.uploads

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _parabens_da_pagina(html):
    achado = re.search(r'var inicial = (\{.*?\});', html)
    return json.loads(achado.group(1)) if achado else None


def test_niveis_de_conquista():
    primeira = servico.conquista(1)
    assert primeira['novo_nivel'] and primeira['nivel'] == 'Olho vivo'
    assert primeira['proximo_nivel'] == 'Vizinho atento' and primeira['faltam'] == 2
    segunda = servico.conquista(2)
    assert not segunda['novo_nivel'] and segunda['nivel'] == 'Olho vivo' and segunda['progresso'] == 50
    assert servico.conquista(3)['novo_nivel'] and servico.conquista(3)['nivel'] == 'Vizinho atento'
    topo = servico.conquista(80)
    assert topo['nivel'] == 'Herói da cidade' and 'proximo_nivel' not in topo and topo['progresso'] == 100
    assert servico.conquista(1, 'comprovacao')['nivel'] == 'Mão na massa'


def test_envio_pelo_celular_devolve_parabens_sem_aviso_atrasado(client, uploads):
    morador = conta('morador@example.test')
    dar(morador, 'colaborador')
    entrar(client, morador)
    resposta = client.post('/limpeza-urbana/comunicar', headers=AJAX, content_type='multipart/form-data', data={
        'categoria': 'lixo', 'foto': (base.foto(), 'foto.jpg'),
        'latitude': str(base.PONTO[0]), 'longitude': str(base.PONTO[1]), 'precisao': '8'})
    dados = resposta.get_json()
    assert resposta.status_code == 200 and dados['numero'] == 1
    assert dados['parabens']['tipo'] == 'comunicacao' and dados['parabens']['nivel'] == 'Olho vivo'
    assert dados['parabens']['novo_nivel'] and dados['parabens']['total'] == 1
    # O aviso antigo aparecia depois, em outra página; agora o parabéns é mostrado na hora pela tela.
    limpar_g()
    pagina = client.get('/limpeza-urbana/minhas').get_data(as_text=True)
    assert 'registrada. Obrigado' not in pagina and _parabens_da_pagina(pagina) is None


def test_envio_sem_script_mostra_parabens_uma_vez(client, uploads):
    morador = conta('morador@example.test')
    dar(morador, 'colaborador')
    entrar(client, morador)
    comunicar(client)
    comunicar(client)
    limpar_g()
    pagina = client.get('/limpeza-urbana/minhas').get_data(as_text=True)
    parabens = _parabens_da_pagina(pagina)
    assert parabens['numero'] == 2 and parabens['total'] == 2 and parabens['faltam'] == 1
    limpar_g()
    assert _parabens_da_pagina(client.get('/limpeza-urbana/minhas').get_data(as_text=True)) is None


def test_comprovacao_mostra_parabens_e_alerta_de_distancia(client, uploads):
    morador = conta('morador@example.test')
    dar(morador, 'colaborador')
    entrar(client, morador)
    comunicar(client)
    comunicar(client)
    perto, longe = base.LimpezaSolicitacao.query.order_by(base.LimpezaSolicitacao.id).all()

    equipe = conta('equipe@example.test')
    dar(equipe, 'equipe')
    entrar(client, equipe)
    comprovar(client, perto.id)
    limpar_g()
    pagina = client.get(f'/limpeza-urbana/solicitacao/{perto.id}').get_data(as_text=True)
    parabens = _parabens_da_pagina(pagina)
    assert parabens['tipo'] == 'comprovacao' and parabens['nivel'] == 'Mão na massa' and 'alerta' not in parabens
    assert 'Ir para o próximo ponto' in pagina

    comprovar(client, longe.id, lat=base.PONTO[0] + 0.01)
    limpar_g()
    parabens = _parabens_da_pagina(client.get(f'/limpeza-urbana/solicitacao/{longe.id}').get_data(as_text=True))
    assert parabens['total'] == 2 and 'fiscalização vai conferir' in parabens['alerta']


def test_tela_de_comunicar_explica_os_passos_e_esconde_pendencias_vazias(client):
    morador = conta('morador@example.test')
    dar(morador, 'colaborador')
    entrar(client, morador)
    pagina = client.get('/limpeza-urbana/comunicar').get_data(as_text=True)
    assert 'Comunicar um problema na cidade' in pagina and 'Enviar comunicação' in pagina
    assert 'Tire a foto' in pagina and 'Sem internet?' in pagina
    assert 'id="limpeza-pendencias" role="status"' in pagina and 'alert alert-info d-none' in pagina
    assert 'id="limpeza-parabens"' in pagina and 'ponto para limpeza' not in pagina
    offline = (Path(__file__).resolve().parents[1] / 'static/js/limpeza_offline.js').read_text(encoding='utf-8')
    assert "tipo: 'guardada'" in offline and 'parabens(dados)' in offline
    assert 'Comunicações enviadas e confirmadas pelo servidor' not in offline
    assert User.query.count() == 1
