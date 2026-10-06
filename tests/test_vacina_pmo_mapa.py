"""Mapa da fila de vacinação: posição pelo atlas, zona pela malha da cidade e dia pela regra do "Criar dia"."""
import pytest

from extensions import db
from models import User
from services import vacina_pmo_mapa as mapa
from services.entomologia_dengue_auto import AddressIndex

HEADER = ['Nome completo do tutor', 'Endereço', 'Número da casa', 'Complemento (Se houver)', 'Bairro', 'Telefone',
          'Telefone 2 ou recado.', 'Quantidade de cachorros para vacinar. ', 'Quantidade de gatos para vacinar ',
          'Nome do(s) animal(is)', 'Observação:', 'Cluster']


def _ponto(u, v):
    """Longitude e latitude de um ponto dado na malha (inverso de ``mapa.malha``)."""
    x, y = u * mapa._COS - v * mapa._SIN, u * mapa._SIN + v * mapa._COS
    return [mapa.ORIGEM[0] + x / mapa._MX, mapa.ORIGEM[1] + y / mapa._MY]


def _indice(casas):
    features = [{'type': 'Feature', 'id': 'c%d' % i, 'geometry': {'type': 'Point', 'coordinates': _ponto(u, v)},
                 'properties': {'street': rua, 'house_number': str(numero), 'neighborhood': 'Bairro'}}
                for i, (rua, numero, u, v) in enumerate(casas)]
    return AddressIndex({'cnefe': {'origin': {'type': 'cnefe'}, 'features': features}})


def _linha(tutor, rua, numero, caes=1, gatos=0, bairro='Centro', complemento=''):
    return [tutor, rua, str(numero), complemento, bairro, '16999990000', '', str(caes), str(gatos), 'Rex', '', '']


@pytest.mark.parametrize('u,v,esperada', [
    (-1700, 500, 'A'), (-1600, -1300, 'B'), (-300, -1400, 'C'), (-300, -300, 'D'),
    (800, -600, 'E'), (1000, -100, 'F'), (1300, 300, 'G'), (1800, 0, 'H'), (2700, 0, 'I'),
    (2400, -600, 'J'), (1500, -600, 'K'), (2000, -1500, 'L'),
    (900, -1200, 'E'),      # ponta sul do Boa Vista não é Parisi
])
def test_zona_segue_a_malha(u, v, esperada):
    assert mapa.zona(*_ponto(u, v)) == esperada


def test_malha_tem_origem_na_vigilancia():
    u, v = mapa.malha(*mapa.ORIGEM)
    assert abs(u) < 1e-6 and abs(v) < 1e-6


def test_dias_da_fila_respeita_o_teto_de_animais():
    casas = [{'dogs': 10, 'cats': 0, 'cells': [''] * 11} for _ in range(5)]
    dias = mapa.dias_da_fila(casas)
    assert [len(d['Manha']) + len(d['Tarde']) for d in dias] == [2, 2, 1]


def test_dias_da_fila_nao_trava_com_casa_acima_do_teto():
    dias = mapa.dias_da_fila([{'dogs': 40, 'cats': 0, 'cells': [''] * 11}, {'dogs': 1, 'cats': 0, 'cells': [''] * 11}])
    assert sum(len(d['Manha']) + len(d['Tarde']) for d in dias) == 2


def test_montar_posiciona_agrupa_e_explica_o_que_faltou(app):
    indice = _indice([('Rua 8', 500, 800, -600), ('Rua 8', 520, 820, -600), ('Rua 9', 300, -300, -1400)])
    values = [HEADER,
              _linha('Ana', 'Rua 8', 500, caes=2),
              _linha('Bia', 'Rua 9', 300, gatos=1),
              _linha('Caio', 'R. 8', 510),                    # interpolado entre 500 e 520
              _linha('Duda', 'Rua 77', 10),                   # rua que o atlas não tem
              _linha('Eva', 'Rua 8', 520)]                    # já agendada (linha pintada)
    with app.app_context():
        resultado = mapa.montar(values, {6}, indice)
    casas = {casa['tutor']: casa for casa in resultado['casas']}
    assert casas['Ana']['zona'] == 'E' and casas['Bia']['zona'] == 'C' and casas['Caio']['zona'] == 'E'
    assert casas['Duda']['lat'] is None and 'Rua 77' in casas['Duda']['precisao']
    assert casas['Eva']['agendada'] and 'previsao_planilha' not in casas['Eva']
    assert resultado['resumo'] == {**resultado['resumo'], 'casas': 4, 'animais': 6, 'no_mapa': 3, 'sem_posicao': 1,
                                   'ja_agendadas': 1}
    assert casas['Ana']['previsao_planilha'] == {'dia': 1, 'turno': 'Manha', 'ordem': 1}
    # Na ordem proposta as duas casas da zona E ficam juntas e a sem posição vai para o fim.
    proposta = sorted((c for c in resultado['casas'] if not c['agendada']),
                      key=lambda c: (c['previsao_proposta']['dia'], c['previsao_proposta']['turno'], c['previsao_proposta']['ordem']))
    assert [c['tutor'] for c in proposta] == ['Bia', 'Ana', 'Caio', 'Duda']
    assert all(chave not in casas['Ana'] for chave in ('cells', '_uv', 'dogs'))
    zonas = {zona['id']: zona for zona in resultado['zonas']}
    assert zonas['E']['casas'] == 2 and zonas['E']['animais'] == 3 and zonas['C']['casas'] == 1


def _entrar(client, role):
    user = User(name='Pessoa', email=role + '-mapa@example.com', role=role)
    user.set_password('senha')
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_mapa_so_para_a_equipe_de_vacinacao(app, client):
    with app.app_context():
        db.drop_all()
        db.create_all()
        _entrar(client, 'adotante')
    assert client.get('/vacina-pmo/mapa').status_code == 404
    assert client.get('/vacina-pmo/mapa/dados').status_code == 404


def test_mapa_abre_e_o_painel_tem_o_botao(app, client, monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()
        _entrar(client, 'admin')
    monkeypatch.setattr(mapa, 'dados_do_mapa', lambda: {'success': True, 'casas': []})
    pagina = client.get('/vacina-pmo/mapa')
    assert pagina.status_code == 200 and b'pmo-mapa' in pagina.data
    assert client.get('/vacina-pmo/mapa/dados').get_json() == {'success': True, 'casas': []}
    assert b'/vacina-pmo/mapa' in client.get('/vacina-pmo').data
