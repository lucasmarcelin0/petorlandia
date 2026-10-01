import json
import pytest
from services import entomologia_atlas as atlas,entomologia_atlas_editor as service
from services import entomologia_folders as folders
from tests.test_entomologia_atualizacao import login
from tests.test_entomologia_atlas_editor import command,create,point,BASE

XML='''<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Cópia de 2026</name><Folder id="root"><name>Rotina</name><Folder id="ie"><name>IE</name><Folder id="jan"><name>Janeiro</name><Folder id="sc"><name>SC 003</name><Placemark id="house"><name>Rua 2 Nº 100 - private-person</name><description>20/01/2026 private-phone</description><Point><coordinates>-47.88,-20.72</coordinates></Point></Placemark></Folder></Folder><Folder id="empty"><name>Pasta vazia</name></Folder></Folder></Folder></Document></kml>'''

def source(monkeypatch):
    data=atlas.read_earth(XML.encode(),'source.kml')
    monkeypatch.setattr(atlas,'active_earth',lambda:data)
    return data

def test_import_full_tree_empty_folders_addresses_and_dates():
    data=atlas.read_earth(XML.encode(),'source.kml');p=data['features'][0]['properties']
    assert data['schema_version']==2 and len(data['folders'])==5
    assert p['folder_path']==['Rotina','IE','Janeiro','SC 003']
    assert p['address']=='Rua 2 Nº 100' and p['date']=='2026-01-20' and p['period_year']=='2026'
    assert p['sector']=='3' and p['position_status']=='imported'
    assert 'private' not in json.dumps(data)
    assert p['source_coordinates']==data['features'][0]['geometry']['coordinates']

def test_folder_crud_cycles_and_bulk_move_preserve_records(client,app,monkeypatch):
    source(monkeypatch);login(client);key='earth-'+atlas.layer_id('Rotina');target=BASE+'/'+key
    original=client.get(target).json
    ie=next(n for n in original['folders'] if n['name']=='IE');jan=next(n for n in original['folders'] if n['name']=='Janeiro');sc=next(n for n in original['folders'] if n['name']=='SC 003')
    bad=client.post(target,json=command('update_folder',folder_id=ie['id'],name='IE',parent_id=sc['id']))
    assert bad.status_code==400 and client.get(target).json['folders']==original['folders']
    rename=client.post(target,json=command('update_folder',folder_id=jan['id'],name='Janeiro · conferência',parent_id=ie['id']))
    assert rename.status_code==200
    assert rename.json['features'][0]['properties']['folder_path']==['Rotina','IE','Janeiro · conferência','SC 003']
    bad=client.post(target,json=command('delete_folder',rename.json['revision'],folder_id=sc['id']))
    assert bad.status_code==400
    made=client.post(target,json=command('create_folder',rename.json['revision'],name='Revisados',parent_id=ie['id']))
    assert made.status_code==200
    new=next(n for n in made.json['folders'] if n['name']=='Revisados')
    moved=client.post(target,json=command('move_features',made.json['revision'],folder_id=new['id'],feature_ids=['house']))
    assert moved.status_code==200
    old=original['features'][0];new_feature=moved.json['features'][0]
    assert new_feature['geometry']==old['geometry']
    assert new_feature['properties']['date']==old['properties']['date']
    assert new_feature['properties']['address']==old['properties']['address']
    assert new_feature['properties']['folder_path']==['Rotina','IE','Revisados']
    assert client.post(target,json=command('move_features',made.json['revision'],folder_id='',feature_ids=['house'])).status_code==409
    deleted=client.post(target,json=command('delete_folder',moved.json['revision'],folder_id=sc['id']))
    assert deleted.status_code==200
    restore=client.post(target,json=command('restore',deleted.json['revision'],restore_revision=0))
    assert restore.status_code==200 and restore.json['features']==original['features']

def test_folder_validation_and_clinical_escalation(client,app):
    login(client);layer=create(client);target=BASE+'/'+layer['id']
    item=point();item['properties']['folder_id']='other-layer-folder'
    assert client.post(target,json=command('create_feature',layer['revision'],feature=item)).status_code==400
    with app.app_context():
        with pytest.raises(PermissionError):
            folders.apply({**layer,'folders':[]},{'action':'create_folder','name':'Casos Dengue','parent_id':''},service.text,False,atlas.is_case)
    item=point();item['properties'].update(position_status='made-up')
    assert client.post(target,json=command('create_feature',layer['revision'],feature=item)).status_code==400

def test_legacy_revision_recovers_tree_without_reverting_edits_or_deletions():
    source={'id':'earth-x','title':'Rotina','clinical':False,'features':[
        {'id':'a','properties':{'name':'Rua 2 Nº 100','address':'Rua 2 Nº 100','folder_id':'sc','folder_path':['Rotina','SC 003'],'position_status':'imported'},'geometry':{'type':'Point','coordinates':[-47.88,-20.72]}},
        {'id':'deleted','properties':{'folder_id':'sc'},'geometry':None}],
        'folders':[{'id':'sc','name':'SC 003','parent_id':''}]}
    edited={'id':'earth-x','title':'Rotina','clinical':False,'origin':{'type':'earth'},'features':[
        {'id':'a','properties':{'name':'Entrada corrigida'},'geometry':{'type':'Point','coordinates':[-47.881,-20.721]}}]}
    result=folders.upgrade_revision(edited,source)
    assert len(result['features'])==1
    assert result['features'][0]['properties']['name']=='Entrada corrigida'
    assert result['features'][0]['properties']['address']=='Rua 2 Nº 100'
    assert result['features'][0]['properties']['folder_path']==['Rotina','SC 003']
    assert result['features'][0]['properties']['position_status']=='to_review'

