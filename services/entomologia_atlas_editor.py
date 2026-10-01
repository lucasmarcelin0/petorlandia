"""Collaborative atlas revisions, protected sources and local place search.

Revisions reuse the audited import table. One active snapshot per layer;
deletions remain snapshots and restoration creates a new revision.
"""
from __future__ import annotations
from contextlib import contextmanager
from functools import lru_cache
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import uuid

from services import entomologia_atlas as atlas
from services.entomologia_atlas import layer_id, is_case, normalize, PALETTE

TIPO = 'atlas_edit'
DATA = Path(__file__).parent/'data'/'entomologia'/'atlas-referencias'
_write_lock = threading.RLock()
FIELDS = {'name':200,'address':240,'category':120,'notes':2000,'date':10,'status':120,
          'sinan':40,'disease':120,'notification_date':10,'symptoms_date':10,'exam':120,
          'exam_result':160,'final_result':160,'classification':120,'precision':240}

class Conflict(ValueError):
    pass

def dumps(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)

@lru_cache(maxsize=1)
def references():
    return json.loads((DATA/'lugares.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def condominiums():
    return json.loads((DATA/'condominios.json').read_text(encoding='utf-8'))

def documents():
    return json.loads((DATA/'documentos.json').read_text(encoding='utf-8'))

def source_layers():
    """Source snapshots; revisions cannot mutate original files or Google data."""
    groups={}
    def add(features,prefix,origin):
        for index,f in enumerate(features):
            name=f.get('properties',{}).get('layer','Referências')
            if normalize(name)=='quadras': continue
            key=prefix+layer_id(name)
            if key not in groups:
                groups[key]={'id':key,'title':name,'color':PALETTE.get(normalize(name),'#65bdd2'),
                             'clinical':is_case(name),'deleted':False,'origin':origin,'features':[], 'revision':0}
            if origin['type']=='condominium':
                groups[key]['default_visible']=True
                groups[key]['color']=f['properties']['color']
            item=deepcopy(f)
            item['id']=str(item.get('id') or key+'-'+str(index+1))
            groups[key]['features'].append(item)
    earth=atlas.active_earth()
    add(earth['features'],'earth-',{'type':'earth','import_id':earth.get('source',{}).get('import_id'),
                                  'title':'Cópia Google Earth'})
    ref=references()
    add(ref['features'],'ref-',{'type':'reference','title':'OpenStreetMap','data_at':ref['source']['data_at']})
    add(condominiums()['features'],'condo-',{'type':'condominium','title':'Croqui de condomínio + quadras',
        'note':condominiums()['source']['method']})
    from services.entomologia_service import dataset_atual
    for upload in dataset_atual().get('layers',[]):
        key='upload-'+str(upload['id'])
        items=deepcopy(upload['geojson']['features'])
        for f in items:
            p=f.setdefault('properties',{})
            p['name']=p.get('name') or p.get('label') or ''
            p['category']=p.get('folder','')[:120]
        for index,f in enumerate(items):
            f['id']=str(f.get('id') or key+'-'+str(index+1))
        groups[key]={'id':key,'title':upload['title'],'color':'#aec7ec','clinical':is_case(upload['title']),
                     'deleted':False,'origin':{'type':'upload','title':'Camada enviada'},'features':items,'revision':0}
    return groups

def revision_rows(key=None):
    from models.entomologia import EntomologiaImportacao as E
    query=E.query.filter_by(tipo=TIPO)
    if key: query=query.filter_by(titulo=key)
    return query.order_by(E.id.desc()).populate_existing()

def layers(clinical_allowed, include_deleted=False):
    from services.entomologia_service import consultar_sem_interromper
    result=source_layers()
    for row in consultar_sem_interromper(lambda:revision_rows().filter_by(status='ATIVA').all(),[]) or []:
        layer=json.loads(row.dados_json)
        layer['revision']=row.id
        layer['updated_at']=row.confirmado_em.isoformat()
        result[layer['id']]=layer
    return {key:item for key,item in result.items() if (clinical_allowed or not item['clinical'])
            and (include_deleted or not item['deleted'])}

def catalog(clinical_allowed, include_deleted=False):
    return [{k:v for k,v in layer.items() if k!='features'} | {'count':len(layer['features']),
            'unlocated':sum(f.get('geometry') is None for f in layer['features'])}
            for layer in layers(clinical_allowed,include_deleted).values()]

def text(value, field, required=False):
    if not isinstance(value,str): raise ValueError('Campo de texto inválido: '+field)
    value=value.strip()
    if (required and not value) or len(value)>FIELDS.get(field,200):
        raise ValueError('Confira o campo '+field+'.')
    return value

def geometry(value):
    if value is None: return None
    if not isinstance(value,dict): raise ValueError('Geometria inválida.')
    total=[0]
    def position(pair):
        if not isinstance(pair,list) or len(pair)!=2 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in pair):
            raise ValueError('Use coordenadas numéricas [longitude, latitude].')
        if not(-180<=pair[0]<=180 and -90<=pair[1]<=90): raise ValueError('Coordenada fora dos limites geográficos.')
        total[0]+=1
        if total[0]>20000: raise ValueError('Geometria com vértices demais.')
        return pair[:]
    def line(coords,ring=False):
        if not isinstance(coords,list) or len(coords)<(4 if ring else 2): raise ValueError('Contorno incompleto.')
        result=[position(p) for p in coords]
        if ring and result[0]!=result[-1]: raise ValueError('Feche o polígono repetindo o primeiro vértice.')
        if len({tuple(p) for p in result})<(3 if ring else 2): raise ValueError('Use vértices distintos para definir o contorno.')
        if ring:
            area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(result,result[1:]))
            if abs(area)<1e-14: raise ValueError('O polígono não define uma área.')
        return result
    def parse(g,depth=0):
        if depth>3 or not isinstance(g,dict): raise ValueError('Geometria inválida.')
        kind=g.get('type');coords=g.get('coordinates')
        if kind=='Point': out=position(coords)
        elif kind=='LineString': out=line(coords)
        elif kind=='Polygon':
            if not isinstance(coords,list) or not coords: raise ValueError('Polígono vazio.')
            out=[line(r,True) for r in coords]
        elif kind=='MultiLineString':
            if not isinstance(coords,list) or not coords: raise ValueError('Linhas vazias.')
            out=[line(r) for r in coords]
        elif kind=='MultiPolygon':
            if not isinstance(coords,list) or not coords: raise ValueError('Polígonos vazios.')
            out=[parse({'type':'Polygon','coordinates':p},depth+1)['coordinates'] for p in coords]
        elif kind=='GeometryCollection':
            gs=g.get('geometries')
            if not isinstance(gs,list) or not gs: raise ValueError('Coleção vazia.')
            return {'type':kind,'geometries':[parse(p,depth+1) for p in gs]}
        else: raise ValueError('Tipo de geometria não suportado.')
        return {'type':kind,'coordinates':out}
    return parse(value)

