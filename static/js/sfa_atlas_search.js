(function(){
  'use strict';const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.SfaAtlasSearch={attach(map,dataset,territory,{select,fit,areaName}){
    const input=$('field-search'),panel=$('atlas-search-panel'),results=$('atlas-search-results'),status=$('atlas-search-status'),preview=L.layerGroup().addTo(map);
    let run=0,timer=null,controller=null;
    function open(value){panel.hidden=!value;input.setAttribute('aria-expanded',String(value));}
    function clear(){run++;clearTimeout(timer);controller?.abort();preview.clearLayers();input.value='';results.replaceChildren();open(false);}
    function section(title){const h=document.createElement('h4');h.textContent=title;results.append(h);}
    function button(title,note,action){const b=document.createElement('button');b.type='button';b.innerHTML='<strong>'+esc(title)+'</strong><small>'+esc(note)+'</small>';b.onclick=action;results.append(b);}
    async function search(){
      const query=input.value.trim(),seq=++run;controller?.abort();preview.clearLayers();results.replaceChildren();
      if(!query){open(false);return;}open(true);status.textContent='Buscando no atlas…';
      const matches=window.SfaFieldMapModel.filter(territory.features,{district:'',sector:'',search:query});
      let count=0;
      if(matches.length){section('Quadras e setores');
        if(matches.length>1){button('Enquadrar '+matches.length+' quadras','Território correspondente a “'+query+'”',()=>{fit(matches);open(false);});count++;}
        matches.slice(0,12).forEach(f=>{button('Quadra '+f.properties.block+' · SC '+f.properties.sector,areaName(f.properties.district),()=>{select(f,true);open(false);});count++;});
      }
      try{
        controller=new AbortController();const response=await fetch(dataset.editor_urls.search+(dataset.editor_urls.search.includes('?')?'&':'?')+'q='+encodeURIComponent(query),{credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('Não foi possível consultar os endereços. As quadras continuam disponíveis.');
        const data=await response.json();if(seq!==run)return;
        if(data.results.length)section('Endereços e locais');
        data.results.forEach(item=>{
          const f=item.feature,p=f.properties;
          button(p.name||p.label||item.layer_title,[p.address,item.layer_title,item.located?(f.geometry.type==='Point'?'Ponto cadastrado':'Trecho / referência no mapa'):'Sem posição · consultar cadastro'].filter(Boolean).join(' · '),()=>{
            preview.clearLayers();
            if(f.geometry){const layer=L.geoJSON(f,{style:{color:'#fff',weight:5,fillOpacity:.2},pointToLayer:(_,coords)=>L.circleMarker(coords,{radius:10,color:'#fff',fillColor:'#087f81',fillOpacity:1})}).addTo(preview);const bounds=layer.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[45,45],maxZoom:19});map.fire('atlasfocusfeature',{layerId:item.layer_id,featureId:f.id});open(false);}
            else if(p.cadastre_ref){window.SfaCadastreViewer.open(dataset,p.cadastre_ref,item.layer_id,f.id);open(false);}
            else{const b=document.createElement('button');b.type='button';b.dataset.atlasLayer=item.layer_id;b.dataset.atlasFeature=f.id;b.hidden=true;document.body.append(b);b.click();b.remove();open(false);}
          });count++;
        });
        status.textContent=count?count+' opções · selecione para localizar ou consultar':'Nenhuma correspondência. Tente o nome da rua ou da quadra. Números sem cadastro não recebem posição estimada.';
      }catch(e){if(e.name!=='AbortError'&&seq===run)status.textContent=e.message;}
    }
    $('field-filters').onsubmit=e=>{e.preventDefault();clearTimeout(timer);search();};
    input.oninput=()=>{run++;controller?.abort();clearTimeout(timer);if(!input.value.trim())clear();else timer=setTimeout(search,400);};
    input.onkeydown=e=>{if(e.key==='Escape'){run++;controller?.abort();open(false);}if(e.key==='ArrowDown'){const b=results.querySelector('button');if(b){e.preventDefault();b.focus();}}};
    panel.onkeydown=e=>{if(e.key==='Escape'){open(false);input.focus();}};
    function close(){run++;clearTimeout(timer);controller?.abort();open(false);}
    $('atlas-search-close').onclick=()=>{close();input.focus();};
    document.addEventListener('pointerdown',e=>{if(!e.target.closest('.field-search'))close();});
    return {clear};
  }};
})();
