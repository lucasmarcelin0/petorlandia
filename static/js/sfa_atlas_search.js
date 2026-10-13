(function(){
  'use strict';const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  window.SfaAtlasSearch={attach(map,dataset,territory,{select,fit,areaName,addStop}){
    const input=$('field-search'),panel=$('atlas-search-panel'),results=$('atlas-search-results'),status=$('atlas-search-status'),preview=L.layerGroup().addTo(map);
    const urls=dataset.editor_urls,Model=window.SfaAtlasSearchModel;
    let run=0,timer=null,controller=null,index=null,indexState='idle',placeRun=0,failures=0,failedAt=0,loadingSince=0;
    const WAIT_MS=2000;   // índice a caminho por mais que isso: o servidor responde, a partir do índice já pronto
    const RETRY_MS=[3000,8000,20000,45000];
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
      // Falhou antes (servidor ocupado, rede)? Tenta de novo depois de alguns segundos, em vez de ficar sem a busca instantânea.
      if(indexState==='failed'&&Date.now()-failedAt>5000)indexState='idle';
      if(indexState!=='idle'||!urls.search_index||!Model)return;
      indexState='loading';loadingSince=Date.now();
      const guard=new AbortController(),giveUp=setTimeout(()=>guard.abort(),28000);
      // Sem `cache:`: o navegador revalida com a etiqueta (ETag) quando o servidor permite.
      fetch(urls.search_index,{credentials:'same-origin',signal:guard.signal}).then(r=>{
        if(!r.ok||!r.headers.get('content-type')?.includes('application/json'))throw Error('índice indisponível');
        return r.json();
      }).then(data=>{
        clearTimeout(giveUp);index=data;indexState='ready';failures=0;
        // A busca em andamento no servidor perde para a local, que é imediata.
        if(input.value.trim()){run++;controller?.abort();clearTimeout(timer);localSearch(input.value.trim());}
      }).catch(()=>{
        clearTimeout(giveUp);indexState='failed';failedAt=Date.now();
        if(failures<RETRY_MS.length)setTimeout(()=>{if(indexState==='failed'){indexState='idle';loadIndex();}},RETRY_MS[failures++]);
        // Quem já estava esperando o índice passa a ser atendido pelo servidor (só agora: antes, cada tecla gerava uma consulta pesada).
        if(!index&&input.value.trim()&&!panel.hidden)serverSearch();
      });
    }
    const where=e=>e[5]===1?'Ponto cadastrado':e[5]===2?'Trecho / referência no mapa':'Sem posição · consultar cadastro';
    function stopFor(e,layer){return {name:e[2],note:[e[3],layer.title].filter(Boolean).join(' · '),kind:e[5],x:e[6],y:e[7],bbox:e[8],layerId:layer.id,featureId:e[1]};}

    // Public IBGE address selection can refine the administrator lookup.
    // No owner, clinical record, cadastral croqui or inferred location is emitted.
    function addressSelected(layer,address){
      if(!String(layer?.id||'').startsWith('cnefe-')||!String(address||'').trim())return;
      document.dispatchEvent(new CustomEvent('sfa:atlas-address-selected',{detail:{address:String(address)}}));
    }

    // `source`: o índice local ou a resposta da reserva do servidor (mesmo formato: {layers, entries}).
    function showPlace(entry,source){
      const layer=(source||index).layers[entry[0]],mine=++placeRun;preview.clearLayers();
      addressSelected(layer,entry[2]||entry[3]);
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
      count+=entries(Model.search(index,query),index);
      if(seq===run)status.textContent=count?count+' opções · selecione para localizar ou consultar':'Nenhuma correspondência. Tente o nome da rua ou da quadra. Números sem cadastro não recebem posição estimada.';
    }

    function entries(found,source){
      if(found.length)section('Endereços e locais');
      found.forEach(e=>{
        const layer=source.layers[e[0]];
        button(e[2],[e[3],layer.title,where(e)].filter(Boolean).join(' · '),()=>showPlace(e,source),e[5]?stopFor(e,layer):undefined);
      });
      return found.length;
    }

    // ---- Reserva: consulta ao servidor ----
    async function serverSearch(){
      const query=input.value.trim(),seq=++run;controller?.abort();preview.clearLayers();results.replaceChildren();
      let timedOut=false;
      if(!query){open(false);return;}open(true);status.textContent='Buscando no atlas…';
      let count=territoryMatches(query);
      try{
        controller=new AbortController();const mine=controller,giveUp=setTimeout(()=>{timedOut=true;mine.abort();},15000);
        const response=await fetch(urls.search+(urls.search.includes('?')?'&':'?')+'compacto=1&q='+encodeURIComponent(query),{credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('Não foi possível consultar os endereços. As quadras continuam disponíveis.');
        const data=await response.json();clearTimeout(giveUp);if(seq!==run)return;
        // Versão nova do índice ainda sendo montada: as quadras já estão na tela; tenta de novo em instantes.
        if(data.preparando){status.textContent='Preparando a busca de endereços…';clearTimeout(timer);timer=setTimeout(()=>{if(!index&&input.value.trim()===query)serverSearch();},4000);return;}
        // Índice pronto no servidor: mesma lista, mesmo toque e mesmo ＋ Rota da busca local.
        if(Array.isArray(data.entries))count+=entries(data.entries,data);
        else{if(data.results.length)section('Endereços e locais');
        data.results.forEach(item=>{
          const f=item.feature,p=f.properties;
          // Mesmo na busca de reserva dá para ir para a rota: a posição vem da própria feição devolvida.
          const stop=f.geometry?{name:p.name||p.label||item.layer_title,note:[p.address,item.layer_title].filter(Boolean).join(' · '),feature:f,layerId:item.layer_id,featureId:f.id}:undefined;
          button(p.name||p.label||item.layer_title,[p.address,item.layer_title,item.located?(f.geometry.type==='Point'?'Ponto cadastrado':'Trecho / referência no mapa'):'Sem posição · consultar cadastro'].filter(Boolean).join(' · '),()=>{
            addressSelected({id:item.layer_id},p.name||p.address);
            preview.clearLayers();
            if(f.geometry){const layer=L.geoJSON(f,highlight).addTo(preview);const bounds=layer.getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[45,45],maxZoom:19});map.fire('atlasfocusfeature',{layerId:item.layer_id,featureId:f.id});open(false);}
            else if(p.cadastre_ref){window.SfaCadastreViewer.open(dataset,p.cadastre_ref,item.layer_id,f.id);open(false);}
            else{const b=document.createElement('button');b.type='button';b.dataset.atlasLayer=item.layer_id;b.dataset.atlasFeature=f.id;b.hidden=true;document.body.append(b);b.click();b.remove();open(false);}
          },stop);count++;
        });}
        status.textContent=count?count+' opções · selecione para localizar ou consultar':'Nenhuma correspondência. Tente o nome da rua ou da quadra. Números sem cadastro não recebem posição estimada.';
      }catch(e){if(seq!==run)return;if(e.name!=='AbortError')status.textContent=e.message;else if(timedOut)status.textContent='A busca demorou demais. Tente de novo em instantes.';}
    }

    // Índice a caminho: quadras e setores já aparecem; se ele demorar mais de WAIT_MS, o servidor responde
    // (a partir do índice já pronto, sem montar nada) e a busca local assume quando o índice chegar.
    function waiting(){
      run++;controller?.abort();preview.clearLayers();results.replaceChildren();open(true);
      territoryMatches(input.value.trim());
      status.textContent='Preparando a busca de endereços…';
      clearTimeout(timer);
      timer=setTimeout(()=>{if(!index&&input.value.trim())serverSearch();},Math.max(400,WAIT_MS-(Date.now()-loadingSince)));
    }
    function search(){
      if(!input.value.trim()){open(false);return;}
      if(index){localSearch(input.value.trim());return;}
      loadIndex();
      if(indexState==='loading')waiting();else serverSearch();      // sem índice nem download em andamento (falha ou recurso ausente): reserva
    }
    $('field-filters').onsubmit=e=>{e.preventDefault();clearTimeout(timer);search();};
    input.oninput=()=>{
      run++;controller?.abort();clearTimeout(timer);
      if(!input.value.trim()){clear();return;}
      if(index){localSearch(input.value.trim());return;}   // imediato: sem espera e sem rede
      loadIndex();
      if(indexState==='loading')waiting();                             // a caminho: o resultado local aparece quando chegar
      else timer=setTimeout(serverSearch,400);                         // indisponível (falha ou recurso ausente): reserva no servidor
    };
    input.onfocus=loadIndex;
    // Baixa o índice logo depois que a tela termina de carregar, antes de alguém digitar.
    (window.requestIdleCallback||(fn=>setTimeout(fn,600)))(loadIndex);
    input.onkeydown=e=>{if(e.key==='Escape'){run++;controller?.abort();open(false);}if(e.key==='ArrowDown'){const b=results.querySelector('button');if(b){e.preventDefault();b.focus();}}};
    panel.onkeydown=e=>{if(e.key==='Escape'){open(false);input.focus();}};
    function close(){run++;clearTimeout(timer);controller?.abort();open(false);}
    $('atlas-search-close').onclick=()=>{close();input.focus();};
    document.addEventListener('pointerdown',e=>{if(!e.target.closest('.field-search'))close();});
    return {clear,search(query){input.value=String(query??'').slice(0,240);clearTimeout(timer);search();}};
  }};
})();