def clean_feature(payload, previous=None):
    if not isinstance(payload,dict): raise ValueError('Registro inválido.')
    raw=payload.get('properties',{})
    if not isinstance(raw,dict): raise ValueError('Campos inválidos.')
    # Preserve only source properties already known to the server. New fields are bounded.
    props=deepcopy(previous.get('properties',{})) if previous else {}
    for field,limit in FIELDS.items():
        if field not in raw: continue
        props[field]=text(raw[field],field)
        if field.endswith('date') or field=='date':
            if props[field]:
                try: date.fromisoformat(props[field])
                except ValueError as exc: raise ValueError('Data inválida: '+field) from exc
    if not props.get('name'): props['name']=props.get('label') or 'Registro sem título'
    props['label']=props['name']
    if props.get('sinan'):
        number=atlas.identifier(props['sinan'])
        if not number: raise ValueError('Use somente números no campo SINAN.')
        props['sinan']=number
    if props.get('date'): props['month']=props['date'][5:7]
    elif previous and previous.get('properties',{}).get('date'): props['month']=''
    return {'type':'Feature','id':str(previous['id']) if previous else 'point-'+uuid.uuid4().hex,
            'geometry':geometry(payload.get('geometry')), 'properties':props}

@contextmanager
def write_transaction():
    """Serialize first source edits too, across Heroku workers/dynos on PostgreSQL."""
    from extensions import db
    from sqlalchemy import text as sql
    with _write_lock:
        if db.engine.dialect.name=='postgresql':
            db.session.execute(sql('SELECT pg_advisory_xact_lock(69461307)'))
        try: yield
        except Exception:
            db.session.rollback()
            raise

