import json
import pytest
from services import entomologia_atlas_editor as service
from tests.test_entomologia_atualizacao import login

BASE='/sfa/entomologia/atlas/editor'

def command(action,revision=0,**extra):
    return dict(action=action,revision=revision,reason='Conferência no campo',**extra)

def create(client,title='Equipamentos da equipe',**extra):
    response=client.post(BASE,json=command('create_layer',title=title,color='#087f81',**extra))
    assert response.status_code==200,response.get_data(as_text=True)
    return response.json

def point(name='UBS de teste',lon=-47.88):
    return {'type':'Feature','geometry':{'type':'Point','coordinates':[lon,-20.72]},
            'properties':{'name':name,'address':'Rua 2, 100','category':'Saúde','notes':'Entrada conferida'}}

def test_crud_history_restore_and_stale_editor(client,app):
    from models.entomologia import EntomologiaImportacao as E
    login(client);layer=create(client);key=layer['id'];target=BASE+'/'+key
    assert layer['features']==[]
    r=client.post(target,json=command('create_feature',layer['revision'],feature=point()))
    assert r.status_code==200
    layer=r.json;before=layer['revision'];fid=layer['features'][0]['id']
    r=client.post(target,json=command('update_feature',before,feature_id=fid,feature=point('UBS corrigida',-47.88123456789)))
    assert r.status_code==200 and r.json['features'][0]['geometry']['coordinates'][0]==-47.88123456789
    revision=r.json['revision']
    stale=client.post(target,json=command('delete_feature',before,feature_id=fid))
    assert stale.status_code==409 and stale.json['conflict']
    assert client.get(target).json['features'][0]['properties']['name']=='UBS corrigida'
    r=client.post(target,json=command('delete_feature',revision,feature_id=fid))
    assert r.status_code==200 and r.json['features']==[]
    r=client.post(target,json=command('restore',r.json['revision'],restore_revision=before))
    assert r.status_code==200 and r.json['features'][0]['properties']['name']=='UBS de teste'
    history=client.get(target+'/historico').json['revisions']
    assert len(history)==5 and history[0]['actor'].startswith('1 ·')
    r=client.post(target,json=command('delete_layer',r.json['revision']))
    assert r.status_code==200 and r.json['deleted']
    assert key not in service.layers(True)
    assert any(l['id']==key and l['deleted'] for l in client.get(BASE).json['layers'])
    assert E.query.filter_by(tipo=service.TIPO,titulo=key,status='ATIVA').count()==1

def test_source_edit_is_local_and_restore_original(client,app,monkeypatch):
    from services import entomologia_atlas as atlas
    source={'features':[dict(point(),id='source-1',properties={'layer':'Rotina','label':'Original'})],'source':{'title':'Earth'}}
    monkeypatch.setattr(atlas,'active_earth',lambda:source)
    login(client);key='earth-'+atlas.layer_id('Rotina');target=BASE+'/'+key
    layer=client.get(target).json
    r=client.post(target,json=command('update_feature',0,feature_id='source-1',feature=point('Corrigido')))
    assert r.status_code==200 and source['features'][0]['properties']['label']=='Original'
    map_layer=client.get('/sfa/entomologia/atlas/camadas/'+atlas.layer_id('Rotina'))
    assert map_layer.json['features'][0]['properties']['name']=='Corrigido'
    r=client.post(target,json=command('restore',r.json['revision'],restore_revision=0))
    assert r.status_code==200 and r.json['features'][0]['properties']['label']=='Original'

def test_team_can_edit_operational_but_not_clinical_or_token(client,app,monkeypatch):
    from extensions import db
    from models.entomologia import EntomologiaEquipe
    admin=login(client);clinical=create(client,'Casos clínicos',clinical=True)
    member=login(client,'tutor');db.session.add(EntomologiaEquipe(user_id=member.id,concedido_por='admin'));db.session.commit()
    app.config['TESTING']=False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0');monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    https={'base_url':'https://localhost'}
    r=client.post(BASE,json=command('create_layer',title='Equipe',color='#087f81'),**https)
    assert r.status_code==200
    assert client.get(BASE+'/'+clinical['id'],**https).status_code==404
    assert client.post(BASE+'/'+clinical['id'],json=command('delete_layer',clinical['revision']),**https).status_code==404
    assert client.post(BASE,json=command('create_layer',title='Dengue',color='#087f81'),**https).status_code==403
    with client.session_transaction() as sess:sess.clear()
    from flask import g
    g.pop('_login_user',None)
    monkeypatch.setenv('SFA_ADMIN_TOKEN','read-only-test')
    assert client.post(BASE+'?token=read-only-test',json=command('create_layer',title='x',color='#087f81'),**https).status_code in (302,401,403)

