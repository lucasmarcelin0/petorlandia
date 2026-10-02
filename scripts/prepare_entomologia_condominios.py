"""Transcribe the public condominium plans onto the existing operational blocks.

These are estimated cartographic label positions, not surveyed entrances.
No resident, patient, owner or occupancy data is used.
"""
import hashlib
import json
from pathlib import Path

def bilinear(corners,u,v):
    nw,ne,sw,se=corners
    return [round((1-v)*((1-u)*nw[k]+u*ne[k])+v*((1-u)*sw[k]+u*se[k]),8) for k in (0,1)]

def along(a,b,t):
    return [a[k]+t*(b[k]-a[k]) for k in (0,1)]

def intersection(a,b,c,d):
    x,y=b[0]-a[0],b[1]-a[1]
    q,r=d[0]-c[0],d[1]-c[1]
    den=x*r-y*q
    t=((c[0]-a[0])*r-(c[1]-a[1])*q)/den
    return along(a,b,t)

def inside(point,ring):
    x,y=point;odd=False
    for a,b in zip(ring,ring[1:]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:odd=not odd
    return odd

def build(root):
    root=Path(root)
    raw=(root/'territory.json').read_bytes()
    territory=json.loads(raw)
    blocks={(f['properties']['sector'],f['properties']['block']):f for f in territory['features']}
    features=[]
    sources=[]
    def add(condo,number,alameda,block,corners,u,v,file,sector,color):
        coords=bilinear(corners,u,v)
        ring=blocks[(sector,block)]['geometry']['coordinates'][0][0]
        if not inside(coords,ring):raise ValueError(f'{condo} {number}: posição fora da quadra {block}')
        features.append({'type':'Feature','id':f'{condo.lower()}-casa-{number}',
          'geometry':{'type':'Point','coordinates':coords},
          'properties':{'layer':f'Casas · Condomínio {condo}','name':f'Casa {number}',
            'label':f'Casa {number}','house_number':str(number),'condominium':condo,
            'kind':'condominium_house','street':f'Alameda {alameda:02d}',
            'address':f'Condomínio {condo}, Alameda {alameda:02d}, Casa {number}',
            'category':f'Alameda {alameda:02d}','block':block,'sector':sector,
            'source_map':file,'source_id':blocks[(sector,block)]['properties']['source_id'],
            'notes':'Numeração e alameda transcritas do mapa original do condomínio.',
            'precision':'Posição cartográfica estimada a partir do croqui e das quadras. Conferir o imóvel e a entrada no campo.',
            'color':color}})
    for condo,sector,file,letters,color in (
        ('Quebec','103','mapa-07.jpg',['899A','899B','899C','899D','899E','899F'],'#147f8c'),
        ('Torino','104','mapa-08.jpg',['900F','900E','900D','900C','900B','900A'],'#9b5362')):
        west=condo=='Quebec'
        def corners(block):
            ring=blocks[(sector,block)]['geometry']['coordinates'][0][0]
            if west:return [ring[0],ring[3],ring[1],ring[2]]
            return [ring[1],ring[0],ring[2],ring[3]]
        def row(numbers,alameda,block,patch,v):
            for index,number in enumerate(numbers):
                u=(index+.5)/14.5
                if not west:u=1-u
                add(condo,number,alameda,block,patch,u,v,file,sector,color)
        # Each paired block has thirteen lots on either side and a leisure bay.
        first=letters[0]
        for nums,alameda,v in ((range(1,14),2,.68),(range(26,13,-1),2,.37),(range(27,40),3,.14)):
            row(list(reversed(list(nums))),alameda,first,corners(first),v)
        for index,start in enumerate((40,66,92),1):
            block=letters[index]
            row(range(start,start+13),index+2,block,corners(block),.75)
            row(range(start+25,start+12,-1),index+3,block,corners(block),.25)
        # Northern block: a paired row plus the eighteen lots along Alameda 07.
        block=letters[4];r=blocks[(sector,block)]['geometry']['coordinates'][0][0]
        if west:
            nw,ne,sw,se=r[1],r[0],r[2],r[3]
            pair_ne=r[4]
            pair_nw=intersection(nw,sw,pair_ne,[pair_ne[k]+sw[k]-se[k] for k in (0,1)])
            pair=[pair_nw,pair_ne,sw,se]
            bar=[nw,ne,along(nw,sw,.23),along(ne,r[5],.65)]
        else:
            nw,ne,sw,se=r[0],r[5],r[3],r[4]
            pair_nw=r[2]
            pair_ne=intersection(ne,se,pair_nw,[pair_nw[k]+se[k]-sw[k] for k in (0,1)])
            pair=[pair_nw,pair_ne,sw,se]
            bar=[nw,ne,along(nw,r[1],.65),along(ne,se,.23)]
        row(range(118,131),6,block,pair,.75)
        row(range(143,130,-1),7,block,pair,.25)
        for index,number in enumerate(range(144,162)):
            u=(index+.5)/18
            if not west:u=1-u
            add(condo,number,7,block,bar,u,.5,file,sector,color)
        # Thirty-six lots on the main internal Alameda 01.
        block=letters[5];r=blocks[(sector,block)]['geometry']['coordinates'][0][0]
        patch=[r[1],r[0],r[2],r[3]] if west else [r[3],r[2],r[0],r[1]]
        for index,number in enumerate(range(162,198)):
            add(condo,number,1,block,patch,.5,(index+.5)/36,file,sector,color)
        numbers=sorted(int(f['properties']['house_number']) for f in features if f['properties']['condominium']==condo)
        if numbers!=list(range(1,198)):raise ValueError('Numeração incompleta ou duplicada')
        sources.append({'condominium':condo,'map':file,'sha256':hashlib.sha256((root/'maps'/file).read_bytes()).hexdigest(),
                        'sector':sector,'houses':197,'color':color,'blocks':letters})
    return {'type':'FeatureCollection','features':features,'source':{'title':'Croquis Quebec e Torino',
            'method':'Transcrição da numeração e interpolação nas quadras operacionais; posições estimadas a conferir.',
            'territory_sha256':hashlib.sha256(raw).hexdigest(),'maps':sources,'houses':394,'contains_resident_data':False}}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=build(args.data)
    args.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')
    print('394 casas transcritas, com coordenadas dentro das quadras e origem registrada.')
