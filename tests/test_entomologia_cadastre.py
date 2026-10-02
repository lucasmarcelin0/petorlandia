import json,gzip,base64,hashlib
import pytest
from services import entomologia_cadastre as cad
from services import entomologia_atlas_editor as service
from tests.test_entomologia_atualizacao import login

def fixture_data():
    return {'source':{'title':'Cadastro'},'drawings':{'S024Q045':{'code':'S024Q045','houses':[],'lines':[],'streets':[]}},'layers':[
        {'id':'cadastre-test','title':'Cadastro teste','clinical':False,'deleted':False,'origin':{'type':'street_catalog'},'revision':0,'features':[
            {'type':'Feature','id':'cep','geometry':None,'properties':{'name':'Rua Dois','address':'Rua Dois · Centro','category':'Centro','cep':'14620-010','date':'','period_year':''}}]}]}

def test_compression_integrity_and_immutable_sources(monkeypatch):
    data=fixture_data();raw=json.dumps(data).encode();wrapper=json.dumps({'encoding':'gzip-base64','sha256':hashlib.sha256(raw).hexdigest(),'payload':base64.b64encode(gzip.compress(raw)).decode()})
    assert cad.decode(wrapper)==data
    monkeypatch.setattr(cad,'active',lambda:data)
    layer=cad.source_layers()['cadastre-test'];layer['features'][0]['properties']['name']='Edited'
    assert data['layers'][0]['features'][0]['properties']['name']=='Rua Dois'
    with pytest.raises(ValueError):cad.decode(wrapper.replace(hashlib.sha256(raw).hexdigest(),'bad'))

def test_private_drawing_route_and_cep_search(client,app,monkeypatch):
    data=fixture_data();monkeypatch.setattr(cad,'active',lambda:data)
    login(client)
    found=service.search('14620-010',True);assert len(found)==1 and not found[0]['located']
    response=client.get('/sfa/entomologia/atlas/croquis/S024Q045');assert response.status_code==200 and response.json['code']=='S024Q045'
    assert 'no-store' in response.headers['Cache-Control']
    assert client.get('/sfa/entomologia/atlas/croquis/not-a-code').status_code==404
    client.get('/logout');app.config['TESTING']=False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0');monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    response=client.get('/sfa/entomologia/atlas/croquis/S024Q045')
    assert response.status_code in (302,401,403)
