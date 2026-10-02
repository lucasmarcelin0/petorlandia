(function(){
  'use strict';const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let map=null,layer=null,labels=null,current=null,sequence=0,fullBounds=null;
  const dialog=()=>$('atlas-cadastre-dialog');
  function showRecord(id){dialog().close();const b=document.createElement('button');b.type='button';b.dataset.atlasLayer=current.layer;b.dataset.atlasFeature=id;b.hidden=true;document.body.append(b);b.click();b.remove();}
  function drawLabels(){if(!current||!map)return;labels.clearLayers();
    const size=map.getSize(),candidates=current.data.houses.map(h=>{const p=map.latLngToContainerPoint([h.point[1],h.point[0]]);return {h,x:p.x,y:p.y,width:Math.max(28,h.number.length*8+12),height:24,priority:h.id===current.selected?100:1};});
    window.SfaFieldMapModel.placeLabels(candidates,size.x,size.y,3,[...$('atlas-cadastre-map').querySelectorAll('.cadastre-street>span')].map(e=>{const b=e.getBoundingClientRect(),rect=$('atlas-cadastre-map').getBoundingClientRect();return {left:b.left-rect.left-3,right:b.right-rect.left+3,top:b.top-rect.top-3,bottom:b.bottom-rect.top+3};})).forEach(c=>L.marker([c.h.point[1],c.h.point[0]],{icon:L.divIcon({className:'cadastre-number'+(c.h.id===current.selected?' is-selected':''),html:'<span>'+esc(c.h.number)+'</span>',iconSize:[c.width,24],iconAnchor:[c.width/2,12]})}).on('click',()=>showRecord(c.h.id)).addTo(labels));
  }
  window.SfaCadastreViewer={async open(dataset,code,layerId,selected){
    const seq=++sequence;dialog().showModal();$('atlas-cadastre-note').textContent='Carregando croqui…';
    $('atlas-cadastre-close').onclick=()=>{sequence++;dialog().close();};
    try{
      const response=await fetch(dataset.editor_urls.cadastre.replace('CODE',encodeURIComponent(code)),{credentials:'same-origin',cache:'no-store'});
      if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('Não foi possível consultar este croqui.');
      const data=await response.json();if(seq!==sequence||!dialog().open)return;
      current={data,layer:layerId,selected};$('atlas-cadastre-title').textContent='Setor cadastral '+data.sector+' · quadra '+data.block;
      $('atlas-cadastre-note').textContent=data.houses.length+' rótulos de números · '+code+'.dwg · logradouro e localização a conferir';
      if(!map){map=L.map('atlas-cadastre-map',{crs:L.CRS.Simple,minZoom:-5,maxZoom:5,scrollWheelZoom:true});layer=L.layerGroup().addTo(map);labels=L.layerGroup().addTo(map);map.on('zoomend moveend resize',drawLabels);}
      layer.clearLayers();labels.clearLayers();map.invalidateSize();
      const points=[];data.lines.forEach(line=>{const coords=line.map(p=>[p[1],p[0]]);L.polyline(coords,{color:'#80a2a7',weight:1,interactive:false}).addTo(layer);points.push(...coords);});
      data.houses.forEach(h=>{const p=[h.point[1],h.point[0]];points.push(p);L.circleMarker(p,{radius:h.id===selected?6:3,color:'#0c777b',fillOpacity:.7,weight:1}).bindTooltip('Nº '+h.number).on('click',()=>showRecord(h.id)).addTo(layer);});
      data.streets.forEach(s=>{points.push([s.point[1],s.point[0]]);L.marker([s.point[1],s.point[0]],{interactive:false,icon:L.divIcon({className:'cadastre-street',html:'<span>'+esc(s.text)+'</span>',iconSize:[190,32],iconAnchor:[95,38]})}).addTo(layer);});
      if(points.length){fullBounds=L.latLngBounds(points).pad(.08);const focus=data.houses.length?L.latLngBounds(data.houses.map(h=>[h.point[1],h.point[0]])).pad(.22):fullBounds;map.fitBounds(focus,{padding:[55,55],maxZoom:4});}
      const fitButton=$('atlas-cadastre-fit');if(fitButton)fitButton.onclick=()=>fullBounds&&map.fitBounds(fullBounds,{padding:[40,40],maxZoom:4});
      const found=data.houses.find(h=>h.id===selected);if(found)map.setView([found.point[1],found.point[0]],Math.min(5,map.getZoom()+1),{animate:false});drawLabels();
    }catch(e){if(seq===sequence)$('atlas-cadastre-note').textContent=e.message;}
  }};
})();
