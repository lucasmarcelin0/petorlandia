"""Testes automatizados da aba Casa a Casa, gestão de quarteirões e visitas domiciliares."""
import json
import pytest

from extensions import db
from models import User
from models.entomologia import EntomologiaQuarteiraoTrabalho, EntomologiaVisitaDomiciliar


def login(client, role='admin'):
    user = User(name='Coordenação', email=f'{role}-fieldwork@test', password_hash='x', role=role)
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    return user


@pytest.fixture()
def admin(app, client):
    return login(client)


def test_quarteiroes_estado_vazio_e_com_dados(app, client, admin):
    """Consulta estado de quarteirões e resumo de visitas."""
    res = client.get('/sfa/entomologia/quarteiroes/estado?ciclo=vigente')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'ok'
    assert isinstance(data['quarteiroes'], list)

    # Insere uma quadra manualmente e consulta novamente
    q = EntomologiaQuarteiraoTrabalho(
        setor='028',
        quarteirao='524',
        ciclo='vigente',
        cor='#bbf7d0',
        responsavel='Lucas ACE',
        status='PLANEJADO',
    )
    db.session.add(q)
    db.session.commit()

    res = client.get('/sfa/entomologia/quarteiroes/estado?ciclo=vigente')
    assert res.status_code == 200
    data = res.get_json()
    quadras = data['quarteiroes']
    assert any(item['quarteirao'] == '524' and item['cor'] == '#bbf7d0' for item in quadras)


def test_quarteiroes_salvar_novo_e_atualizar_trabalhado(app, client, admin):
    """Salva quarteirão via API e atualiza status para TRABALHADO."""
    payload = {
        'items': [{
            'setor': '028',
            'quarteirao': '525',
            'ciclo': 'vigente',
            'cor': '#bae6fd',
            'responsavel': 'Equipe Sul',
            'status': 'PLANEJADO',
        }]
    }
    res = client.post(
        '/sfa/entomologia/quarteiroes/salvar',
        data=json.dumps(payload),
        content_type='application/json',
    )
    assert res.status_code == 200
    assert res.get_json()['salvos'] == 1

    # Confere no banco
    q = EntomologiaQuarteiraoTrabalho.query.filter_by(setor='028', quarteirao='525').first()
    assert q is not None
    assert q.cor == '#bae6fd'
    assert q.status == 'PLANEJADO'
    assert q.trabalhado_em is None

    # Atualiza para TRABALHADO
    update_payload = {
        'items': [{
            'setor': '028',
            'quarteirao': '525',
            'status': 'TRABALHADO',
        }]
    }
    res2 = client.post(
        '/sfa/entomologia/quarteiroes/salvar',
        data=json.dumps(update_payload),
        content_type='application/json',
    )
    assert res2.status_code == 200

    q_updated = EntomologiaQuarteiraoTrabalho.query.filter_by(setor='028', quarteirao='525').first()
    assert q_updated.status == 'TRABALHADO'
    assert q_updated.trabalhado_em is not None


def test_visitas_sincronizar_idempotencia_e_criacao(app, client, admin):
    """Sincroniza visitas em lote garantindo desduplicação por uuid_local."""
    visitas = [
        {
            'uuid_local': 'uuid-teste-001',
            'setor': '028',
            'quarteirao': '524',
            'logradouro': 'Rua 12',
            'numero': '450',
            'situacao': 'ABERTA',
            'criadouros': ['A1', 'B'],
            'larvas': False,
            'agente': 'Carlos ACE',
            'data_visita': '2026-10-13',
            'observacao': 'Morador atencioso',
        },
        {
            'uuid_local': 'uuid-teste-002',
            'setor': '028',
            'quarteirao': '524',
            'logradouro': 'Rua 12',
            'numero': '458',
            'situacao': 'FECHADA',
            'criadouros': [],
            'larvas': False,
            'agente': 'Carlos ACE',
            'data_visita': '2026-10-13',
        },
        {
            'uuid_local': 'uuid-teste-003',
            'setor': '028',
            'quarteirao': '524',
            'logradouro': 'Rua 12',
            'numero': '462',
            'situacao': 'ABERTA',
            'criadouros': ['D1'],
            'larvas': True,
            'tubitos': 2,
            'agente': 'Carlos ACE',
            'data_visita': '2026-10-13',
            'observacao': 'Foco de larvas em pneu',
        },
    ]

    res = client.post(
        '/sfa/entomologia/visitas/sincronizar',
        data=json.dumps({'visitas': visitas}),
        content_type='application/json',
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data['recebidas'] == 3
    assert data['inseridas'] == 3

    # Testa Idempotência: reenvio não deve duplicar registros
    res_repeat = client.post(
        '/sfa/entomologia/visitas/sincronizar',
        data=json.dumps({'visitas': visitas}),
        content_type='application/json',
    )
    assert res_repeat.status_code == 200
    data_repeat = res_repeat.get_json()
    assert data_repeat['recebidas'] == 3
    assert data_repeat['inseridas'] == 0  # Nenhuma duplicata inserida

    # Lista visitas para conferir retorno
    res_list = client.get('/sfa/entomologia/visitas/listar?setor=028&quarteirao=524')
    assert res_list.status_code == 200
    list_data = res_list.get_json()
    assert len(list_data['visitas']) == 3

    foco = next(v for v in list_data['visitas'] if v['uuid_local'] == 'uuid-teste-003')
    assert foco['larvas'] is True
    assert foco['tubitos'] == 2
    assert foco['criadouros'] == ['D1']


def test_visitas_exportar_csv(app, client, admin):
    """Testa download de CSV das visitas domiciliares de campo."""
    v = EntomologiaVisitaDomiciliar(
        uuid_local='uuid-csv-001',
        setor='028',
        quarteirao='524',
        logradouro='Avenida 1',
        numero='100',
        situacao='ABERTA',
        criadouros_json='["B"]',
        larvas_encontradas=False,
        agente='Lucas',
    )
    db.session.add(v)
    db.session.commit()

    res = client.get('/sfa/entomologia/visitas/exportar.csv?setor=028')
    assert res.status_code == 200
    assert 'text/csv' in res.headers['Content-Type']
    csv_text = res.get_data(as_text=True)
    assert 'Avenida 1' in csv_text
    assert 'uuid-csv-001' in csv_text