def test_spatial_review_stays_local_and_draft_never_writes(client,app,monkeypatch):
    from services import entomologia_georeference as geo
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('Conferência não pode transmitir endereço ao exterior'))
    login(client);layer=create(client);target=BASE+'/'+layer['id'];item=point('Entrada em conferência');item['properties']['address']='Rua 2, 100'
    r=client.post(target,json=command('create_feature',layer['revision'],feature=item));assert r.status_code==200
    fid=r.json['features'][0]['id'];review=client.get(target+'/conferencia')
    assert review.status_code==200 and review.json['summary']['records']==1
    moved=point('Entrada em conferência',lon=0)
    draft=client.post(target+'/conferencia',json={'feature_id':fid,'feature':moved})
    assert draft.status_code==200 and 'Fora do entorno do território cadastrado' in draft.json['records'][0]['issues']
    assert client.get(target).json['revision']==r.json['revision']
    assert client.get(target).json['features'][0]['geometry']['coordinates'][0]==-47.88
    candidate=geo.assess({'id':'c','geometry':None,'properties':{'address':'Sem referência'}})
    assert 'Sem posição' in candidate['issues']

def test_spatial_review_honors_clinical_access(client,app,monkeypatch):
    from extensions import db
    from models.entomologia import EntomologiaEquipe
    login(client);layer=create(client,'Casos Dengue',clinical=True)
    member=login(client,'tutor');db.session.add(EntomologiaEquipe(user_id=member.id,concedido_por='admin'));db.session.commit()
    app.config['TESTING']=False;monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0');monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    assert client.get(BASE+'/'+layer['id']+'/conferencia',base_url='https://localhost').status_code==404

def test_folder_browser_model():
    import shutil,subprocess
    node=shutil.which('node')
    if not node:pytest.skip('Node ausente')
    root=service.DATA.parents[3]
    r=subprocess.run([node,str(root/'tests'/'test_atlas_folders_model.js')],cwd=root,capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr


def test_reimport_same_file_upgrades_legacy_metadata_once(client,app):
    from models.entomologia import EntomologiaImportacao as E
    from extensions import db
    from tests.test_entomologia_atualizacao import enviar,confirmar_ultimo
    login(client);data=atlas.read_earth(XML.encode(),'source.kml')
    old={**data,'schema_version':1};old.pop('folders')
    entry=E(tipo=atlas.TIPO_ATLAS,status='ATIVA',titulo='2026',nome_arquivo='source.kml',
            sha256=data['source']['sha256'],linhas=1,dados_json=json.dumps(old),resumo_json='{}',responsavel='Equipe',ator='Equipe')
    db.session.add(entry);db.session.commit()
    response=enviar(client,XML.encode(),'source.kml',tipo=atlas.TIPO_ATLAS)
    assert response.status_code==302 and E.query.filter_by(status='PREVIA').count()==1
    new=confirmar_ultimo(client)
    assert json.loads(new.dados_json)['schema_version']==2
    enviar(client,XML.encode(),'source.kml',tipo=atlas.TIPO_ATLAS)
    assert E.query.filter_by(status='PREVIA').count()==0


def test_moving_imported_or_confirmed_point_invalidates_position(client,app,monkeypatch):
    source(monkeypatch);login(client);target=BASE+'/earth-'+atlas.layer_id('Rotina')
    layer=client.get(target).json;item=layer['features'][0]
    item['geometry']['coordinates'][0]-=.0001
    moved=client.post(target,json=command('update_feature',feature_id=item['id'],feature=item))
    assert moved.status_code==200 and moved.json['features'][0]['properties']['position_status']=='to_review'
    item=moved.json['features'][0];item['properties']['position_status']='verified'
    confirmed=client.post(target,json=command('update_feature',moved.json['revision'],feature_id=item['id'],feature=item,confirm_position=True))
    assert confirmed.status_code==200
    item=confirmed.json['features'][0];item['geometry']['coordinates'][0]-=.0001
    again=client.post(target,json=command('update_feature',confirmed.json['revision'],feature_id=item['id'],feature=item))
    assert again.json['features'][0]['properties']['position_status']=='to_review'


def test_condominium_reference_uses_current_shared_house_position(client,app):
    login(client);layers=service.layers(True)
    house_layer=next(l for l in layers.values() if l['origin']['type']=='condominium' and 'Quebec' in l['title'])
    house=house_layer['features'][0];house['geometry']['coordinates'][0]+=.00005
    corrected=client.post(BASE+'/'+house_layer['id'],json=command('update_feature',feature_id=house['id'],feature=house))
    assert corrected.status_code==200
    local=create(client);item=point();item['properties']['address']=house['properties']['address']
    draft=client.post(BASE+'/'+local['id']+'/conferencia',json={'feature':item})
    assert draft.status_code==200
    assert draft.json['records'][0]['house_candidate']['coordinates']==house['geometry']['coordinates']
    assert draft.json['records'][0]['house_candidate']['position_status']=='to_review'

    house['geometry']=None
    absent=client.post(BASE+'/'+house_layer['id'],json=command('update_feature',corrected.json['revision'],feature_id=house['id'],feature=house))
    assert absent.status_code==200
    draft=client.post(BASE+'/'+local['id']+'/conferencia',json={'feature':item})
    assert draft.status_code==200 and draft.json['records'][0]['house_candidate'] is None


def test_legacy_revision_preserves_clinical_source_restriction():
    source={'id':'earth-x','title':'Rotina','clinical':True,'features':[],'folders':[]}
    old={'id':'earth-x','title':'Rotina','clinical':False,'origin':{'type':'earth'},'features':[]}
    assert folders.upgrade_revision(old,source)['clinical'] is True
