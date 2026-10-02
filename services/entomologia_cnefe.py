"""Public IBGE address references; original coordinates never get snapped."""
from collections import Counter, defaultdict
from copy import deepcopy
import csv, hashlib, io, json, math, re, unicodedata, zipfile

TIPO = 'atlas_cnefe'
MUNICIPALITY = '3534302'
SOURCE_URL = 'https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio/35_SP/3534302_ORL%c3%82NDIA.zip'
QUALITY = {'1':'Coordenada original do Censo 2022', '2':'Coordenada modificada/agrupada pelo IBGE', '3':'Coordenada estimada pelo IBGE', '4':'Referência de face de quadra', '5':'Referência de localidade', '6':'Referência de setor censitário'}

def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.lower()) if not unicodedata.combining(c)).strip()

def street_number(value):
    numbers={'cinco':5,'quatro':4,'dois':2,'tres':3,'um':1,'sete':7,'seis':6,'nove':9,'oito':8,'dez':10,'onze':11,'doze':12,'treze':13,'quatorze':14,'catorze':14,'quinze':15,'dezesseis':16,'dezessete':17,'dezoito':18,'dezenove':19,'vinte':20,'trinta':30,'quarenta':40,'cinquenta':50,'sessenta':60,'setenta':70,'oitenta':80,'noventa':90,'cem':100}
    key=normalized(value)
    if key in numbers:return str(numbers[key])
    parts=key.split(' e ')
    if len(parts)==2 and parts[0] in numbers and numbers[parts[0]]>=20 and parts[1] in numbers and numbers[parts[1]]<10:
        return str(numbers[parts[0]]+numbers[parts[1]])
    return value.strip()

def street_name(row):
    return ' '.join(p for p in (row['NOM_TIPO_SEGLOGR'].title(),row['NOM_TITULO_SEGLOGR'].title(),street_number(row['NOM_SEGLOGR']).title()) if p)

def inside(point,geometry):
    def ring(points):
        x,y=point;odd=False
        for a,b in zip(points,points[1:]):
            if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:odd=not odd
        return odd
    polygons=geometry['coordinates'] if geometry['type']=='MultiPolygon' else [geometry['coordinates']]
    return any(ring(rings[0]) and not any(ring(r) for r in rings[1:]) for rings in polygons)

def read_csv(raw_zip):
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        names=[n for n in archive.namelist() if n.lower().endswith('.csv')]
        if len(names)!=1:raise ValueError('Use um CSV municipal por arquivo.')
        raw=archive.read(names[0])
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')),delimiter=';')
    required={'COD_UNICO_ENDERECO','COD_MUNICIPIO','NOM_TIPO_SEGLOGR','NOM_TITULO_SEGLOGR','NOM_SEGLOGR','NUM_ENDERECO','DSC_MODIFICADOR','LATITUDE','LONGITUDE','NV_GEO_COORD','COD_ESPECIE','COD_TIPO_ESPECI','DSC_LOCALIDADE','CEP'}
    if not required.issubset(reader.fieldnames or []):raise ValueError('Colunas do CNEFE incompatíveis.')
    return list(reader)

def active():
    from services.entomologia_cadastre import active_record
    return active_record(TIPO)

def source_layers():
    return {layer['id']:{**deepcopy(layer),'default_visible':True} for layer in active()['layers']}

