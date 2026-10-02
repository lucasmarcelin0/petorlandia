(function(){
  'use strict';
  const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fields=['name','address','category','date','status','notes','precision','sinan','disease','notification_date','symptoms_date','exam','exam_result','final_result','classification','folder_id','position_status','period_year'];
  const normalize=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  window.SfaAtlasEditor={attach(map,dataset){
    const urls=dataset.editor_urls, editable=$('atlas-collaboration').dataset.editor==='1',clinicalEditor=$('atlas-collaboration').dataset.clinicalEditor==='1';
    let catalog=[],layer=null,feature=null,page=0,selected=new Set(),quality=null,folderAction='create_folder',positioning=false,qualityRun=0,layerAction='create_layer',drawing=false,vertices=[],busy=false,canEdit=false;
    const preview=L.layerGroup().addTo(map);
    const dragIcon=()=>L.divIcon({className:'editor-drag-marker',html:'<span></span>',iconSize:[30,38],iconAnchor:[15,36],tooltipAnchor:[0,-31]});
    const url=key=>key?urls.layer.replace('KEY',encodeURIComponent(key)):urls.catalog;
    const api=async(target,body)=>{
      const response=await fetch(target,{credentials:'same-origin',cache:'no-store',method:body?'POST':'GET',
        ...(body?{referrerPolicy:'strict-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]')?.content||$('atlas-collaboration').dataset.csrf},body:JSON.stringify(body)}:{})});
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
    function hide(){finishPositioning();stopDrawing();preview.clearLayers();$('atlas-editor').hidden=true;$('field-workspace').classList.remove('has-editor');map.invalidateSize();$('atlas-open-editor').focus();}
    function stopDrawing(){drawing=false;$('editor-draw-finish')&&($('editor-draw-finish').hidden=true);$('editor-draw-undo')&&($('editor-draw-undo').hidden=true);$('field-map').classList.remove('is-picking');}
    function rows(){
      const q=normalize($('editor-table-query').value),node=window.SfaAtlasFoldersModel.tree(layer?.folders||[]).byId.get($('editor-folder-filter').value);
      return window.SfaAtlasFoldersModel.filter(layer?.features||[],{start:$('editor-from').value,end:$('editor-to').value},node?.ids||null)
        .filter(f=>normalize(fields.map(k=>f.properties?.[k]||'').join(' ')+' '+(f.properties?.label||'')+' '+(f.properties?.folder_path||[]).join(' ')).includes(q))
        .filter(f=>!$('editor-only-issues').checked||quality?.records.find(r=>r.id===String(f.id))?.issues.length);
    }
    function foldersUI(){
      const model=window.SfaAtlasFoldersModel.tree(layer?.folders||[]),options=[...model.byId.values()].map(n=>new Option(n.path.join(' / '),n.id));
      ['editor-folder-filter','editor-folder_id','editor-move-target','editor-folder-parent'].forEach(id=>{
        const element=$(id);if(!element)return;const previous=element.value;
        element.replaceChildren(new Option(id==='editor-folder-filter'?'Todas as pastas':'Direto na camada',''),...options.map(o=>new Option(o.text,o.value)));
        if(model.byId.has(previous))element.value=previous;
      });
      ['editor-folder-edit','editor-folder-delete'].forEach(id=>{if($(id))$(id).disabled=!canEdit||!$('editor-folder-filter').value;});
    }
    function updateSelected(){
      $('editor-selected-count').textContent=selected.size+' selecionados';
      if($('editor-bulk-move'))$('editor-bulk-move').disabled=!canEdit||!selected.size;
    }
    function table(){
      const list=rows(), pages=Math.max(1,Math.ceil(list.length/30));page=Math.min(page,pages-1);
      $('editor-table-count').textContent=layer?`${list.length} de ${layer.features.length} registros · ${layer.features.filter(f=>!f.geometry).length} sem posição · revisão ${layer.revision||'original'}`:'Escolha uma camada para consultar os registros.';
      $('editor-rows').innerHTML=list.slice(page*30,(page+1)*30).map(f=>`<tr><td class="editor-select-cell"><input type="checkbox" data-select-feature="${esc(f.id)}" aria-label="Selecionar ${esc(f.properties.name||f.properties.label||f.id)}" ${selected.has(String(f.id))?'checked':''}></td><td><strong>${esc(f.properties.name||f.properties.label||f.id)}</strong><small>${esc(f.properties.date||f.properties.notification_date||'')}</small></td><td>${esc(f.properties.address||'')}<small class="editor-folder-meta">${esc((f.properties.folder_path||[f.properties.category||'']).join(' › '))}</small>${quality?.records.find(r=>r.id===String(f.id))?.issues.length?'<div class="editor-quality-issues">'+esc(quality.records.find(r=>r.id===String(f.id)).issues.join(' · '))+'</div>':''}</td><td>${f.geometry?esc({Point:'Ponto',LineString:'Trajeto',Polygon:'Área'}[f.geometry.type]||f.geometry.type):'<span class="editor-unlocated">Sem posição</span>'}</td><td><button type="button" data-edit-feature="${esc(f.id)}">${canEdit?'Editar':'Localizar'}</button>${canEdit?`<button type="button" class="editor-danger" data-delete-feature="${esc(f.id)}" aria-label="Excluir ${esc(f.properties.name||f.properties.label||f.id)}">Excluir</button>`:''}</td></tr>`).join('');
      updateSelected();$('editor-page').textContent=`${page+1} / ${pages}`;$('editor-prev').disabled=page===0;$('editor-next').disabled=page+1>=pages;
      ['editor-new-point','editor-edit-layer','editor-delete-layer','editor-copy-layer'].forEach(id=>{if($(id))$(id).disabled=!layer||!canEdit||layer.deleted;});
      ['editor-export','editor-export-csv','editor-review-layer'].forEach(id=>$(id).disabled=!layer);
      ['editor-folder-new','editor-reposition','editor-bulk-move'].forEach(id=>{if($(id))$(id).disabled=!canEdit||layer?.deleted||(id==='editor-bulk-move'&&!selected.size);});
      foldersUI();
    }
    async function reloadCatalog(selected=layer?.id){
      catalog=(await api(urls.catalog)).layers;
      $('editor-layer').replaceChildren(new Option('Escolha uma camada',''),...catalog.map(l=>new Option(`${l.deleted?'[Excluída] ':''}${l.title} · ${l.count}`,l.id)));
      if(catalog.some(l=>l.id===selected))$('editor-layer').value=selected;
    }
    async function loadLayer(key){
      stopDrawing();preview.clearLayers();if($('editor-feature-form'))$('editor-feature-form').hidden=true;finishPositioning();selected.clear();quality=null;qualityRun++;$('editor-quality-summary').hidden=true;$('editor-only-issues').checked=false;
      layer=key?await api(url(key)):null;canEdit=editable&&!!layer&&(!layer.clinical||clinicalEditor);page=0;foldersUI();table();
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
      const geo=L.geoJSON(f);map.fitBounds(geo.getBounds(),{padding:[40,40],maxZoom:window.SfaCondominiosModel.isHouse({...f,atlasEntry:layer})?20:18});
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
        const m=L.marker([geo.coordinates[1],geo.coordinates[0]],{draggable:true,icon:dragIcon(),title:'Ponto em edição · arraste para ajustar'}).addTo(preview);
        m.bindTooltip('Arraste para ajustar o local',{permanent:true,direction:'top'});
        m.on('dragend',()=>{const p=m.getLatLng();$('editor-lat').value=p.lat.toFixed(8);$('editor-lng').value=p.lng.toFixed(8);markMoved();});
      }else L.geoJSON(geo,{style:{color:'#fff',weight:4,dashArray:'5 5',fillOpacity:.15}}).addTo(preview);
    }
    function openFeature(f=null){
      if(!canEdit||layer.deleted){if(f)focus(f);return;}
      feature=f;stopDrawing();vertices=[];
      fields.forEach(k=>{if($('editor-'+k))$('editor-'+k).value=f?.properties?.[k]||(k==='name'?f?.properties?.label||'':'');});
      $('editor-folder_id').value=f?.properties.folder_id||$('editor-folder-filter').value||'';$('editor-position_status').value=f?.properties.position_status||'to_review';
      $('editor-reason').value=f?'Correção do cadastro':'Cadastro de registro';
      $('editor-feature-heading').textContent=f?'Editar registro':'Novo registro';
      const cad=$('editor-cadastre-reference');cad.hidden=!f?.properties.cadastre_ref;cad.onclick=()=>window.SfaCadastreViewer.open(dataset,f.properties.cadastre_ref,layer.id,f.id);$('editor-clinical-fields').hidden=!layer.clinical;
      const geo=f?.geometry;
      $('editor-geometry-kind').value=!geo?(f?'none':'Point'):['Point','LineString','Polygon'].includes(geo.type)?geo.type:'custom';
      $('editor-lat').value=geo?.type==='Point'?geo.coordinates[1]:'';$('editor-lng').value=geo?.type==='Point'?geo.coordinates[0]:'';
      $('editor-geometry').value=geo?JSON.stringify(geo):'';
      $('editor-feature-form').hidden=false;$('editor-save-feature').disabled=false;updateGeometryUI();previewGeometry();
      qualityRun++;if(f?.geometry)focus(f);if(f)pointReview().catch(e=>message(e.message,true));else $('editor-point-review').hidden=true;$('editor-name').focus();
    }
    function finishPositioning(){
      positioning=false;$('field-workspace').classList.remove('is-positioning');$('editor-map-tools').hidden=true;map.invalidateSize();
    }
    function startPositioning(){
      if(!canEdit)return;positioning=true;$('field-workspace').classList.add('is-positioning');$('editor-map-tools').hidden=false;map.invalidateSize();
      message('Arraste o marcador para a entrada correta. Volte ao formulário para conferir e salvar.');
    }
    function markMoved(){
      $('editor-position_status').value='to_review';$('editor-point-review').hidden=true;
      message('Posição ajustada, ainda não salva. Confira endereço, precisão e motivo antes de salvar.');
    }
    async function pointReview(){
      if(!layer)return;const run=++qualityRun,target=new URL(url(layer.id),window.location.origin);target.pathname+='/conferencia';
      const properties={};fields.forEach(k=>{if($('editor-'+k))properties[k]=$('editor-'+k).value;});
      const data=await api(target.pathname+target.search,{feature_id:feature?.id,feature:{type:'Feature',geometry:geometryValue(),properties}});
      if(run!==qualityRun)return;const r=data.records[0];$('editor-point-review').hidden=false;
      $('editor-point-review').innerHTML=`<strong>Conferência local</strong>${r.nearest_road?'<p>Rua próxima: '+esc(r.nearest_road.name)+' · '+r.nearest_road.distance_m+' m</p>':''}${r.declared_road?'<p>Distância da via informada: '+r.declared_road.distance_m+' m</p>':''}${r.blocks.length?'<p>Dentro de: '+r.blocks.map(b=>'quadra '+esc(b.block)+' / SC '+esc(b.sector)).join(' · ')+'</p>':''}${r.issues.length?'<p class="editor-quality-issues">'+esc(r.issues.join(' · '))+'</p>':''}<small>${esc(r.note||r.geometry_note||'Confira a entrada no campo.')}</small>${r.house_candidate?'<button type="button" id="editor-use-house-reference">Usar referência desta casa · conferir</button>':''}`;
      if(r.house_candidate)$('editor-use-house-reference').onclick=()=>{
        const house=r.house_candidate;$('editor-geometry-kind').value='Point';$('editor-lng').value=house.coordinates[0];$('editor-lat').value=house.coordinates[1];
        $('editor-address').value=house.address;$('editor-precision').value=house.precision;$('editor-position_status').value=house.position_status;
        updateGeometryUI();previewGeometry();message('Referência carregada para conferência. A posição ainda não foi salva.');
      };
    }
    async function reviewLayer(){
      if(!layer)return;const target=new URL(url(layer.id),window.location.origin);target.pathname+='/conferencia';
      message('Conferindo endereços, ruas e setores…');const run=++qualityRun,data=await api(target.pathname+target.search);if(run!==qualityRun)return;quality=data;
      $('editor-quality-summary').hidden=false;$('editor-quality-summary').innerHTML=`<b>${quality.summary.records} registros · ${quality.summary.with_address} com endereço · ${quality.summary.with_issues} com pendências de referência</b><p>${Object.entries(quality.summary.issues).map(([name,count])=>esc(name)+': '+count).join(' · ')||'Nenhuma divergência nas referências locais.'}</p><small>${esc(quality.source_note)}</small>`;table();message('Conferência concluída. Os pontos preservam suas posições; corrija os registros após revisar as referências.');
    }
    function folderForm(action){
      folderAction=action;const current=(layer.folders||[]).find(n=>n.id===$('editor-folder-filter').value);
      $('editor-folder-form').hidden=false;$('editor-folder-name').value=action==='update_folder'?current.name:'';
      $('editor-folder-parent').value=action==='update_folder'?current.parent_id:$('editor-folder-filter').value;
      $('editor-folder-reason').value='Organização das pastas';$('editor-folder-name').focus();
    }
    async function mutate(command,key=layer?.id){
      if(busy)return;busy=true;
      const buttons=[...$('atlas-editor').querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
      try{
        const updated=await api(url(key),{revision:key?layer.revision:0,...command});
        message('Alteração salva e compartilhada com a equipe.');layer=updated;
        if($('editor-layer-form'))$('editor-layer-form').hidden=true;
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
    $('editor-table-query').oninput=()=>{page=0;table();};['editor-folder-filter','editor-from','editor-to'].forEach(id=>$(id).onchange=()=>{page=0;foldersUI();table();});
    $('editor-review-layer').onclick=()=>reviewLayer().catch(e=>message(e.message,true));$('editor-only-issues').onchange=async()=>{if($('editor-only-issues').checked&&!quality)try{await reviewLayer();}catch(e){$('editor-only-issues').checked=false;message(e.message,true);}table();};
    $('editor-select-page').onclick=()=>{rows().slice(page*30,(page+1)*30).forEach(f=>selected.add(String(f.id)));table();};$('editor-clear-selected').onclick=()=>{selected.clear();table();};$('editor-prev').onclick=()=>{page--;table();};$('editor-next').onclick=()=>{page++;table();};
    $('editor-rows').onclick=async e=>{
      const toggle=e.target.closest('[data-select-feature]');if(toggle){if(toggle.checked)selected.add(toggle.dataset.selectFeature);else selected.delete(toggle.dataset.selectFeature);updateSelected();return;}
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
      $('editor-folder-new').onclick=()=>folderForm('create_folder');$('editor-folder-edit').onclick=()=>folderForm('update_folder');
      $('editor-folder-cancel').onclick=()=>$('editor-folder-form').hidden=true;
      $('editor-folder-form').onsubmit=async e=>{e.preventDefault();try{await mutate({action:folderAction,folder_id:$('editor-folder-filter').value,name:$('editor-folder-name').value,parent_id:$('editor-folder-parent').value,reason:$('editor-folder-reason').value});$('editor-folder-form').hidden=true;}catch(e){}};
      $('editor-folder-delete').onclick=async()=>{if(await ask('Excluir esta pasta vazia? A estrutura anterior permanece no histórico.'))try{await mutate({action:'delete_folder',folder_id:$('editor-folder-filter').value,reason:'Exclusão de pasta vazia'});}catch(e){}};
      $('editor-bulk-move').onclick=async()=>{if(!selected.size)return;if(await ask('Mover '+selected.size+' registros para a pasta selecionada? Datas, endereços e posições serão preservados.'))try{await mutate({action:'move_features',folder_id:$('editor-move-target').value,feature_ids:[...selected],reason:'Organização de registros em pastas'});}catch(e){}};
      $('editor-reposition').onclick=startPositioning;$('editor-finish-position').onclick=finishPositioning;
      $('editor-refresh-point-review').onclick=()=>pointReview().catch(e=>message(e.message,true));
      $('editor-new-layer').onclick=()=>layerForm('create_layer');$('editor-copy-layer').onclick=()=>layerForm('copy_layer');
      if($('editor-copy-sheet'))$('editor-copy-sheet').onclick=()=>layerForm('copy_sheet');
      $('editor-edit-layer').onclick=()=>layerForm('update_layer');$('editor-layer-cancel').onclick=()=>$('editor-layer-form').hidden=true;
      $('editor-layer-form').onsubmit=async e=>{e.preventDefault();try{await mutate({action:layerAction,title:$('editor-layer-title').value,color:$('editor-layer-color').value,clinical:$('editor-layer-clinical').checked,reason:$('editor-layer-reason').value,copy_from:layer?.id},layerAction==='update_layer'?layer.id:null);}catch(e){}};
      $('editor-delete-layer').onclick=async()=>{if(await ask('Excluir a camada e retirar seus registros do mapa? Ela poderá ser restaurada no histórico.'))try{await mutate({action:'delete_layer',reason:'Exclusão de camada'});}catch(e){}};
      $('editor-new-point').onclick=()=>openFeature();$('editor-cancel-feature').onclick=()=>{finishPositioning();stopDrawing();preview.clearLayers();$('editor-feature-form').hidden=true;};
      $('editor-feature-form').onsubmit=async e=>{e.preventDefault();try{
        const properties={};fields.forEach(k=>{if($('editor-'+k))properties[k]=$('editor-'+k).value;});
        await mutate({action:feature?'update_feature':'create_feature',feature_id:feature?.id,feature:{type:'Feature',geometry:geometryValue(),properties},confirm_position:$('editor-position_status').value==='verified',reason:$('editor-reason').value});
      }catch(error){message(error.message,true);}};
      $('editor-geometry-kind').onchange=()=>{stopDrawing();updateGeometryUI();previewGeometry();markMoved();};
      ['editor-lat','editor-lng','editor-geometry'].forEach(id=>$(id).onchange=()=>{previewGeometry();markMoved();});
      $('editor-pick').onclick=()=>{startPositioning();drawing=true;vertices=[];preview.clearLayers();$('field-map').classList.add('is-picking');const kind=$('editor-geometry-kind').value;
        $('editor-draw-finish').hidden=kind==='Point';$('editor-draw-undo').hidden=kind==='Point';message(kind==='Point'?'Clique no local no mapa. Depois, arraste o marcador para ajustar.':'Clique no mapa para adicionar os vértices e escolha Concluir desenho.');};
      function drawVertices(){
        preview.clearLayers();vertices.forEach((p,i)=>{const marker=L.marker([p[1],p[0]],{draggable:true,icon:dragIcon(),title:'Ponto em edição · arraste para ajustar'}).addTo(preview);marker.on('dragend',()=>{const pos=marker.getLatLng();vertices[i]=[pos.lng,pos.lat];drawVertices();});});
        if(vertices.length>1)L.polyline(vertices.map(p=>[p[1],p[0]]),{color:'#fff',weight:4}).addTo(preview);
      }
      map.on('click',e=>{if(!drawing)return;const p=[e.latlng.lng,e.latlng.lat];
        if($('editor-geometry-kind').value==='Point'){$('editor-lng').value=p[0].toFixed(8);$('editor-lat').value=p[1].toFixed(8);stopDrawing();previewGeometry();markMoved();message('Posição marcada. Confira e salve o registro.');}
        else{vertices.push(p);drawVertices();}
      });
      $('editor-draw-undo').onclick=()=>{vertices.pop();drawVertices();};
      $('editor-draw-finish').onclick=()=>{const kind=$('editor-geometry-kind').value;
        if(vertices.length<(kind==='Polygon'?3:2)){message('Adicione mais vértices antes de concluir.',true);return;}
        $('editor-geometry').value=JSON.stringify({type:kind,coordinates:kind==='Polygon'?[[...vertices,vertices[0]]]:vertices});stopDrawing();previewGeometry();markMoved();message('Desenho concluído. Confira e salve o registro.');};
    }
    document.addEventListener('click',async e=>{const b=e.target.closest('[data-atlas-layer][data-atlas-feature]');if(!b)return;
      show();try{await reloadCatalog(b.dataset.atlasLayer);await loadLayer(b.dataset.atlasLayer);openFeature(layer.features.find(f=>String(f.id)===b.dataset.atlasFeature));}catch(e){message(e.message,true);}
    });
    $('atlas-reload').onclick=()=>window.SfaAtlasLayers.refresh().catch(e=>message(e.message,true));
    api(urls.documents).then(data=>{
      $('atlas-documents').innerHTML=data.documents.map(d=>`<a href="${esc(d.url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(d.image_url)}" alt="" loading="lazy"><span><strong>${esc(d.title)}</strong><small>${esc(d.note)} Abrir PDF ↗</small></span></a>`).join('');
    }).catch(e=>$('atlas-documents').textContent=e.message);
    map.attributionControl.addAttribution('Ruas/locais: © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · ODbL');
  }};
})();