def save(key, command, allowed_clinical, actor):
    from extensions import db
    from models.entomologia import EntomologiaImportacao as E
    from blueprints.entomologia_routes import _auditar
    from time_utils import utcnow
    if not isinstance(command,dict): raise ValueError('Comando inválido.')
    action=command.get('action')
    reason=text(command.get('reason',''), 'notes',True)
    with write_transaction():
        current=layers(allowed_clinical,True).get(key) if key else None
        if key and current is None: raise LookupError('Camada inexistente ou sem acesso.')
        if not key:
            if action not in ('create_layer','copy_layer','copy_sheet'): raise ValueError('Crie a camada primeiro.')
            key='local-'+uuid.uuid4().hex
            clinical=bool(command.get('clinical')) or is_case(command.get('title',''))
            if clinical and not allowed_clinical: raise PermissionError('Camadas de saúde exigem acesso SFA completo.')
            current={'id':key,'title':'','color':'#65bdd2','clinical':clinical,'deleted':False,
                     'origin':{'type':'local','title':'Cadastro da equipe'},'features':[],'revision':0}
            if action=='copy_layer':
                original=layers(allowed_clinical).get(command.get('copy_from'))
                if not original: raise LookupError('Camada de origem não encontrada.')
                current.update(features=deepcopy(original['features']),clinical=original['clinical'],
                               origin={'type':'copy','title':'Cópia de '+original['title']})
            elif action=='copy_sheet':
                if not allowed_clinical: raise PermissionError('A planilha exige acesso SFA completo.')
                from services.entomologia_atlas import live_sheet
                source=live_sheet(atlas.active_earth())
                current.update(clinical=True,origin={'type':'sheet_snapshot','title':'Cópia da planilha',**source['source']})
                current['features']=[{'type':'Feature','id':row['id'],'geometry':row['geometry'],
                    'properties':{'name':f"Planilha · linha {row['source_row']}",
                    **{f:row[f] for f in FIELDS if f in row},'source_row':row['source_row']}}
                    for row in source['records']]
        try: revision=int(command.get('revision',-1))
        except (TypeError,ValueError) as exc: raise ValueError('Versão inválida.') from exc
        if revision!=current['revision']: raise Conflict('Outra pessoa alterou esta camada. Recarregue antes de salvar; seu formulário foi preservado.')
        layer=deepcopy(current)
        if action in ('create_layer','update_layer','copy_layer','copy_sheet'):
            layer['title']=text(command.get('title',''),'name',True)
            color=command.get('color','#65bdd2')
            if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color): raise ValueError('Cor inválida.')
            layer['color']=color
            clinical=layer['clinical'] or bool(command.get('clinical')) or is_case(layer['title'])
            if clinical and not allowed_clinical: raise PermissionError('Camadas de saúde exigem acesso SFA completo.')
            layer['clinical']=clinical
        elif action=='delete_layer': layer['deleted']=True
        elif action=='restore':
            try: rid=int(command.get('restore_revision'))
            except (TypeError,ValueError) as exc: raise ValueError('Revisão inválida.') from exc
            if rid==0:
                original=source_layers().get(key)
                if not original: raise ValueError('Esta camada não tem fonte original.')
                layer=deepcopy(original)
            else:
                old=revision_rows(key).filter_by(id=rid).first()
                if not old: raise ValueError('Revisão não pertence à camada.')
                layer=json.loads(old.dados_json)
            layer['clinical']=layer['clinical'] or current['clinical']
        elif action in ('create_feature','update_feature','delete_feature'):
            if layer['deleted']: raise ValueError('Restaure a camada antes de editar os registros.')
            items=layer['features']
            fid=str(command.get('feature_id',''))
            previous=next((f for f in items if str(f['id'])==fid),None)
            if action!='create_feature' and previous is None: raise LookupError('Registro não encontrado.')
            if action=='create_feature':
                if len(items)>=5000: raise ValueError('Limite de 5.000 registros por camada.')
                items.append(clean_feature(command.get('feature')))
            elif action=='update_feature':
                items[items.index(previous)]=clean_feature(command.get('feature'),previous)
            else: items.remove(previous)
        else: raise ValueError('Ação inválida.')
        if len({str(f['id']) for f in layer['features']})!=len(layer['features']):
            raise ValueError('Há identificadores repetidos. Confira a fonte.')
        layer.pop('revision',None);layer.pop('updated_at',None)
        encoded=dumps(layer)
        if len(encoded.encode())>15_000_000: raise ValueError('Camada maior que 15 MB.')
        revision_rows(key).filter_by(status='ATIVA').order_by(None).update({'status':'DESFEITA'},synchronize_session=False)
        now=utcnow()
        entry=E(tipo=TIPO,status='ATIVA',titulo=key,nome_arquivo='Edição no atlas',sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                linhas=len(layer['features']),dados_json=encoded,resumo_json=dumps({'action':action,'reason':reason,'previous':revision}),
                responsavel=actor[:160],ator=actor[:160],confirmado_em=now)
        db.session.add(entry);db.session.flush()
        _auditar('atlas_editar','Camada do atlas revisada',{'layer_id':key,'revision':entry.id,'previous':revision,'action':action})
        db.session.commit()
        return {**layer,'revision':entry.id,'updated_at':now.isoformat()}