def build(raw_zip,boundary,assess=None):
    original_rows=read_csv(raw_zip)
    # An address can have several species/uses. Keep those uses, consolidate exact
    # duplicates of the geographic projection, and never publish establishment names.
    fields=['COD_UNICO_ENDERECO','COD_MUNICIPIO','NOM_TIPO_SEGLOGR','NOM_TITULO_SEGLOGR','NOM_SEGLOGR','NUM_ENDERECO','DSC_MODIFICADOR','LATITUDE','LONGITUDE','NV_GEO_COORD','COD_ESPECIE','COD_TIPO_ESPECI','DSC_LOCALIDADE','CEP']+[p+str(n) for n in range(1,6) for p in ('NOM_COMP_ELEM','VAL_COMP_ELEM')]
    projected={tuple(r.get(k,'') for k in fields):r for r in original_rows}
    rows=list(projected.values());ids=set();groups={};issues_count=Counter();levels=Counter();checks=Counter()
    coordinates=Counter((r['LONGITUDE'],r['LATITUDE']) for r in rows)
    coordinate_addresses=defaultdict(set)
    for r in rows:
        coordinate_addresses[(r['LONGITUDE'],r['LATITUDE'])].add((street_name(r),r['NUM_ENDERECO'],r['DSC_MODIFICADOR']))
    source_hash=hashlib.sha256(raw_zip).hexdigest()
    for row in rows:
        if row['COD_MUNICIPIO']!=MUNICIPALITY:raise ValueError('Arquivo contém outro município.')
        unique=row['COD_UNICO_ENDERECO']
        if not unique:raise ValueError('Identificador do CNEFE ausente.')
        feature_id='cnefe-'+unique+'-'+hashlib.sha256(json.dumps([row.get(k,'') for k in fields],ensure_ascii=False).encode()).hexdigest()[:12]
        if feature_id in ids:raise ValueError('Identificador da referência CNEFE duplicado.')
        ids.add(feature_id);level=row['NV_GEO_COORD'];levels[level]+=1
        street=street_name(row);neighborhood=row['DSC_LOCALIDADE'].title() or 'Localidade não informada'
        number=row['NUM_ENDERECO'];modifier=row['DSC_MODIFICADOR'].strip()
        numbered=number.isdigit() and int(number)>0 and modifier.upper() not in ('SN','KM')
        address_number=number+modifier if numbered and re.fullmatch(r'[A-Za-z]{1,2}',modifier) else number
        address=street+', '+(address_number if numbered else 'sem número')
        if modifier and not re.fullmatch(r'[A-Za-z]{1,2}',modifier) and modifier!='SN':address+=' · '+modifier
        complements=[]
        for n in range(1,6):
            name=row.get('NOM_COMP_ELEM'+str(n),'').strip();value=row.get('VAL_COMP_ELEM'+str(n),'').strip()
            if name or value:complements.append(' '.join(p for p in (name.title(),value) if p))
        if complements:address+=' · '+' · '.join(complements)
        address+=' · '+neighborhood
        point=None;issues=[]
        try:
            point=[float(row['LONGITUDE']),float(row['LATITUDE'])]
            valid=all(math.isfinite(v) for v in point) and -180<=point[0]<=180 and -90<=point[1]<=90
        except (TypeError,ValueError):valid=False
        if not valid:issues.append('Coordenada inválida')
        elif not inside(point,boundary):issues.append('Coordenada fora do limite municipal de referência')
        if level!='1':issues.append(QUALITY.get(level,'Geocodificação não reconhecida'))
        house=row['COD_TIPO_ESPECI'] in ('101','102')
        if valid and not issues and assess:
            result=assess({'id':unique,'geometry':{'type':'Point','coordinates':point},'properties':{'address':street}})
            declared=result.get('declared_road');nearest=result.get('nearest_road')
            if declared:
                checks['matched_street']+=1
                if declared['distance_m']>60:issues.append('Coordenada distante da rua informada na base local')
            else:checks['street_without_match']+=1
            if nearest and nearest['distance_m']>100:checks['far_from_local_road']+=1
        ambiguous=len(coordinate_addresses[(row['LONGITUDE'],row['LATITUDE'])])>1
        geometry={'type':'Point','coordinates':point[:]} if not issues else None
        kind='cnefe_house' if house and numbered and geometry and not ambiguous else 'cnefe_address'
        if house and numbered:checks['numbered_house_records']+=1
        if kind=='cnefe_house':checks['number_labels']+=1
        if geometry:checks['located_records']+=1
        if ambiguous:checks['shared_coordinate_records']+=1
        for issue in issues:issues_count[issue]+=1
        key='cnefe-'+hashlib.sha256(normalized(neighborhood).encode()).hexdigest()[:16]
        if key not in groups:
            groups[key]={'id':key,'title':neighborhood,'color':'#2a8884','clinical':False,'deleted':False,'origin':{'type':'cnefe','title':'IBGE · CNEFE 2022','url':SOURCE_URL,'note':'Coordenadas originais publicadas pelo IBGE. Conferência de sinalização e entrada atual a cargo da equipe.'},'features':[],'folders':[],'revision':0}
        folder=key+'-street-'+hashlib.sha256(normalized(street).encode()).hexdigest()[:12]
        layer=groups[key]
        if not any(f['id']==folder for f in layer['folders']):layer['folders'].append({'id':folder,'name':street or 'Logradouro não informado','parent_id':''})
        cep=row['CEP'];cep=cep[:5]+'-'+cep[5:] if len(cep)==8 else cep
        notes='Endereço público do Censo 2022. Não confirma mudanças posteriores nem o número exibido atualmente na fachada.'
        if ambiguous:notes+=' Há endereços distintos com a mesma coordenada; consulte os registros agrupados.'
        if issues:notes+=' Pendências: '+'; '.join(issues)+'.'
        p={'name':street+', '+(address_number if numbered else 'sem número'),'address':address[:240],
           'house_number':address_number if numbered else '', 'kind':kind,'street':street,
           'original_street':' '.join(row[k] for k in ('NOM_TIPO_SEGLOGR','NOM_TITULO_SEGLOGR','NOM_SEGLOGR') if row[k]),
           'neighborhood':neighborhood,'cep':cep,'category':'Casa' if house else 'Endereço do CNEFE',
           'folder_id':folder,'source_coordinates':point if valid else None,'source_sha256':source_hash,
           'cnefe_id':unique,'cnefe_geo_level':level,'cnefe_species':row['COD_ESPECIE'],
           'cnefe_building_type':row['COD_TIPO_ESPECI'],'source_year':2022,
           'position_status':'imported' if geometry else 'unlocated',
           'precision':QUALITY.get(level,'Qualidade desconhecida')+'. Coordenada preservada; entrada e sinalização atuais a conferir.',
           'notes':notes,'quality_issues':issues,'date':'','period_year':''}
        layer['features'].append({'type':'Feature','id':feature_id,'geometry':geometry,'properties':p})
    layers=sorted(groups.values(),key=lambda l:l['title'])
    for layer in layers:
        if len(layer['features'])>5000:raise ValueError('Divida uma localidade com mais de 5.000 registros.')
        layer['folders'].sort(key=lambda f:f['name'])
    source={'title':'Endereços georreferenciados · IBGE CNEFE 2022','municipality':MUNICIPALITY,'year':2022,
            'read_only':True,'url':SOURCE_URL,'sha256':source_hash,'records':len(rows),'raw_records':len(original_rows),
            'consolidated_duplicates':len(original_rows)-len(rows),'unique_address_ids':len({r['COD_UNICO_ENDERECO'] for r in rows}),
            'neighborhoods':len(layers),'geocoding_levels':dict(levels),'issues':dict(issues_count),**dict(checks)}
    return {'schema_version':1,'source':source,'layers':layers,'drawings':{}}

