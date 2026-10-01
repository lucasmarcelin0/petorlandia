"""Local, reviewable spatial checks. Never reverse-geocode or snap homes silently."""
from collections import Counter,defaultdict
from functools import lru_cache
from pathlib import Path
import json,math,re

CELL=.001
MX=111320*math.cos(math.radians(-20.72));MY=111320

def cells(bounds):
    a,b,c,d=bounds
    return ((x,y) for x in range(math.floor(a/CELL),math.floor(c/CELL)+1)
                  for y in range(math.floor(b/CELL),math.floor(d/CELL)+1))

def distance_segment(point,a,b):
    px,py=point[0]*MX,point[1]*MY;ax,ay=a[0]*MX,a[1]*MY;bx,by=b[0]*MX,b[1]*MY
    dx,dy=bx-ax,by-ay
    t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(px-ax-t*dx,py-ay-t*dy)

def in_ring(point,ring):
    x,y=point;odd=False
    for a,b in zip(ring,ring[1:]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:odd=not odd
    return odd

@lru_cache(maxsize=1)
def reference_index():
    from services.entomologia_atlas_editor import references,condominiums,search_text,DATA
    roads=[];grid=defaultdict(list);by_name=defaultdict(list)
    for f in references()['features']:
        g=f.get('geometry',{});p=f['properties']
        lines=[g['coordinates']] if g.get('type')=='LineString' else g.get('coordinates',[]) if g.get('type')=='MultiLineString' else []
        for line in lines:
            for a,b in zip(line,line[1:]):
                index=len(roads);roads.append((a,b,p.get('name') or p.get('label','')))
                by_name[search_text(roads[-1][2])].append(index)
                box=(min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1]))
                for cell in cells(box):grid[cell].append(index)
    territory=json.loads((DATA.parent/'territory.json').read_text(encoding='utf-8'))
    blocks=[];block_grid=defaultdict(list);wide=[]
    for f in territory['features']:
        g=f['geometry'];polygons=g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']] if g['type']=='Polygon' else []
        for rings in polygons:
            ring=rings[0];xs=[p[0] for p in ring];ys=[p[1] for p in ring]
            box=(min(xs),min(ys),max(xs),max(ys));index=len(blocks);blocks.append((rings,f['properties']))
            if (box[2]-box[0])*(box[3]-box[1])>CELL*CELL*400:wide.append(index)
            else:
                for cell in cells(box):block_grid[cell].append(index)
    xs=[p[0] for rings,_ in blocks for p in rings[0]];ys=[p[1] for rings,_ in blocks for p in rings[0]]
    return {'roads':roads,'grid':grid,'by_name':by_name,'keys':sorted(by_name,key=len,reverse=True),
            'blocks':blocks,'block_grid':block_grid,'wide':wide,'bounds':(min(xs),min(ys),max(xs),max(ys)),
            'houses':condominiums()['features']}

def assess(feature,houses=None):
    from services.entomologia_atlas_editor import search_text
    p=feature['properties'];g=feature.get('geometry');issues=[]
    output={'id':str(feature['id']),'name':p.get('name') or p.get('label',''),'address':p.get('address',''),
            'position_status':p.get('position_status','imported'),'issues':issues,'nearest_road':None,
            'declared_road':None,'blocks':[],'house_candidate':None}
    if not output['address']:issues.append('Endereço não informado')
    if not g:issues.append('Sem posição');return output
    if g['type']!='Point':output['geometry_note']='Área ou trajeto: confira o contorno no satélite';return output
    point=g['coordinates'];index=reference_index();x,y=math.floor(point[0]/CELL),math.floor(point[1]/CELL)
    nearby=set(i for dx in range(-3,4) for dy in range(-3,4) for i in index['grid'].get((x+dx,y+dy),[]))
    if nearby:
        distance,rid=min((distance_segment(point,*index['roads'][i][:2]),i) for i in nearby)
        output['nearest_road']={'name':index['roads'][rid][2],'distance_m':round(distance,1)}
    normalized=search_text(output['address'])
    road_key=next((key for key in index['keys'] if normalized==key or normalized.startswith(key+' ') or normalized.startswith(key+',')),None)
    if road_key:
        distance,rid=min((distance_segment(point,*index['roads'][i][:2]),i) for i in index['by_name'][road_key])
        output['declared_road']={'name':index['roads'][rid][2],'distance_m':round(distance,1)}
        if distance>60:issues.append('Ponto distante do logradouro informado')
    elif output['address'] and not re.search(r'\b(?:quebec|torino)\b',normalized):
        issues.append('Logradouro sem correspondência na base local')
    a,b,c,d=index['bounds']
    if not a-.004<=point[0]<=c+.004 or not b-.004<=point[1]<=d+.004:issues.append('Fora do entorno do território cadastrado')
    for bid in set(index['block_grid'].get((x,y),[])+index['wide']):
        rings,bp=index['blocks'][bid]
        if in_ring(point,rings[0]) and not any(in_ring(point,r) for r in rings[1:]):
            output['blocks'].append({'block':bp['block'],'sector':bp['sector']})
    if str(p.get('sector','')).isdigit() and output['blocks'] and not any(int(block['sector'])==int(p['sector']) for block in output['blocks']):
        issues.append('Setor da pasta diverge da quadra que contém o ponto')
    condo=re.search(r'\b(quebec|torino)\b',normalized);house=re.search(r'\bcasa\s+(\d+)\b',normalized)
    if condo and house:
        matches=[f for f in (index['houses'] if houses is None else houses) if (f.get('geometry') or {}).get('type')=='Point' and f['properties']['condominium'].lower()==condo[1] and int(f['properties']['house_number'])==int(house[1])]
        alameda=re.search(r'\balameda\s+(\d+)\b',normalized)
        if len(matches)==1 and (not alameda or int(matches[0]['properties']['street'].split()[-1])==int(alameda[1])):
            f=matches[0]
            output['house_candidate']={'address':f['properties']['address'],'coordinates':f['geometry']['coordinates'],
                'precision':('Referência da casa cadastrada no atlas. '+f['properties'].get('precision',''))[:240],
                'reference_position_status':f['properties'].get('position_status','estimated'),
                'position_status':'estimated' if f['properties'].get('position_status','estimated')=='estimated' else 'to_review'}
    original=p.get('source_coordinates')
    if isinstance(original,list) and len(original)==2:
        output['moved_from_source_m']=round(math.hypot((point[0]-original[0])*MX,(point[1]-original[1])*MY),1)
    output['note']='Rua próxima e quadra ajudam a conferir. Não identificam automaticamente a entrada nem o número do imóvel.'
    return output

def review(layer,feature_id=None,houses=None):
    features=layer['features']
    if feature_id:
        features=[f for f in features if str(f['id'])==feature_id]
        if not features:raise LookupError('Registro não encontrado.')
    records=[assess(f,houses) for f in features]
    coincident=Counter(tuple(f['geometry']['coordinates']) for f in features if (f.get('geometry') or {}).get('type')=='Point')
    for f,row in zip(features,records):
        if (f.get('geometry') or {}).get('type')=='Point':row['coincident_records']=coincident[tuple(f['geometry']['coordinates'])]
    return {'records':records,'summary':{'records':len(records),'with_address':sum(bool(r['address']) for r in records),
        'with_issues':sum(bool(r['issues']) for r in records),'verified':sum(r['position_status']=='verified' for r in records),
        'issues':dict(Counter(issue for r in records for issue in r['issues']))},
        'source_note':'Conferência local com ruas OSM, quadras operacionais e croquis dos condomínios. Referências a conferir no campo.'}
