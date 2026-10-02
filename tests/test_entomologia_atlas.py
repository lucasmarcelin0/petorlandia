import pytest
from services.entomologia_atlas import read_earth, sheet_records, catalog, date_iso, result_group

def feature(key, point=True):
    return {'type':'Feature','geometry':{'type':'Point' if point else 'Polygon','coordinates':[-47.88,-20.72]},
            'properties':{'layer':'Casos Dengue','sinan':key}}

def row(key, name='private-person'):
    r = ['']*20
    r[3], r[7], r[9], r[11], r[5], r[6], r[16], r[18] = key,name,'private-address','private-phone','30/09/2026','29/09/2026','Negativo','Importado'
    return r

def test_sheet_links_only_unique_explicit_key_and_drops_identifiers():
    records = sheet_records([['header'],row('00123'),row('456'),row('456'),row('999')],
                            {'features':[feature('123'),feature('456'),feature('999'),feature('999')]})
    assert records[0]['geometry'] is not None
    assert all(r['geometry'] is None for r in records[1:])
    assert records[0]['notification_date']=='2026-09-30'
    assert records[0]['classification']=='Importado'
    assert 'private' not in str(records)
    assert 'nome' not in records[0] and 'endereco' not in records[0]

def test_earth_keeps_geometry_month_status_and_rejects_entities():
    xml = b'''<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>2026</name><Folder><name>Casos Dengue</name><Folder><name>janeiro</name><Folder><name>Negativo</name><Placemark id="source-1"><name>private-person</name><description>SINAN: 00123 private-phone</description><Point><coordinates>-47.88123456789,-20.72123456789,0</coordinates></Point></Placemark></Folder></Folder></Folder></Document></kml>'''
    data=read_earth(xml,'source.kml')
    f=data['features'][0]
    assert f['geometry']['coordinates']==[-47.88123456789,-20.72123456789]
    assert f['properties']['month']=='01' and f['properties']['sinan']=='123'
    assert 'private' not in str(data)
    assert catalog(data,False)['layers'][0]['count'] is None
    assert catalog(data,False)['layers'][0]['allowed'] is False
    with pytest.raises(ValueError):
        read_earth(b'<!DOCTYPE x [<!ENTITY p SYSTEM "file:///secret">]><kml>&p;</kml>','bad.kml')

def test_dates_and_results_do_not_invent_classifications():
    assert date_iso('31/02/2026')==''
    assert result_group('Negativo Clin. Epidemiológico')=='negative'
    assert result_group('Positivo Clin. Epidemiológico')=='positive'
    assert result_group('')=='unknown'
    assert result_group('Autóctone')=='unknown'


def test_atlas_upload_preview_confirmation_and_undo(client, app):
    import json
    from tests.test_entomologia_atualizacao import login, enviar, confirmar_ultimo
    from models.entomologia import EntomologiaImportacao
    from services.entomologia_atlas import active_earth, TIPO_ATLAS, layer_id
    login(client)
    xml=b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Atlas</name><Folder><name>Rotina</name><Placemark><name>private-person</name><description>private-address</description><Point><coordinates>-47.88,-20.72</coordinates></Point></Placemark></Folder></Document></kml>'
    response=enviar(client,xml,'atlas.kml',tipo=TIPO_ATLAS)
    assert response.status_code==302
    entry=EntomologiaImportacao.query.one()
    assert entry.status=='PREVIA' and not active_earth()['features']
    assert 'private' not in entry.dados_json
    confirmar_ultimo(client)
    assert len(active_earth()['features'])==1
    api=client.get('/sfa/entomologia/atlas/camadas/'+layer_id('Rotina'))
    assert api.status_code==200 and len(api.json['features'])==1
    assert api.headers['Cache-Control']=='private, no-store'
    assert api.headers['Referrer-Policy']=='no-referrer'
    html=client.get('/sfa/entomologia').get_data(as_text=True)
    data=json.loads(html.split('id="ento-dataset">',1)[1].split('</script>',1)[0])
    assert not data['layers']  # The private snapshot is never inlined in the page.
    assert data['atlas_urls']['clinical_allowed']
    client.post(f'/sfa/entomologia/envios/{entry.id}/desfazer',data={'responsavel':'Coordenação'})
    assert not active_earth()['features']


def test_live_sheet_bounds_header_and_read_only_cache(monkeypatch):
    from types import SimpleNamespace
    from services import sfa_service, entomologia_atlas as atlas
    calls=[]
    def execute(payload):
        return SimpleNamespace(execute=lambda:payload)
    class Values:
        def get(self,**kwargs):
            calls.append(kwargs)
            header=['']*20
            for index,name in {1:'Agravo/Doença',3:'SINAN',5:'Data notificação',6:'Data inicio sintomas',15:'Tipo de Exame',16:'Resultado',17:'Resultado final',18:'Classificação do Caso'}.items():
                header[index]=name
            return execute({'values':[header,row('123')]})
    class Sheets:
        def get(self,**kwargs):
            return execute({'sheets':[{'properties':{'sheetId':atlas.SHEET_GID,'title':"Resposta's",'gridProperties':{'rowCount':272}}}]})
        def values(self):
            return Values()
    monkeypatch.setattr(sfa_service,'_get_sheets_service',lambda:SimpleNamespace(spreadsheets=lambda:Sheets()))
    monkeypatch.setattr(atlas,'_sheet_cache',{})
    earth={'features':[feature('123')]}
    first=atlas.live_sheet(earth,force=True)
    assert first['source']['rows']==first['source']['mapped']==1
    assert 'private' not in str(first)
    assert calls[0]['range']=="'Resposta''s'!A1:T272"
    assert atlas.live_sheet({'features':[]})['source']['mapped']==0
    assert len(calls)==1  # Cache raw bounded rows, recompute current spatial links.
    atlas.live_sheet(earth,force=True)
    assert len(calls)==2


def test_unauthenticated_atlas_endpoints_return_no_data(client, app, monkeypatch):
    app.config['TESTING']=False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0')
    monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    for url in ('/sfa/entomologia/atlas/camadas','/sfa/entomologia/atlas/camadas/example','/sfa/entomologia/atlas/sinan'):
        response=client.get(url,base_url='https://localhost')
        assert response.status_code in (302,401,403)
        assert not response.is_json
