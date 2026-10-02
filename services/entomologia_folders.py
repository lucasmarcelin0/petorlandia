"""Folder trees within audited atlas layers; no cross-layer permission inheritance."""
from copy import deepcopy
import hashlib
import re
import uuid

MAX_DEPTH=12

def node_paths(nodes):
    by_id={n['id']:n for n in nodes}
    if len(by_id)!=len(nodes):raise ValueError('Identificadores de pastas repetidos.')
    paths={}
    def path(key,seen=()):
        if not key:return []
        if key not in by_id:raise ValueError('Pasta superior inexistente nesta camada.')
        if key in seen or len(seen)>=MAX_DEPTH:raise ValueError('A organização contém um ciclo ou níveis demais.')
        if key not in paths:
            node=by_id[key]
            paths[key]=path(node.get('parent_id',''),seen+(key,))+[node['name']]
        return paths[key]
    for key in by_id:path(key)
    return paths

def descendants(nodes,key):
    found={key};changed=True
    while changed:
        extra={n['id'] for n in nodes if n.get('parent_id','') in found}
        changed=not extra<=found;found|=extra
    return found

def ensure(layer):
    """Upgrade flat legacy categories once; derive displayed paths from the tree."""
    if 'folders' not in layer:
        layer['folders']=[]
        categories={f.get('properties',{}).get('category','') for f in layer['features']} - {''}
        for name in sorted(categories):
            key='category-'+hashlib.sha256((layer['id']+'\0'+name).encode()).hexdigest()[:20]
            layer['folders'].append({'id':key,'parent_id':'','name':name[:120]})
            for f in layer['features']:
                if f['properties'].get('category')==name:f['properties']['folder_id']=key
    paths=node_paths(layer['folders'])
    for feature in layer['features']:
        p=feature.setdefault('properties',{})
        key=p.get('folder_id','')
        if key not in paths:key=''
        p['folder_id']=key;p['folder_path']=[layer['title']]+paths.get(key,[])
    return layer

def upgrade_revision(layer,source):
    """Restore metadata lost by old imports, while keeping edits and deletions."""
    if source:layer['clinical']=layer.get('clinical',False) or source.get('clinical',False)
    if source and layer.get('origin',{}).get('type')=='earth':
        original={str(f['id']):f for f in source['features']}
        if 'folders' not in layer:layer['folders']=deepcopy(source.get('folders',[]))
        for f in layer['features']:
            new=original.get(str(f['id']))
            if not new:continue
            p=f['properties']
            for field in ('folder_id','folder_path','address','address_origin','date','date_origin',
                          'period_year','sector','source_coordinates','source_month','position_status','precision'):
                if field not in p and field in new['properties']:p[field]=deepcopy(new['properties'][field])
            if (not p.get('name') or p.get('name')==p.get('label')) and re.search(r' · marcador \d+$',p.get('label','')):
                p['name']=new['properties'].get('name',p['label']);p['label']=p['name']
            if f.get('geometry')!=new.get('geometry') and p.get('position_status')=='imported':
                p['position_status']='to_review'
    return ensure(layer)

def apply(layer,command,text,clinical_allowed,is_case):
    if layer['deleted']:raise ValueError('Restaure a camada antes de organizar as pastas.')
    ensure(layer)
    action=command['action'];nodes=layer['folders'];key=str(command.get('folder_id',''))
    if action in ('create_folder','update_folder'):
        name=text(command.get('name',''),'category',True)
        parent=text(command.get('parent_id',''),'folder_id')
        if is_case(name):
            if not clinical_allowed:raise PermissionError('Pastas de saúde exigem acesso SFA completo.')
            layer['clinical']=True
        if parent and parent not in {n['id'] for n in nodes}:raise ValueError('Pasta superior inexistente nesta camada.')
        if action=='create_folder':
            if len(nodes)>=500:raise ValueError('Limite de 500 pastas por camada.')
            node={'id':'folder-'+uuid.uuid4().hex,'name':name,'parent_id':parent};nodes.append(node)
        else:
            node=next((n for n in nodes if n['id']==key),None)
            if not node:raise LookupError('Pasta não encontrada.')
            node.update(name=name,parent_id=parent)
        node_paths(nodes)
    elif action=='delete_folder':
        if not any(n['id']==key for n in nodes):raise LookupError('Pasta não encontrada.')
        if any(n.get('parent_id','')==key for n in nodes) or any(f['properties'].get('folder_id','')==key for f in layer['features']):
            raise ValueError('A pasta contém registros ou subpastas. Mova-os antes de excluir a pasta vazia.')
        layer['folders']=[n for n in nodes if n['id']!=key]
    elif action=='move_features':
        ids=command.get('feature_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=500 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('Selecione entre 1 e 500 registros distintos.')
        if key and key not in {n['id'] for n in nodes}:raise ValueError('Pasta de destino inexistente nesta camada.')
        features={str(f['id']):f for f in layer['features']}
        if not set(ids)<=features.keys():raise LookupError('Um registro selecionado não existe nesta camada.')
        for fid in ids:features[fid]['properties']['folder_id']=key
    else:raise ValueError('Ação de pasta inválida.')
    ensure(layer)

def validate_feature_folder(feature,layer):
    key=feature['properties'].get('folder_id','')
    if key and key not in {n['id'] for n in layer.get('folders',[])}:
        raise ValueError('Escolha uma pasta desta camada.')
    state=feature['properties'].get('position_status','to_review')
    if state not in ('imported','estimated','to_review','verified','unlocated'):
        raise ValueError('Conferência da posição inválida.')
    feature['properties']['position_status']=state if feature.get('geometry') else 'unlocated'

def folder_counts(layer):
    counts={n['id']:0 for n in layer.get('folders',[])}
    for f in layer['features']:
        key=f['properties'].get('folder_id','')
        if key in counts:counts[key]+=1
    return [{**n,'direct_count':counts[n['id']]} for n in layer.get('folders',[])]