@pytest.mark.parametrize('bad',[{'type':'Point','coordinates':[float('nan'),0]}, {'type':'Point','coordinates':[200,0]},
    {'type':'Point','coordinates':['1','2']},{'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[2,2]]]},
    {'type':'LineString','coordinates':[[0,0]]},{'type':'GeometryCollection','geometries':[]}])
def test_invalid_coordinates_are_rejected(bad):
    with pytest.raises(ValueError):service.geometry(bad)

def test_recovery_cannot_load_another_layer(client,app):
    login(client);a=create(client,'A');b=create(client,'B')
    r=client.post(BASE+'/'+a['id'],json=command('restore',a['revision'],restore_revision=b['revision']))
    assert r.status_code==400
    assert client.get(BASE+'/'+a['id']).json['title']=='A'

def test_search_is_local_and_excludes_clinical(client,app,monkeypatch):
    login(client);a=create(client,'Locais');r=client.post(BASE+'/'+a['id'],json=command('create_feature',a['revision'],feature=point()))
    assert r.status_code==200
    b=create(client,'Casos Dengue');client.post(BASE+'/'+b['id'],json=command('create_feature',b['revision'],feature=point('private-clinical')))
    assert service.search('Rua 2, 100',False)
    assert not service.search('private-clinical',False)
    assert service.search('private-clinical',True)
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('Search must stay local'))
    assert client.get('/sfa/entomologia/atlas/busca?q=Rua%202,%20100').status_code==200

def test_documents_are_private_and_exact_sources(client,app,monkeypatch):
    login(client)
    for doc in service.documents():
        response=client.get('/sfa/entomologia/atlas/documentos/'+doc['id']+'.pdf')
        assert response.status_code==200 and response.data.startswith(b'%PDF')
        import hashlib
        assert hashlib.sha256(response.data).hexdigest()==doc['sha256']
        assert response.headers['Cache-Control']=='private, no-store'
    with client.session_transaction() as session:session.clear()
    from flask import g
    g.pop('_login_user',None);app.config['TESTING']=False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0');monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    for endpoint in ('editor','busca?q=Rua','documentos','documentos/publicos.pdf'):
        response=client.get('/sfa/entomologia/atlas/'+endpoint,base_url='https://localhost')
        assert response.status_code in (302,401,403) and not response.is_json

def test_csrf_required_for_authenticated_writes(client,app):
    login(client);app.config['WTF_CSRF_ENABLED']=True
    assert client.post(BASE,json=command('create_layer',title='Teste',color='#087f81')).status_code==400

def test_numeric_street_search_does_not_select_another_street(client,app):
    login(client)
    result=service.search('Rua 2',False)
    streets=[r for r in result if r['layer_title'].startswith('Ruas')]
    assert streets and all('rua 2' in service.search_text(r['feature']['properties']['name']) for r in streets)
    assert all(not service.search_text(r['feature']['properties']['name']).startswith('rua 20') for r in streets)
    assert service.search_text('Avenida Vinte e Dois')=='avenida 22'
    assert service.search_text('Rua Dezesseis')=='rua 16'

def test_sheet_copy_is_editable_without_writing_google(client,app,monkeypatch):
    from services import entomologia_atlas as atlas
    data={'records':[{'id':'sheet-row-2','source_row':2,'geometry':None,'sinan':'123','disease':'Dengue',
                     'notification_date':'2026-10-01','exam_result':'Negativo','classification':'Importado'}],
          'source':{'read_at':'2026-10-01T00:00:00Z','url':'https://docs.google.com/spreadsheets/d/test'}}
    monkeypatch.setattr(atlas,'live_sheet',lambda *a,**k:data)
    login(client)
    r=client.post(BASE,json=command('copy_sheet',title='Vigilância no atlas',color='#087f81'))
    assert r.status_code==200 and r.json['clinical']
    layer=r.json;feature=layer['features'][0]
    assert feature['geometry'] is None
    r=client.post(BASE+'/'+layer['id'],json=command('update_feature',layer['revision'],feature_id=feature['id'],feature=point('Posição conferida')))
    assert r.status_code==200
    assert data['records'][0]['geometry'] is None
    assert r.json['features'][0]['properties']['sinan']=='123'
    # Import-upload undo must not bypass editor permissions/concurrency.
    r=client.post('/sfa/entomologia/envios/'+str(r.json['revision'])+'/desfazer',data={'responsavel':'Equipe'})
    assert r.status_code==404
