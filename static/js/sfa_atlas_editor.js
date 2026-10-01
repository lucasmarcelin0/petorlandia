(function(){
  'use strict';
  const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fields=['name','address','category','date','status','notes','precision','sinan','disease','notification_date','symptoms_date','exam','exam_result','final_result','classification'];
  const normalize=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  window.SfaAtlasEditor={attach(map,dataset){
    const urls=dataset.editor_urls, editable=$('atlas-collaboration').dataset.editor==='1',clinicalEditor=$('atlas-collaboration').dataset.clinicalEditor==='1';
    let catalog=[],layer=null,feature=null,page=0,layerAction='create_layer',drawing=false,vertices=[],busy=false,canEdit=false;
    const preview=L.layerGroup().addTo(map), searchPreview=L.layerGroup().addTo(map);
    const url=key=>key?urls.layer.replace('KEY',encodeURIComponent(key)):urls.catalog;
    const api=async(target,body)=>{
      const response=await fetch(target,{credentials:'same-origin',cache:'no-store',method:body?'POST':'GET',
        ...(body?{headers:{'Content-Type':'application/json','X-CSRFToken':$('atlas-collaboration').dataset.csrf},body:JSON.stringify(body)}:{})});
      if(!response.headers.get('content-type')?.includes('application/json'))throw Error('Sessão encerrada ou acesso indisponível. Entre novamente antes de salvar.');
      const data=await response.json();if(!response.ok)throw Error(data.error||'Não foi possível concluir a operação.');return data;
    };
    function message(text,error=false){$('editor-message').hidden=!text;$('editor-message').textContent=text;$('editor-message').classList.toggle('is-error',error);}
    let confirmation=null;
    function ask(text){$('editor-confirm-text').textContent=text;$('editor-confirm').hidden=false;$('editor-confirm-yes').focus();return new Promise(resolve=>confirmation=resolve);}
    function answer(yes){$('editor-confirm').hidden=true;const resolve=confirmation;confirmation=null;resolve?.(yes);}
    $('editor-confirm-yes').onclick=()=>answer(true);$('editor-confirm-no').onclick=()=>answer(false);
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('editor-confirm').hidden){e.preventDefault();e.stopImmediatePropagation();answer(false);}},true);
    function show(){ $('atlas-editor').hidden=false;$('field-workspace').classList.add('has-editor');map.invalidateSize();}
    function hide(){stopDrawing();preview.clearLayers();$('atlas-editor').hidden=true;$('field-workspace').classList.remove('has-editor');map.invalidateSize();$('atlas-open-editor').focus();}
    function stopDrawing(){drawing=false;$('editor-draw-finish')&&($('editor-draw-finish').hidden=true);$('editor-draw-undo')&&($('editor-draw-undo').hidden=true);$('field-map').classList.remove('is-picking');}
    function rows(){ const q=normalize($('editor-table-query').value);return (layer?.features||[]).filter(f=>normalize(fields.map(k=>f.properties?.[k]||'').join(' ')+' '+(f.properties?.label||'')).includes(q)); }
    function table(){
      const list=rows(), pages=Math.max(1,Math.ceil(list.length/30));page=Math.min(page,pages-1);
      $('editor-table-count').textContent=layer?`${list.length} de ${layer.features.length} registros · ${layer.features.filter(f=>!f.geometry).length} sem posição · revisão ${layer.revision||'original'}`:'Escolha uma camada para consultar os registros.';
      $('editor-rows').innerHTML=list.slice(page*30,(page+1)*30).map(f=>`<tr><td><strong>${esc(f.properties.name||f.properties.label||f.id)}</strong><small>${esc(f.properties.date||f.properties.notification_date||'')}</small></td><td>${esc(f.properties.address||'')}<small>${esc(f.properties.category||'')}</small></td><td>${f.geometry?esc({Point:'Ponto',LineString:'Trajeto',Polygon:'Área'}[f.geometry.type]||f.geometry.type):'<span class="editor-unlocated">Sem posição</span>'}</td><td><button type="button" data-edit-feature="${esc(f.id)}">${canEdit?'Editar':'Localizar'}</button>${canEdit?`<button type="button" class="editor-danger" data-delete-feature="${esc(f.id)}" aria-label="Excluir ${esc(f.properties.name||f.properties.label||f.id)}">Excluir</button>`:''}</td></tr>`).join('');
      $('editor-page').textContent=`${page+1} / ${pages}`;$('editor-prev').disabled=page===0;$('editor-next').disabled=page+1>=pages;
      ['editor-new-point','editor-edit-layer','editor-delete-layer','editor-copy-layer'].forEach(id=>{if($(id))$(id).disabled=!layer||!canEdit||layer.deleted;});
      ['editor-export','editor-export-csv'].forEach(id=>$(id).disabled=!layer);
    }
    async function reloadCatalog(selected=layer?.id){
      catalog=(await api(urls.catalog)).layers;
      $('editor-layer').replaceChildren(new Option('Escolha uma camada',''),...catalog.map(l=>new Option(`${l.deleted?'[Excluída] ':''}${l.title} · ${l.count}`,l.id)));
      if(catalog.some(l=>l.id===selected))$('editor-layer').value=selected;
    }
    async function loadLayer(key){
      stopDrawing();preview.clearLayers();if($('editor-feature-form'))$('editor-feature-form').hidden=true;
      layer=key?await api(url(key)):null;canEdit=editable&&!!layer&&(!layer.clinical||clinicalEditor);page=0;table();
      $('editor-origin').textContent=layer?`${layer.origin.title||'Equipe'} · ${layer.updated_at?'atualizado em '+new Date(layer.updated_at).toLocaleString('pt-BR'):'fonte original'}${layer.deleted?' · camada excluída (restaure pelo histórico)':''}`:'';
      $('editor-layer-form')&&($('editor-layer-form').hidden=true);await history();
    }
    async function history(){
      if(!layer){$('editor-history-list').replaceChildren();return;}
      const data=await api(urls.history.replace('KEY',encodeURIComponent(layer.id)));
      $('editor-history-list').innerHTML=data.revisions.map(r=>`<div class="editor-revision"><strong>${esc(new Date(r.at).toLocaleString('pt-BR'))}</strong><small>${esc(r.actor)} · ${esc(r.reason)}</small>${canEdit?`<button type="button" data-restore="${r.revision}">Restaurar esta versão</button>`:''}</div>`).join('')+(canEdit&&layer.origin.type!=='local'&&layer.origin.type!=='copy'&&layer.origin.type!=='sheet_snapshot'?'<button type="button" data-restore="0">Restaurar fonte original</button>':'');
    }
    function focus(f){
      if(!f.geometry){message('Este registro ainda não tem posição confirmada. Marque o local no mapa para posicioná-lo.');return;}
      const geo=L.geoJSON(f);map.fitBounds(geo.getBounds(),{padding:[40,40],maxZoom:18});
    }
    function geometryValue(){
      const kind=$('editor-geometry-kind').value;
      if(kind==='none')return null;
      if(kind==='Point'){
        if(!$('editor-lng').value||!$('editor-lat').value)throw Error('Informe latitude e longitude ou marque o ponto no mapa.');
        return {type:'Point',coordinates:[Number($('editor-lng').value),Number($('editor-lat').value)]};
      }
      try{return JSON.parse($('editor-geometry').value);}catch(e){throw Error('Confira o desenho ou as coordenadas GeoJSON.');}
    }
    function updateGeometryUI(){
      const kind=$('editor-geometry-kind').value;
      $('editor-coordinate-fields').hidden=kind!=='Point';$('editor-geometry-details').hidden=!['LineString','Polygon','custom'].includes(kind);
      $('editor-pick').disabled=kind==='none'||kind==='custom';
      if(kind==='none'){preview.clearLayers();stopDrawing();}
    }
    function previewGeometry(){
      preview.clearLayers();let geo;
      try{geo=geometryValue();}catch(e){return;}
      if(!geo)return;
      if(geo.type==='Point'){
        const m=L.marker([geo.coordinates[1],geo.coordinates[0]],{draggable:true}).addTo(preview);
        m.bindTooltip('Arraste para ajustar o local',{permanent:true,direction:'top'});
        m.on('dragend',()=>{const p=m.getLatLng();$('editor-lat').value=p.lat.toFixed(8);$('editor-lng').value=p.lng.toFixed(8);});
      }else L.geoJSON(geo,{style:{color:'#fff',weight:4,dashArray:'5 5',fillOpacity:.15}}).addTo(preview);
    }
    function openFeature(f=null){
      if(!canEdit||layer.deleted){if(f)focus(f);return;}
      feature=f;stopDrawing();vertices=[];
      fields.forEach(k=>{if($('editor-'+k))$('editor-'+k).value=f?.properties?.[k]||(k==='name'?f?.properties?.label||'':'');});
      $('editor-reason').value=f?'Correção do cadastro':'Cadastro de registro';
      $('editor-feature-heading').textContent=f?'Editar registro':'Novo registro';$('editor-clinical-fields').hidden=!layer.clinical;
      const geo=f?.geometry;
      $('editor-geometry-kind').value=!geo?(f?'none':'Point'):['Point','LineString','Polygon'].includes(geo.type)?geo.type:'custom';
      $('editor-lat').value=geo?.type==='Point'?geo.coordinates[1]:'';$('editor-lng').value=geo?.type==='Point'?geo.coordinates[0]:'';
      $('editor-geometry').value=geo?JSON.stringify(geo):'';
      $('editor-feature-form').hidden=false;$('editor-save-feature').disabled=false;updateGeometryUI();previewGeometry();
      if(f?.geometry)focus(f);$('editor-name').focus();
    }
    async function mutate(command,key=layer?.id){
      if(busy)return;busy=true;
      const buttons=[...$('atlas-editor').querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
      try{
        const updated=await api(url(key),{revision:key?layer.revision:0,...command});
        message('Alteração salva e compartilhada com a equipe.');layer=updated;
        await reloadCatalog(updated.id);await loadLayer(updated.id);await window.SfaAtlasLayers.refresh(updated.id);
        return updated;
      }catch(error){message(error.message,true);throw error;}
      finally{busy=false;buttons.forEach(b=>b.disabled=false);table();}
    }
    function layerForm(action){
      layerAction=action;$('editor-layer-form').hidden=false;
      $('editor-layer-form-title').textContent=action==='update_layer'?'Alterar camada':'Nova camada';
      $('editor-layer-title').value=action==='update_layer'?layer.title:action==='copy_layer'?layer.title+' · cópia':action==='copy_sheet'?'Arboviroses · cadastro no atlas':'';
      $('editor-layer-color').value=layer?.color||'#65bdd2';$('editor-layer-clinical').checked=(action!=='create_layer'&&!!layer?.clinical)||action==='copy_sheet';
      $('editor-layer-clinical').disabled=!clinicalEditor||!!layer?.clinical&&action==='update_layer';
      $('editor-layer-reason').value=action==='update_layer'?'Alteração da camada':'Criação de camada';$('editor-layer-title').focus();
    }
    function download(data,type,extension){
      const a=document.createElement('a'),blob=new Blob([data],{type});a.href=URL.createObjectURL(blob);a.download=(layer.title.replace(/[^\p{L}\p{N} _-]/gu,'_')||'atlas')+'.'+extension;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
    }
    $('atlas-open-editor').onclick=async()=>{show();try{await reloadCatalog();table();}catch(e){message(e.message,true);}};
    $('editor-close').onclick=hide;
    $('editor-reload').onclick=async()=>{try{await reloadCatalog();await loadLayer($('editor-layer').value);message('Tabela atualizada.');}catch(e){message(e.message,true);}};
    $('editor-layer').onchange=()=>loadLayer($('editor-layer').value).catch(e=>message(e.message,true));
    $('editor-table-query').oninput=()=>{page=0;table();};$('editor-prev').onclick=()=>{page--;table();};$('editor-next').onclick=()=>{page++;table();};
    $('editor-rows').onclick=async e=>{
      const edit=e.target.closest('[data-edit-feature]'),del=e.target.closest('[data-delete-feature]');
      if(edit){openFeature(layer.features.find(f=>String(f.id)===edit.dataset.editFeature));return;}
      if(del&&await ask('Excluir este registro? A versão anterior fica disponível no histórico.'))try{await mutate({action:'delete_feature',feature_id:del.dataset.deleteFeature,reason:'Exclusão de registro incorreto'});}catch(e){}
    };
    $('editor-history-list').onclick=async e=>{const b=e.target.closest('[data-restore]');if(b&&await ask('Restaurar esta versão inteira da camada? A versão atual também ficará no histórico.'))try{await mutate({action:'restore',restore_revision:Number(b.dataset.restore),reason:'Restauração pelo histórico'});}catch(e){}};
    $('editor-export').onclick=()=>download(JSON.stringify({type:'FeatureCollection',features:layer.features,source:layer.origin},null,2),'application/geo+json','geojson');
    $('editor-export-csv').onclick=()=>{
      const cols=['id',...fields,'longitude','latitude'],cell=v=>'"'+String(v??'').replace(/^[=+@-]/,'\t$&').replace(/"/g,'""')+'"';
      const data=[cols.map(cell).join(';'),...layer.features.map(f=>[f.id,...fields.map(k=>f.properties?.[k]),...(f.geometry?.type==='Point'?f.geometry.coordinates:['',''])].map(cell).join(';'))].join('\r\n');download('\ufeff'+data,'text/csv;charset=utf-8','csv');
    };
    if(editable){
      $('editor-new-layer').onclick=()=>layerForm('create_layer');$('editor-copy-layer').onclick=()=>layerForm('copy_layer');
      if($('editor-copy-sheet'))$('editor-copy-sheet').onclick=()=>layerForm('copy_sheet');
      $('editor-edit-layer').onclick=()=>layerForm('update_layer');$('editor-layer-cancel').onclick=()=>$('editor-layer-form').hidden=true;
      $('editor-layer-form').onsubmit=async e=>{e.preventDefault();try{await mutate({action:layerAction,title:$('editor-layer-title').value,color:$('editor-layer-color').value,clinical:$('editor-layer-clinical').checked,reason:$('editor-layer-reason').value,copy_from:layer?.id},layerAction==='update_layer'?layer.id:null);}catch(e){}};
      $('editor-delete-layer').onclick=async()=>{if(await ask('Excluir a camada e retirar seus registros do mapa? Ela poderá ser restaurada no histórico.'))try{await mutate({action:'delete_layer',reason:'Exclusão de camada'});}catch(e){}};
      $('editor-new-point').onclick=()=>openFeature();$('editor-cancel-feature').onclick=()=>{stopDrawing();preview.clearLayers();$('editor-feature-form').hidden=true;};
      $('editor-feature-form').onsubmit=async e=>{e.preventDefault();try{
        const properties={};fields.forEach(k=>{if($('editor-'+k))properties[k]=$('editor-'+k).value;});
        await mutate({action:feature?'update_feature':'create_feature',feature_id:feature?.id,feature:{type:'Feature',geometry:geometryValue(),properties},reason:$('editor-reason').value});
      }catch(error){message(error.message,true);}};
      $('editor-geometry-kind').onchange=()=>{stopDrawing();updateGeometryUI();previewGeometry();};
      ['editor-lat','editor-lng','editor-geometry'].forEach(id=>$(id).onchange=previewGeometry);
      $('editor-pick').onclick=()=>{drawing=true;vertices=[];preview.clearLayers();$('field-map').classList.add('is-picking');const kind=$('editor-geometry-kind').value;
        $('editor-draw-finish').hidden=kind==='Point';$('editor-draw-undo').hidden=kind==='Point';message(kind==='Point'?'Clique no local no mapa. Depois, arraste o marcador para ajustar.':'Clique no mapa para adicionar os vértices e escolha Concluir desenho.');};
      function drawVertices(){
        preview.clearLayers();vertices.forEach((p,i)=>{const marker=L.marker([p[1],p[0]],{draggable:true}).addTo(preview);marker.on('dragend',()=>{const pos=marker.getLatLng();vertices[i]=[pos.lng,pos.lat];drawVertices();});});
        if(vertices.length>1)L.polyline(vertices.map(p=>[p[1],p[0]]),{color:'#fff',weight:4}).addTo(preview);
      }
      map.on('click',e=>{if(!drawing)return;const p=[e.latlng.lng,e.latlng.lat];
        if($('editor-geometry-kind').value==='Point'){$('editor-lng').value=p[0].toFixed(8);$('editor-lat').value=p[1].toFixed(8);stopDrawing();previewGeometry();message('Posição marcada. Confira e salve o registro.');}
        else{vertices.push(p);drawVertices();}
      });
      $('editor-draw-undo').onclick=()=>{vertices.pop();drawVertices();};
      $('editor-draw-finish').onclick=()=>{const kind=$('editor-geometry-kind').value;
        if(vertices.length<(kind==='Polygon'?3:2)){message('Adicione mais vértices antes de concluir.',true);return;}
        $('editor-geometry').value=JSON.stringify({type:kind,coordinates:kind==='Polygon'?[[...vertices,vertices[0]]]:vertices});stopDrawing();previewGeometry();message('Desenho concluído. Confira e salve o registro.');};
    }
    document.addEventListener('click',async e=>{const b=e.target.closest('[data-atlas-layer][data-atlas-feature]');if(!b)return;
      show();try{await reloadCatalog(b.dataset.atlasLayer);await loadLayer(b.dataset.atlasLayer);openFeature(layer.features.find(f=>String(f.id)===b.dataset.atlasFeature));}catch(e){message(e.message,true);}
    });
    $('atlas-reload').onclick=()=>window.SfaAtlasLayers.refresh().catch(e=>message(e.message,true));
    // Street/address search uses the local snapshot and current shared registrations.
    let searchSequence=0;
    async function placeSearch(){
      const query=$('atlas-place-query').value.trim(),run=++searchSequence;if(!query)return;
      $('atlas-place-status').textContent='Buscando…';$('atlas-place-results').replaceChildren();searchPreview.clearLayers();
      try{
        const data=await api(urls.search+(urls.search.includes('?')?'&':'?')+'q='+encodeURIComponent(query));if(run!==searchSequence)return;
        const items=data.results;$('atlas-place-status').textContent=items.length?`${items.length} correspondências. Ruas indicam o trecho, sem estimar o número do imóvel.`:'Nenhum local cadastrado corresponde à busca. Tente o nome da rua sem o número ou confira os PDFs.';
        items.forEach(item=>{const b=document.createElement('button');b.type='button';b.innerHTML=`<strong>${esc(item.feature.properties.name||item.feature.properties.label)}</strong><small>${esc(item.feature.properties.address||item.layer_title)} · ${item.located?'Referência no mapa':'Sem posição'}</small>`;
          b.onclick=()=>{searchPreview.clearLayers();if(item.feature.geometry){L.geoJSON(item.feature,{style:{color:'#fff',weight:5,fillOpacity:.2},pointToLayer:(_,p)=>L.circleMarker(p,{radius:10,color:'#fff',fillColor:'#087f81',fillOpacity:1})}).addTo(searchPreview);focus(item.feature);}else $('atlas-place-status').textContent='Registro disponível na tabela, ainda sem posição confirmada.';};$('atlas-place-results').append(b);
        });
      }catch(e){$('atlas-place-status').textContent=e.message;}
    }
    $('atlas-place-search').onclick=placeSearch;$('atlas-place-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();placeSearch();}};
    $('atlas-place-clear').onclick=()=>{searchSequence++;searchPreview.clearLayers();$('atlas-place-query').value='';$('atlas-place-status').textContent='';$('atlas-place-results').replaceChildren();};
    api(urls.documents).then(data=>{
      $('atlas-documents').innerHTML=data.documents.map(d=>`<a href="${esc(d.url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(d.image_url)}" alt="" loading="lazy"><span><strong>${esc(d.title)}</strong><small>${esc(d.note)} Abrir PDF ↗</small></span></a>`).join('');
    }).catch(e=>$('atlas-documents').textContent=e.message);
    map.attributionControl.addAttribution('Ruas/locais: © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · ODbL');
  }};
})();
