import csv,io,zipfile
from copy import deepcopy
import pytest
from services import entomologia_cnefe as c
from services.entomologia_atlas_editor import clean_feature

BOUNDARY={'type':'Polygon','coordinates':[[[-48,-21],[-47,-21],[-47,-20],[-48,-20],[-48,-21]]]}

def row(**changes):
    result={k:'' for k in ['COD_UNICO_ENDERECO','COD_MUNICIPIO','NOM_TIPO_SEGLOGR','NOM_TITULO_SEGLOGR','NOM_SEGLOGR','NUM_ENDERECO','DSC_MODIFICADOR','LATITUDE','LONGITUDE','NV_GEO_COORD','COD_ESPECIE','COD_TIPO_ESPECI','DSC_LOCALIDADE','CEP']}
    result.update(COD_UNICO_ENDERECO='100',COD_MUNICIPIO='3534302',NOM_TIPO_SEGLOGR='RUA',NOM_SEGLOGR='VINTE E QUATRO',NUM_ENDERECO='1963',LATITUDE='-20.7',LONGITUDE='-47.9',NV_GEO_COORD='1',COD_ESPECIE='1',COD_TIPO_ESPECI='101',DSC_LOCALIDADE='CENTRO',CEP='14620000')
    result.update(changes);return result

def archive(rows):
    text=io.StringIO();writer=csv.DictWriter(text,fieldnames=sorted({k for r in rows for k in r}),delimiter=';');writer.writeheader();writer.writerows(rows)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:z.writestr('orlandia.csv',text.getvalue().encode())
    return output.getvalue()

def test_original_coordinate_and_number_are_preserved_without_personal_fields():
    data=c.build(archive([row(DSC_ESTABELECIMENTO='Not published')]),BOUNDARY)
    f=data['layers'][0]['features'][0]
    assert f['geometry']['coordinates']==[-47.9,-20.7]==f['properties']['source_coordinates']
    assert f['properties']['name']=='Rua 24, 1963' and f['properties']['kind']=='cnefe_house'
    assert f['properties']['position_status']=='imported'
    assert 'Not published' not in str(data)
    c.validate(data)

def test_one_address_can_have_multiple_uses_and_duplicate_projections_are_consolidated():
    first=row();second=row(COD_ESPECIE='6',COD_TIPO_ESPECI='')
    data=c.build(archive([first,first,second]),BOUNDARY)
    assert data['source']['records']==2 and data['source']['unique_address_ids']==1
    assert data['source']['consolidated_duplicates']==1
    assert len({f['id'] for f in data['layers'][0]['features']})==2
    c.validate(data)

@pytest.mark.parametrize('change',[{'NV_GEO_COORD':'3'},{'NV_GEO_COORD':'2'},{'NV_GEO_COORD':'4'},{'LATITUDE':'-25'},{'LONGITUDE':'NaN'}])
def test_uncertain_or_invalid_positions_do_not_receive_satellite_geometry(change):
    data=c.build(archive([row(**change)]),BOUNDARY);f=data['layers'][0]['features'][0]
    assert f['geometry'] is None and f['properties']['quality_issues']
    assert f['properties']['kind']=='cnefe_address';c.validate(data)

def test_road_disagreement_is_quarantined_and_coincident_addresses_do_not_show_individual_numbers():
    data=c.build(archive([row()]),BOUNDARY,lambda f:{'declared_road':{'distance_m':70}})
    assert data['layers'][0]['features'][0]['geometry'] is None
    data=c.build(archive([row(),row(COD_UNICO_ENDERECO='200',NUM_ENDERECO='1965')]),BOUNDARY)
    assert data['source'].get('number_labels',0)==0
    assert all(f['geometry'] for f in data['layers'][0]['features'])
    assert all(f['properties']['kind']=='cnefe_address' for f in data['layers'][0]['features'])

def test_no_number_and_kilometer_do_not_become_house_labels():
    for change in ({'NUM_ENDERECO':'0','DSC_MODIFICADOR':'SN'},{'NUM_ENDERECO':'15','DSC_MODIFICADOR':'KM'}):
        f=c.build(archive([row(**change)]),BOUNDARY)['layers'][0]['features'][0]
        assert not f['properties']['house_number'] and f['properties']['kind']=='cnefe_address'

def test_import_validation_rejects_changed_coordinate_or_claim_of_field_verification():
    source=c.build(archive([row()]),BOUNDARY)
    for mutate in (lambda f:f['geometry']['coordinates'].__setitem__(0,-47.8),lambda f:f['properties'].__setitem__('position_status','verified')):
        data=deepcopy(source);mutate(data['layers'][0]['features'][0])
        with pytest.raises(ValueError):c.validate(data)

def test_number_can_be_corrected_while_source_coordinate_is_retained():
    f=c.build(archive([row()]),BOUNDARY)['layers'][0]['features'][0]
    updated=clean_feature({'geometry':f['geometry'],'properties':{'house_number':'1963A'}},f)
    assert updated['properties']['house_number']=='1963A' and updated['properties']['number_edited']
    assert updated['properties']['source_coordinates']==f['properties']['source_coordinates']
    assert updated['properties']['name']=='Rua 24, 1963A'
    assert updated['properties']['address'].startswith('Rua 24, 1963A ·')
    with pytest.raises(ValueError):clean_feature({'geometry':f['geometry'],'properties':{'house_number':'wrong'}},f)


def test_bulk_addresses_honor_revisions_and_require_access(client,app,monkeypatch):
    from services import entomologia_atlas_editor as editor
    from tests.test_entomologia_atualizacao import login
    source=c.build(archive([row()]),BOUNDARY)
    monkeypatch.setattr(c,'active',lambda:source)
    login(client)
    layer=next(item for item in editor.layers(True).values() if item['origin']['type']=='cnefe')
    feature=layer['features'][0]
    editor.save(layer['id'],{'action':'update_feature','revision':0,'reason':'Conferência local','feature_id':feature['id'],'feature':{'geometry':feature['geometry'],'properties':{'house_number':'1963A'}}},True,'Equipe teste')
    response=client.get('/sfa/entomologia/atlas/enderecos')
    assert response.status_code==200 and 'no-store' in response.headers['Cache-Control']
    assert len(response.json['layers'])==1
    assert response.json['layers'][0]['features'][0]['properties']['house_number']=='1963A'
    assert source['layers'][0]['features'][0]['properties']['house_number']=='1963'
    client.get('/logout');app.config['TESTING']=False
    monkeypatch.setenv('SFA_ALLOW_OPEN_ACCESS','0');monkeypatch.delenv('SFA_ADMIN_TOKEN',raising=False)
    assert client.get('/sfa/entomologia/atlas/enderecos').status_code in (302,401,403)
