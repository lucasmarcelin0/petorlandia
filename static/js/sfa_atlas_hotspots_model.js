(function(root){
  'use strict';
  const norm=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
  function kind(title){const n=norm(title);return n==='larvas'?'larvae':n==='casos dengue'?'cases':null;}
  function qualifies(f,k){if(f.geometry?.type!=='Point')return false;if(k==='larvae')return true;
    const p=f.properties||{},status=norm(p.final_result||p.classification||p.exam_result||p.status||p.folder_status);
    return /\b(positivo|positivos|confirmado|confirmados)\b/.test(status)&&!/negativ|descart|suspeit|pendente/.test(status);
  }
  function ringContains(point,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const [x,y]=point,[xi,yi]=ring[i],[xj,yj]=ring[j],cross=(x-xi)*(yj-yi)-(y-yi)*(xj-xi);
    if(Math.abs(cross)<1e-12&&x>=Math.min(xi,xj)&&x<=Math.max(xi,xj)&&y>=Math.min(yi,yj)&&y<=Math.max(yi,yj))return true;
    if((yi>y)!==(yj>y)&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)inside=!inside;
  }return inside;}
  const contains=(p,g)=>(g.type==='Polygon'?[g.coordinates]:g.type==='MultiPolygon'?g.coordinates:[]).some(rings=>ringContains(p,rings[0])&&!rings.slice(1).some(r=>ringContains(p,r)));
  function index(blocks){const cells=new Map(),size=.002,key=p=>Math.floor(p[0]/size)+':'+Math.floor(p[1]/size);
    blocks.forEach(block=>{const g=block.geometry;if(!g||!['Polygon','MultiPolygon'].includes(g.type))return;
      const points=g.type==='Polygon'?g.coordinates.flat():g.coordinates.flat(2),xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
      for(let x=Math.floor(Math.min(...xs)/size);x<=Math.floor(Math.max(...xs)/size);x++)for(let y=Math.floor(Math.min(...ys)/size);y<=Math.floor(Math.max(...ys)/size);y++){
        const k=x+':'+y;if(!cells.has(k))cells.set(k,[]);cells.get(k).push(block);
      }
    });return {match(point){return (cells.get(key(point))||[]).filter(b=>contains(point,b.geometry));}};
  }
  function aggregate(rows,spatial){const groups=new Map(),seen=new Set();let located=0,outside=0;
    rows.forEach(row=>{if(seen.has(row.key))return;seen.add(row.key);const coords=row.feature.geometry?.coordinates;
      if(row.feature.geometry?.type!=='Point'||!coords){outside++;return;}
      const matches=spatial.match(coords);if(matches.length!==1){outside++;return;}
      const block=matches[0];if(!groups.has(block.id))groups.set(block.id,{block,larvae:0,cases:0,items:[]});
      const entry=groups.get(block.id);entry[row.kind]++;entry.items.push(row);located++;
    });return {blocks:[...groups.values()],located,outside};
  }
  const api={kind,qualifies,contains,index,aggregate};root.SfaAtlasHotspotsModel=api;if(typeof module==='object')module.exports=api;
})(typeof window==='object'?window:globalThis);