def validate(data):
    source=data.get('source',{})
    if data.get('schema_version')!=1 or source.get('municipality')!=MUNICIPALITY or source.get('year')!=2022 or source.get('url')!=SOURCE_URL or not source.get('read_only'):
        raise ValueError('Fonte CNEFE inválida.')
    ids=set()
    for layer in data['layers']:
        if not layer['id'].startswith('cnefe-') or layer.get('clinical') or layer['origin']['type']!='cnefe':raise ValueError('Camada CNEFE inválida.')
        if len(layer['features'])>5000:raise ValueError('Camada CNEFE grande demais.')
        for f in layer['features']:
            if f['id'] in ids:raise ValueError('Identificadores repetidos.')
            ids.add(f['id']);p=f['properties'];g=f.get('geometry')
            if p.get('position_status')=='verified':raise ValueError('A importação não pode afirmar conferência de campo.')
            if g:
                if g.get('type')!='Point' or p.get('cnefe_geo_level')!='1' or p.get('quality_issues') or g['coordinates']!=p.get('source_coordinates'):
                    raise ValueError('Posição CNEFE alterada ou sem qualidade original.')
                from services.entomologia_atlas_editor import geometry
                geometry(g)
    if len(ids)!=source['records']:raise ValueError('Contagem CNEFE inconsistente.')