def history(key, allowed_clinical):
    layer=layers(allowed_clinical,True).get(key)
    if not layer: raise LookupError('Camada não encontrada.')
    return [{'revision':r.id,'at':r.confirmado_em.isoformat(),'actor':r.ator,
             **json.loads(r.resumo_json)} for r in revision_rows(key).limit(100).all()]

def search_text(value):
    value=normalize(value)
    for ten,prefix in ((20,'vinte'),(30,'trinta')):
        for n,word in enumerate('um dois tres quatro cinco seis sete oito nove'.split(),1):
            value=re.sub(r'\b(rua|avenida|alameda|travessa) '+prefix+' e '+word+r'\b',lambda m:m[1]+' '+str(ten+n),value)
    value=re.sub(r'\bav\.?\s','avenida ',value)
    for n,word in enumerate('um dois tres quatro cinco seis sete oito nove dez onze doze treze quatorze quinze'.split(),1):
        value=re.sub(r'\b(rua|avenida|alameda|travessa) '+word+r'\b',lambda m:m[1]+' '+str(n),value)
    for n,word in {16:'dezesseis',17:'dezessete',18:'dezoito',19:'dezenove',20:'vinte',30:'trinta',100:'cem',102:'cento e dois'}.items():
        value=re.sub(r'\b(rua|avenida|alameda|travessa) '+word+r'\b',lambda m:m[1]+' '+str(n),value)
    value=re.sub(r'\b(rua|avenida|alameda|travessa|casa) 0*(\d+)\b',lambda m:m[1]+' '+str(int(m[2])),value)
    return value

def search(query, allowed_clinical):
    """Local data only: no query, patient address or identifier sent to a provider."""
    q=search_text(query)
    if not q or len(q)>240: return []
    q=re.sub(r'\bav\.?\s','avenida ',q)
    pattern=r'\b(?:rua|avenida|alameda|travessa|casa) \d+[a-z]?\b'
    phrases=re.findall(pattern,q)
    tokens=re.sub(pattern,' ',q).replace(',',' ').split()
    result=[]
    grouped={}
    for layer in layers(allowed_clinical).values():
        for f in layer['features']:
            p=f['properties']
            hay=search_text(' '.join(str(p.get(k,'')) for k in ('name','label','address','category')))
            if all(re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',hay) for t in phrases) and all(
                    re.search(r'(?<!\d)'+re.escape(t)+r'(?!\d)',hay) if t.isdigit() else t in hay for t in tokens):
                identity=(layer['id'],normalize(p.get('name') or p.get('label')))
                if layer['origin']['type']=='reference' and identity in grouped:
                    base=grouped[identity]['feature']
                    if base['geometry']['type']!='GeometryCollection':
                        base['geometry']={'type':'GeometryCollection','geometries':[base['geometry']]}
                    base['geometry']['geometries'].append(deepcopy(f['geometry']))
                    continue
                item={'layer_id':layer['id'],'layer_title':layer['title'],'feature':deepcopy(f),
                               'located':f.get('geometry') is not None}
                grouped[identity]=item
                result.append(item)
    return result[:80]
