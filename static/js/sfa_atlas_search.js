(function(){
  'use strict';const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.SfaAtlasSearch={attach(map,dataset,territory,{select,fit,areaName,addStop}){
    const input=$('field-search'),panel=$('atlas-search-panel'),results=$('atlas-search-results'),status=$('atlas-search-status'),preview=L.layerGroup().addTo(map);
    const urls=dataset.editor_urls,Model=window.SfaAtlasSearchModel;
    let run=0,timer=null,controller=null,index=null,indexState='idle',placeRun=0;
    const highlight={style:{color:'#fff',weight:5,fillOpacity:.2},pointToLayer:(_,coords)=>L.circleMarker(coords,{radius:10,color:'#fff',fillColor:'#087f81',fillOpacity:1})};

    function open(value){panel.hidden=!value;input.setAttribute('aria-expanded',String(value));}
    function clear(){run++;placeRun++;clearTimeout(timer);controller?.abort();preview.clearLayers();input.value='';results.replaceChildren();open(false);}
    function section(title){const h=document.createElement('h4');h.textContent=title;results.append(h);}
    // `stop` (opcional): descreve o local para o botão "＋ Rota". Fica ao lado do resultado, nunca dentro dele.
    function button(title,note,action,stop){
      const b=document.createElement('button');b.type='button';b.innerHTML='<strong>'+esc(title)+'</strong><small>'+esc(note)+'</small>';b.onclick=action;
      if(!(stop&&addStop)){results.append(b);return;}
      const row=document.createElement('div');row.className='atlas-result-row';row.append(b);
      const add=document.createElement('button');add.type='button';add.className='atlas-result-route';add.textContent='＋ Rota';
      add.title='Adicionar à rota de campo';add.setAttribute('aria-label','Adicionar '+title+' à rota de campo');
      add.onclick=e=>{e.stopPropagation();addStop(stop,add);};
      row.append(add);results.append(row);
    }

    // ---- Quadras e setores: sempre locais ----
    function territoryMatches(query){
      const matches=window.SfaFieldMapModel.filter(territory.features,{district:'',sector:'',search:query});
      let count=0;
      if(matches.length){section('Quadras e setores');
        if(matches.length>1){button('Enquadrar '+matches.length+' quadras','Território correspondente a “'+query+'”',()=>{fit(matches);open(false);});count++;}
        matches.slice(0,12).forEach(f=>{
          button('Quadra '+f.properties.block+' · SC '+f.properties.sector,areaName(f.properties.district),()=>{select(f,true);open(false);},
            {name:'Quadra '+f.properties.block+' · SC '+f.properties.sector,note:areaName(f.properties.district),feature:f});count++;
        });
      }
      return count;
    }

    // ---- Índice local: resposta imediata, sem rede ----
    function loadIndex(){
      if(indexState!=='idle'||!urls.search_index||!Model)return;
      indexState='loading';
      // Sem `cache:`: o navegador revalida com a etiqueta (ETag) quando o servidor permite.
      fetch(urls.search_index,{credentials:'same-origin'}).then(r=>{
        if(!r.ok||!r.headers.get('content-type')?.includes('application/json'))throw Error('índice indisponível');
        return r.json();
      }).then(data=>{
        index=data;indexState='ready';
        // A busca em andamento no servidor perde para a local, que é imediata.
        if(input.value.trim()){run++;controller?.abort();clearTimeout(timer);localSearch(input.value.trim());}
      }).catch(()=>{indexState='failed';});
    }
    const where=e=>e[5]===1?'Ponto cadastrado':e[5]===2?'Trecho / referência no mapa':'Sem posição · consultar cadastro';
    function stopFor(e,layer){return {name:e[2],note:[e[3],layer.title].filter(Boolean).join(' · '),kind:e[5],x:e[6],y:e[7],bbox:e[8],layerId:layer.id,featureId:e[1]};}

    function showPlace(entry){
      const layer=index.layers[entry[0]],mine=++placeRun;preview.clearLayers();
      if(entry[5]===1){
        L.geoJSON({type:'Feature',geometry:{type:'Point',coordinates:[entry[6],entry[7]]},properties:{}},highlight).addTo(preview);
        map.fitBounds(L.latLngBounds([[entry[7],entry[6]],[entry[7],entry[6]]]),{padding:[45,45],maxZoom:19});
        map.fire('atlasfocusfeature',{layerId:layer.id,featureId:entry[1]});open(false);return;
      }
      if(entry[5]===2){
        // Enquadra já pelo retângulo conhecido; o traçado exato chega logo depois.
        const b=entry[8],box=L.latLngBounds([[b[1],b[0]],[b[3],b[2]]]);
        const temp=L.rectangle(box,{color:'#fff',weight:3,dashArray:'6 6',fillOpacity:.12}).addTo(preview);
        map.fitBounds(box,{padding:[45,45],maxZoom:19});
        map.fire('atlasfocusfeature',{layerId:layer.id,featureId:entry[1]});open(false);
        fetch(urls.search_place+(urls.search_place.includes('?')?'&':'?')+'layer='+encodeURIComponent(layer.id)+'&feature='+encodeURIComponent(entry[1]),{credentials:'same-origin',cache:'no-store'})
          .then(r=>{if(!r.ok)throw Error();return r.json();})
          .then(item=>{if(mine!==placeRun)return;preview.removeLayer(temp);L.geoJSON(item.feature,highlight).addTo(preview);})
          .catch(()=>{});
        return;
      }
      if(entry[9]){window.SfaCadastreViewer.open(dataset,entry[9],layer.id,entry[1]);open(false);return;}
      const b=document.createElement('button');b.type='button';b.dataset.atlasLayer=layer.id;b.dataset.atlasFeature=entry[1];b.hidden=true;document.body.append(b);b.click();b.remove();open(false);
    }

    function localSearch(query){
      const seq=++run;controller?.abort();preview.clearLayers();results.replaceChildren();open(true);
      let count=territoryMatches(query);
      const found=Model.search(index,query);
      if(found.length)section('Endereços e locais');
      found.forEach(e=>{
        const layer=index.layers[e[0]];
        button(e[2],[e[3],layer.title,where(e)].filter(Boolean).join(' · '),()=>showPlace(e),e[5]?stopFor(e,layer):undefined);count++;
      });
      if(seq===run)status.textContent=count?count+' opções · selecione para localizar ou consultar':'Nenhuma correspondência. Tente o nome da rua ou da quadra. Números sem cadastro não recebem posição estimada.';
    }

    // ---- Reserva: consulta ao servidor (comportamento anterior) ----
    async function serverSearch(){
      const query=input.value.trim(),seq=++run;controller?.abort();preview.clearLayers();results.replaceChildren();
      if(!query){open(false);return;}open(true);status.textContent='Buscando no atlas…';
      let count=territoryMatches(query);
      try{
        controller=new AbortController();const response=await fetch(urls.search+(urls.search.includes('?')?'&':'?')+'q='+encodeURIComponent(query),{credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('Não foi possível consultar os endereços. As quadras continuam disponíveis.');
        const data=await response.json();if(seq!==run)return;
        if(data.results.length)section('Endereços e locais');
        data.results.forEach(item=>{
          const f=item.feature,p=f.properties;
          button(p.name||p.label||item.layer_title,[p.address,item.layer_title,item.located?(f.geometry.type==='Point'?'Ponto cadastrado':'Trecho / referência no mapa'):'Sem posição · consultar cadastro'].filter(Boolean).join(' · '),()=>{
            preview.clearLayers();
            if(f.geometry){const layer=L.geoJSON(f,highlight).addTo(preview);const bounds=layer.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[45,45],maxZoom:19});map.fire('atlasfocusfeature',{layerId:item.layer_id,featureId:f.id});open(false);}
            else if(p.cadastre_ref){window.SfaCadastreViewer.open(dataset,p.cadastre_ref,item.layer_id,f.id);open(false);}
            else{const b=document.createElement('button');b.type='button';b.dataset.atlasLayer=item.layer_id;b.dataset.atlasFeature=f.id;b.hidden=true;document.body.append(b);b.click();b.remove();open(false);}
          });count++;
        });
        status.textContent=count?count+' opções · selecione para localizar ou consultar':'Nenhuma correspondência. Tente o nome da rua ou da quadra. Números sem cadastro não recebem posição estimada.';
      }catch(e){if(e.name!=='AbortError'&&seq===run)status.textContent=e.message;}
    }

    function search(){
      if(!input.value.trim()){open(false);return;}
      if(index)localSearch(input.value.trim());else{loadIndex();serverSearch();}
    }
    $('field-filters').onsubmit=e=>{e.preventDefault();clearTimeout(timer);search();};
    input.oninput=()=>{
      run++;controller?.abort();clearTimeout(timer);
      if(!input.value.trim()){clear();return;}
      if(index){localSearch(input.value.trim());return;}   // imediato: sem espera e sem rede
      loadIndex();timer=setTimeout(serverSearch,400);       // enquanto o índice não chega
    };
    input.onfocus=loadIndex;
    // Baixa o índice logo depois que a tela termina de carregar, antes de alguém digitar.
    (window.requestIdleCallback||(fn=>setTimeout(fn,600)))(loadIndex);
    input.onkeydown=e=>{if(e.key==='Escape'){run++;controller?.abort();open(false);}if(e.key==='ArrowDown'){const b=results.querySelector('button');if(b){e.preventDefault();b.focus();}}};
    panel.onkeydown=e=>{if(e.key==='Escape'){open(false);input.focus();}};
    function close(){run++;clearTimeout(timer);controller?.abort();open(false);}
    $('atlas-search-close').onclick=()=>{close();input.focus();};
    document.addEventListener('pointerdown',e=>{if(!e.target.closest('.field-search'))close();});
    return {clear};
  }};
})();
