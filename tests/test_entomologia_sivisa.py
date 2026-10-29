import io
import json
import pytest
from extensions import db
from models.entomologia import EntomologiaImportacao
from services.entomologia_sivisa import validar
from services.entomologia_service import dataset_atual
from models import User
from flask import g

def login(client, role='admin'):
    user=User(name='Teste',email=f'{role}-sivisa@test',password_hash='x',role=role)
    db.session.add(user);db.session.commit()
    with client.session_transaction() as session:
        session.clear();session['_user_id']=str(user.id);session['_fresh']=True
    g.pop('_login_user',None)

def payload():
    return {'inicio':'2023-10-29','fim':'2026-10-29','registros':[
        {'nome':'Teste', 'endereco':'Rua 1, 100', 'data':'2025-01-01', 'validade':'2027-01-01', 'coordenadas':[-47.88,-20.72], 'cpf':'12345678901'},
        {'nome':'Outro', 'endereco':'Rua 2', 'data':'2026-01-01', 'validade':'', 'coordenadas':None}]}

def test_importacao_exclusiva_admin_e_fora_da_base_compartilhada(app, client, monkeypatch):
    login(client)
    raw=json.dumps(payload()).encode()
    response=client.post('/sfa/entomologia/sivisa',data={'responsavel':'Admin','arquivo':(io.BytesIO(raw),'dados.json')},content_type='multipart/form-data')
    assert response.status_code==302
    row=EntomologiaImportacao.query.filter_by(tipo='sivisa_privado').one()
    assert row.linhas==2 and '12345678901' not in row.dados_json
    result=client.get('/sfa/entomologia/sivisa').get_json()
    assert len(result['registros'])==2 and result['registros'][1]['coordenadas'] is None
    assert not any(x['id']==row.id for x in dataset_atual()['layers'])
    login(client, role='veterinario')
    monkeypatch.setenv('SFA_ADMIN_TOKEN','token-interno')
    assert client.get('/sfa/entomologia/sivisa',headers={'X-SFA-Token':'token-interno'}).status_code in (403,404)
    assert client.post('/sfa/entomologia/sivisa',headers={'X-SFA-Token':'token-interno'}).status_code in (403,404)
    assert b'Teste' not in client.get('/sfa/entomologia',headers={'X-SFA-Token':'token-interno'}).data

def test_validacao_nao_aceita_coordenada_ou_data_invalidas():
    data=payload(); data['registros'][0]['coordenadas']=[float('nan'),-20.72]
    with pytest.raises(ValueError): validar(json.dumps(data).encode())
    data=payload(); data['registros'][0]['data']='2022-01-01'
    with pytest.raises(ValueError): validar(json.dumps(data).encode())
