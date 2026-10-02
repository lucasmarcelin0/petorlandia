import hashlib
import json
import pytest
from scripts.prepare_entomologia_condominios import build, inside
from services import entomologia_atlas_editor as service
from tests.test_entomologia_atualizacao import login

def test_house_transcription_provenance_and_operational_bounds():
    root=service.DATA.parent
    data=service.condominiums()
    assert build(root)==data
    assert len(data['features'])==394
    territory=json.loads((root/'territory.json').read_text(encoding='utf-8'))
    blocks={(f['properties']['sector'],f['properties']['block']):f for f in territory['features']}
    for source in data['source']['maps']:
        assert hashlib.sha256((root/'maps'/source['map']).read_bytes()).hexdigest()==source['sha256']
        houses=[f for f in data['features'] if f['properties']['condominium']==source['condominium']]
        assert sorted(int(f['properties']['house_number']) for f in houses)==list(range(1,198))
        assert len({f['id'] for f in houses})==197
        assert {f['properties']['category'] for f in houses}=={f'Alameda {n:02d}' for n in range(1,8)}
        for house in houses:
            p=house['properties'];ring=blocks[(p['sector'],p['block'])]['geometry']['coordinates'][0][0]
            assert inside(house['geometry']['coordinates'],ring)
            assert 'estimada' in p['precision']
            assert not ({'owner','resident','patient','cpf','phone'}&p.keys())

@pytest.mark.parametrize('query,condo,number',[
    ('Quebec casa 01','Quebec','1'),('Torino casa 197','Torino','197'),
    ('Condomínio Quebec, Alameda 02, Casa 14','Quebec','14'),
    ('Torino Alameda 07 Casa 144','Torino','144')])
def test_house_search_does_not_confuse_alameda_and_house(client,app,query,condo,number):
    login(client)
    rows=service.search(query,False)
    assert len(rows)==1
    assert rows[0]['feature']['properties']['condominium']==condo
    assert rows[0]['feature']['properties']['house_number']==number
    assert not service.search('Quebec Alameda 02 Casa 162',False)

def test_house_source_is_active_editable_and_restorable(client,app):
    login(client)
    layers=service.layers(False)
    original=next(l for l in layers.values() if l['title']=='Casas · Condomínio Quebec')
    assert original['default_visible'] and not original['clinical'] and len(original['features'])==197
    house=next(f for f in original['features'] if f['id']=='quebec-casa-1')
    target='/sfa/entomologia/atlas/editor/'+original['id']
    payload={'action':'update_feature','revision':0,'reason':'Entrada conferida',
        'feature_id':house['id'],'feature':{**house,'geometry':{'type':'Point','coordinates':[-47.872,-20.708]},
        'properties':{**house['properties'],'address':'Condomínio Quebec, Alameda 02, Casa 1, entrada conferida',
                      'precision':'Entrada conferida no campo'}}}
    response=client.post(target,json=payload)
    assert response.status_code==200
    changed=next(f for f in response.json['features'] if f['id']==house['id'])
    assert changed['geometry']['coordinates']==[-47.872,-20.708]
    assert changed['properties']['house_number']=='1'
    assert service.source_layers()[original['id']]['features']==original['features']
    response=client.post(target,json={'action':'restore','revision':response.json['revision'],
                                    'reason':'Repor croqui','restore_revision':0})
    assert response.status_code==200
    assert response.json['features']==original['features']

def test_condominium_browser_model():
    import shutil,subprocess
    node=shutil.which('node')
    if not node:pytest.skip('Node não disponível')
    root=service.DATA.parents[3]
    result=subprocess.run([node,str(root/'tests'/'test_condominios_model.js')],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
