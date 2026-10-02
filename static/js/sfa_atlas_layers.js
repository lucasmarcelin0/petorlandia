(function(){
  'use strict';
  const $=id=>document.getElementById(id), M=window.SfaAtlasLayersModel;
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const day=v=>v ? v.slice(8,10)+'/'+v.slice(5,7)+'/'+v.slice(0,4) : 'Não informada';
  const resultNames={positive:'Positivo',negative:'Negativo',pending:'Pendente / suspeito',unknown:'Sem resultado reconhecido'};
  const resultColors={positive:'#dd7587',negative:'#69bfce',pending:'#edbb6f',unknown:'#bbc3d0'};
  window.SfaAtlasLayers={attach(map,dataset,territory){
    let entries=[], sheet=null, sheetPromise=null, source=null, sequence=0, unlocatedLimit=50, catalogInitialized=false;
    const renderer=L.canvas({padding:.3,pane:'field-events'}), pointLayer=L.layerGroup().addTo(map);
    let pointFeatures=[], addressPromise=null, redrawPending=false;
    function addressData(){if(!addressPromise)addressPromise=fetchJson(dataset.atlas_urls.addresses).then(data=>new Map(data.layers.map(l=>[l.id,l.features]))).catch(e=>{addressPromise=null;throw e;});return addressPromise;}
    const fetchJson=async url=>{
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});
      if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))throw Error('Fonte indisponível ou acesso não autorizado.');
      return response.json();
    };
    const filters=()=>({month:$('atlas-month').value,start:$('atlas-start').value,end:$('atlas-end').value,
      year:$('atlas-year').value,dateField:$('atlas-date-field').value,result:$('atlas-result').value,finalResult:$('atlas-final-result').value,classification:$('atlas-classification').value});
    function notice(text){$('atlas-notice').textContent=text;$('atlas-notice').hidden=!text;}
    function popup(feature,title){
      const p=feature.properties||{}, row=p.sheet;
      if(p.__atlas_layer && (p.name||p.address||p.notes||p.precision))return `<div class="atlas-popup"><strong>${escape(p.name||p.label||title)}</strong><p class="atlas-popup-path">${escape((p.folder_path||[title,p.category||'Cadastro']).join(' › '))}</p>${p.address?'<p>'+escape(p.address)+'</p>':''}${p.date?'<p>'+day(p.date)+'</p>':p.period_year?'<p>Mês da pasta: '+escape(p.month||'não informado')+' / '+escape(p.period_year)+' · sem dia informado</p>':''}${p.notes?'<p>'+escape(p.notes)+'</p>':''}${p.precision?'<small>'+escape(p.precision)+'</small>':''}${p.position_status?'<small class="editor-point-state">'+escape({imported:'Posição original da fonte · a conferir',estimated:'Posição estimada',to_review:'Posição a conferir',verified:'Conferida pela equipe',unlocated:'Sem posição'}[p.position_status]||p.position_status)+'</small>':''}<p><button type="button" data-atlas-layer="${escape(p.__atlas_layer)}" data-atlas-feature="${escape(feature.id)}">Consultar / editar registro</button></p></div>`;
      return row ? `<div class="atlas-popup"><strong>Planilha · linha ${row.source_row}</strong><p>${escape(row.disease || 'Agravo não informado')}</p><dl><dt>SINAN</dt><dd>${escape(row.sinan || 'Não informado')}</dd><dt>Notificação</dt><dd>${day(row.notification_date)}</dd><dt>Sintomas</dt><dd>${day(row.symptoms_date)}</dd><dt>Exame</dt><dd>${escape(row.exam || 'Não informado')}</dd><dt>Resultado</dt><dd>${escape(row.exam_result || 'Não informado')}</dd><dt>Resultado final</dt><dd>${escape(row.final_result || 'Não informado')}</dd><dt>Classificação</dt><dd>${escape(row.classification || 'Não informada')}</dd></dl><p>Posição vinculada por um número SINAN explícito e único no Earth.</p><a target="_blank" rel="noopener noreferrer" href="${escape(sheet.source.url)}&range=A${row.source_row}:T${row.source_row}">Consultar linha de origem ↗</a></div>`
        : `<div class="atlas-popup"><strong>${escape(title)}</strong><p>${escape(p.category || 'Referência operacional')}${p.month?' · mês '+p.month+' na pasta':''}</p>${p.folder_status?'<p>Rótulo da pasta: '+escape(p.folder_status)+'. A classificação da planilha é consultada separadamente.</p>':''}<p>Elemento do arquivo Earth; não representa necessariamente pessoa, imóvel ou visita únicos.</p><small>Origem: ${escape(p.source_id || feature.id || 'camada enviada')}</small>${p.__atlas_layer?'<p><button type="button" data-atlas-layer="'+escape(p.__atlas_layer)+'" data-atlas-feature="'+escape(feature.id)+'">Consultar / editar registro</button></p>':''}</div>`;
    }
    const houses=window.SfaCondominios.attach(map,{popup});
    const isHouse=window.SfaCondominiosModel.isHouse;
    function render(entry,features){
      entry.group.clearLayers();
      if(!entry.enabled)return;
      const points=features.filter(f=>f.geometry?.type==='Point'), other=features.filter(f=>f.geometry && f.geometry.type!=='Point');
      L.geoJSON(other,{pane:'field-events',renderer,style:{color:entry.color,weight:2,fillOpacity:.13},
        onEachFeature:(f,target)=>target.bindPopup(popup(f,entry.title))}).addTo(entry.group);
      points.forEach(feature=>pointFeatures.push({...feature,atlasEntry:entry}));
    }
    function renderPoints(){
      pointLayer.clearLayers();
      const visible=pointFeatures.filter(f=>!isHouse(f)&&(f.atlasEntry.origin?.type!=='cnefe'||map.getZoom()>=17)&&map.getBounds().pad(.1).contains([f.geometry.coordinates[1],f.geometry.coordinates[0]]));
      const groups=M.clusters(visible,coords=>map.latLngToContainerPoint([coords[1],coords[0]]),map.getZoom()>=17?38:48);
      groups.forEach(c=>{
        const sources=new Map();
        c.items.forEach(f=>{
          const entry=f.atlasEntry, title=entry.title;
          if(!sources.has(title))sources.set(title,{color:entry.color,count:0});
          sources.get(title).count++;
        });
        let angle=0;
        const segments=[...sources.values()].map(s=>{const start=angle;angle+=s.count/c.items.length*360;return `${s.color} ${start}deg ${angle}deg`;}).join(',');
        const first=c.items[0], single=c.items.length===1;
        const color=single && first.properties?.sheet ? resultColors[first.properties.sheet.result_group] : first.atlasEntry.color;
        const title=[...sources].map(([name,s])=>`${name}: ${s.count}`).join(' · ');
        const marker=L.marker([c.coordinates[1],c.coordinates[0]],{pane:'field-event-labels',icon:L.divIcon({
          className:'atlas-cluster'+(single?' atlas-single':''),iconSize:single?[18,18]:[36,36],iconAnchor:single?[9,9]:[18,18],
          html:`<span style="--cluster-color:${color};--cluster-ring:conic-gradient(${segments})" title="${escape(title)}">${single?'':c.items.length}</span>`})});
        if(single)marker.bindPopup(popup(first,first.atlasEntry.title));
        else{
          const detail=`<div class="atlas-popup"><strong>${c.items.length} elementos próximos</strong><ul class="atlas-cluster-breakdown">${[...sources].map(([name,s])=>`<li><i style="background:${s.color}"></i>${escape(name)}<b>${s.count}</b></li>`).join('')}</ul><p>Aproxime para separar os pontos. Elementos das fontes podem representar o mesmo evento e permanecem distintos.</p><details><summary>Consultar os elementos deste grupo</summary><div class="atlas-cluster-items">${c.items.map(f=>popup(f,f.atlasEntry.title)).join('<hr>')}</div></details></div>`;
          marker.bindPopup(detail);
          marker.on('dblclick',()=>map.setView(marker.getLatLng(),Math.min(21,map.getZoom()+2)));
        }
        marker.addTo(pointLayer);
      });
      houses.render(pointFeatures.filter(isHouse));
    }
    function filteredRows(entry,current){
      const features=entry.features||[];
      if(entry.origin?.type!=='sheet_snapshot')return window.SfaAtlasFoldersModel.filter(features,current,entry.selectedFolders,['condominium','reference','cadastre','street_catalog','cnefe'].includes(entry.origin?.type));
      return M.sheetFilter(features.filter(f=>!entry.selectedFolders||entry.selectedFolders.has(f.properties.folder_id||'')).map(f=>{
        const p=f.properties, result=String(p.exam_result||'').toLowerCase();
        return {...p,result_group:/\bnegativo\b/.test(result)?'negative':/\bpositivo\b/.test(result)?'positive':/suspeito|aguard|pendente/.test(result)?'pending':'unknown',feature:f};
      }),current).map(row=>row.feature);
    }
    function redraw(){
      if(redrawPending)return;
      redrawPending=true;
      requestAnimationFrame(()=>{redrawPending=false;paint();});
    }
    function paint(){
      const current=filters();let visible=0, enabled=0;pointFeatures=[];
      entries.forEach(entry=>{
        const rows=filteredRows(entry,current);
        render(entry,rows);visible+=entry.enabled?rows.filter(f=>f.geometry).length:0;enabled+=Number(entry.enabled);
        entry.folderWidget?.refresh(rows);
        entry.input.indeterminate=entry.enabled && entry.selectedFolders.size>0 && entry.selectedFolders.size < 1+(entry.folders||[]).length;
        if(entry.counter)entry.counter.textContent=entry.origin?.type==='cadastre'?`${entry.count} números · ${entry.features?entry.features.filter(f=>f.geometry).length:entry.count-entry.unlocated} posicionados`:entry.enabled?`${rows.length} nos filtros`:`${entry.count ?? 'Restrito'} ${entry.count==null?'':'elementos'}`;
      });
      const active=$('atlas-sinan').checked && sheet;
      if(sheet){
        const rows=M.sheetFilter(sheet.records,current), located=rows.filter(r=>r.geometry), unlocated=rows.filter(r=>!r.geometry);
        sheet.entry.enabled=!!active;
        render(sheet.entry,located.map(r=>({type:'Feature',geometry:r.geometry,properties:{sheet:r}})));
        $('atlas-sheet-count').textContent=active?`${rows.length} ${rows.length===1?'registro':'registros'} · ${located.length} localizados · ${unlocated.length} sem posição`:`${sheet.records.length} registros disponíveis`;
        $('atlas-unlocated').hidden=!active || !unlocated.length;
        $('atlas-unlocated-count').textContent=`${unlocated.length} registros sem posição`;
        $('atlas-unlocated-list').innerHTML=unlocated.slice(0,unlocatedLimit).map(r=>`<a target="_blank" rel="noopener noreferrer" href="${escape(sheet.source.url)}&range=A${r.source_row}:T${r.source_row}"><span>Linha ${r.source_row}${r.sinan?' · SINAN '+escape(r.sinan):''}</span><small>${day(r[current.dateField])} · ${escape(r.exam || 'Exame não informado')} · ${escape(r.exam_result || 'Resultado não informado')} · ${escape(r.classification || 'Classificação não informada')}</small></a>`).join('');
        $('atlas-more-unlocated').hidden=unlocated.length<=unlocatedLimit;
        $('atlas-more-unlocated').textContent=`Mostrar mais ${Math.min(50,unlocated.length-unlocatedLimit)} registros`;
        visible+=active?located.length:0;enabled+=Number(!!active);
      }
      const addresses=entries.filter(e=>e.origin?.type==='cnefe'), selected=addresses.filter(e=>e.enabled).length;
      $('atlas-address-toggle').checked=addresses.length>0&&selected===addresses.length;$('atlas-address-toggle').indeterminate=selected>0&&selected<addresses.length;
      renderPoints();renderHotspots();map.fire('atlaslayerschange');
      const unlocated=entries.filter(e=>e.enabled).reduce((n,e)=>n+filteredRows(e,current).filter(f=>!f.geometry).length,0);
      $('atlas-active-count').textContent=`${enabled} ${enabled===1?'camada ativa':'camadas ativas'} · ${visible} no mapa${unlocated?' · '+unlocated+' sem posição':''}`;
    }
    function makeEntry(item,features=null,previous=null){
      const entry={...item,features,enabled:false,group:L.layerGroup().addTo(map),loading:null,selectedFolders:previous?.selectedFolders,openFolders:previous?.openFolders};
      if(previous){
        const all=['',...(previous.folders||[]).map(n=>n.id)].every(id=>previous.selectedFolders?.has(id));
        if(all)entry.selectedFolders=new Set(['',...(item.folders||[]).map(n=>n.id)]);
      }
      const wrapper=document.createElement('article');wrapper.className='atlas-layer-card';
      const header=document.createElement('div');header.className='atlas-layer-row';wrapper.append(header);
      const body=document.createElement('div');body.className='atlas-layer-body';body.hidden=!(previous?.expanded);wrapper.append(body);
      const expand=document.createElement('button');expand.type='button';expand.className='atlas-layer-expand';expand.textContent=body.hidden?'▸':'▾';expand.setAttribute('aria-label','Subpastas de '+item.title);expand.setAttribute('aria-expanded',String(!body.hidden));expand.disabled=item.allowed===false;
      expand.hidden=!(item.folders?.length);header.append(expand);
      expand.onclick=()=>{body.hidden=!body.hidden;entry.expanded=!body.hidden;expand.textContent=body.hidden?'▸':'▾';expand.setAttribute('aria-expanded',String(!body.hidden));};
      const label=document.createElement('label'), input=document.createElement('input'), info=document.createElement('span'), dot=document.createElement('i'), name=document.createElement('strong'), small=document.createElement('small');
      input.type='checkbox';input.disabled=item.allowed===false;input.setAttribute('aria-label',item.title);
      dot.style.background=item.color;name.textContent=item.title;small.textContent=input.disabled?'Acesso interno SFA necessário':`${item.count} elementos`;
      info.append(name,small);label.append(input,dot,info);header.append(label);
      const focus=document.createElement('button');focus.type='button';focus.className='atlas-focus';focus.textContent='↗';focus.title='Enquadrar '+item.title;focus.setAttribute('aria-label','Enquadrar '+item.title);focus.disabled=input.disabled;
      header.append(focus);entry.input=input;entry.counter=small;entry.expanded=!!previous?.expanded;
      entry.folderWidget=window.SfaAtlasFolders.attach(entry,body,{change:()=>input.onchange(),focus:async node=>{
        if(entry.origin?.type==='cadastre'){window.SfaCadastreViewer.open(dataset,node.id.replace(/^cad-/,''),entry.id,null);return;}
        if(!entry.enabled)entry.selectedFolders=new Set(node.ids);
        input.checked=true;await input.onchange();const rows=filteredRows(entry,filters()).filter(f=>node.ids.has(f.properties.folder_id||''));
        const bounds=L.geoJSON(rows).getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[30,30],maxZoom:18});else notice('Registros sem posição: consulte os cadastros e croquis.');
      }});
      async function load(){
        if(entry.features)return;
        if(!entry.loading)entry.loading=(item.origin?.type==='cnefe'?addressData().then(index=>({features:index.get(item.id)||[]})):fetchJson(dataset.atlas_urls.layer.replace('LAYER',item.id))).then(data=>{entry.features=data.features.map(f=>({...f,properties:{...f.properties,__atlas_layer:item.id}}));}).catch(error=>{entry.loading=null;throw error;});
        await entry.loading;
      }
      entry.load=load;
      input.onclick=()=>{if(input.checked)entry.selectedFolders=new Set(['',...(entry.folders||[]).map(n=>n.id)]);};
      input.onchange=async()=>{
        entry.enabled=input.checked;small.textContent='Carregando…';
        try{if(entry.enabled)await load();redraw();notice('');}catch(error){entry.enabled=false;input.checked=false;redraw();notice(error.message+' As outras camadas continuam disponíveis.');}
      };
      focus.onclick=async()=>{input.checked=true;await input.onchange();const rows=filteredRows(entry,filters());const bounds=L.geoJSON(rows).getBounds();if(bounds.isValid())map.fitBounds(bounds,{padding:[28,28],maxZoom:entry.origin?.type==='condominium'?19:17});else notice('Esta camada tem registros ainda sem posição. Use a busca para consultar o cadastro ou o croqui.');};
      entry.focus=focus.onclick;
      return {entry,wrapper};
    }
    function rebuildYears(){
      const current=$('atlas-year').value,years=new Set(entries.flatMap(e=>e.period_years||[]));
      sheet?.records.forEach(r=>{['notification_date','symptoms_date'].forEach(k=>{if(r[k])years.add(r[k].slice(0,4));});});
      $('atlas-year').replaceChildren(new Option('Todos os anos',''),...[...years].sort().map(y=>new Option(y,y)),new Option('Sem ano informado','unknown'));
      if(years.has(current)||current==='unknown')$('atlas-year').value=current;
    }
    async function loadSheet(force=false){
      if(sheet && !force)return sheet;
      if(!sheetPromise || force)sheetPromise=fetchJson(dataset.atlas_urls.sinan+(force?(dataset.atlas_urls.sinan.includes('?')?'&':'?')+'refresh=1':'')).then(data=>{
        if(sheet?.entry)map.removeLayer(sheet.entry.group);
        sheet={...data,entry:{title:'Planilha · Arboviroses',color:'#d59bfd',group:L.layerGroup().addTo(map),enabled:false}};
        const previous=$('atlas-classification').value, values=[...new Set(sheet.records.map(r=>r.classification).filter(Boolean))].sort();
        $('atlas-classification').replaceChildren(new Option('Todas as classificações',''),...values.map(v=>new Option(v,v)));
        if(values.includes(previous))$('atlas-classification').value=previous;
        const finalPrevious=$('atlas-final-result').value, finalValues=[...new Set(sheet.records.map(r=>r.final_result).filter(Boolean))].sort();
        $('atlas-final-result').replaceChildren(new Option('Todos os resultados finais',''),new Option('Sem resultado final informado','missing'),...finalValues.map(v=>new Option(v,v)));
        if(finalValues.includes(finalPrevious)||finalPrevious==='missing')$('atlas-final-result').value=finalPrevious;
        rebuildYears();$('atlas-sheet-source').textContent='Planilha consultada em '+new Date(data.source.read_at).toLocaleString('pt-BR')+'. '+data.source.note;
        return sheet;
      }).catch(error=>{sheetPromise=null;throw error;});
      return sheetPromise;
    }
    $('atlas-sinan').disabled=!dataset.atlas_urls.clinical_allowed;
    $('atlas-refresh').disabled=!dataset.atlas_urls.clinical_allowed;
    if($('atlas-sinan').disabled)$('atlas-sheet-count').textContent='Acesso interno SFA necessário';
    $('atlas-sinan').onchange=async()=>{try{if($('atlas-sinan').checked){$('atlas-sheet-count').textContent='Consultando planilha…';await loadSheet();}redraw();notice('');}catch(error){$('atlas-sinan').checked=false;$('atlas-sheet-count').textContent='Planilha indisponível';notice(error.message+' Tente atualizar a fonte.');}};
    $('atlas-refresh').onclick=async()=>{try{ $('atlas-refresh').disabled=true;await loadSheet(true);redraw();notice('');}catch(error){notice(error.message);}finally{$('atlas-refresh').disabled=false;}};
    ['atlas-month','atlas-year','atlas-start','atlas-end','atlas-date-field','atlas-result','atlas-final-result','atlas-classification'].forEach(id=>$(id).onchange=()=>{
      if($('atlas-start').value && $('atlas-end').value && $('atlas-start').value>$('atlas-end').value){notice('A data inicial deve vir antes da final.');return;}notice('');redraw();
    });
    $('atlas-more-unlocated').onclick=()=>{unlocatedLimit+=50;redraw();};
    $('atlas-clear-filters').onclick=()=>{['atlas-month','atlas-year','atlas-start','atlas-end','atlas-result','atlas-final-result','atlas-classification'].forEach(id=>$(id).value='');redraw();notice('');};
    async function preset(mode){
      const run=++sequence;
      const tasks=entries.filter(e=>!e.input.disabled).map(async entry=>{
        entry.input.checked=mode==='all'||mode==='field'&&!entry.clinical&&!['cadastre','street_catalog'].includes(entry.origin?.type);entry.enabled=entry.input.checked;
        await entry.input.onchange();
        if(entry.enabled){entry.selectedFolders=new Set(['',...(entry.folders||[]).map(n=>n.id)]);redraw();}
        if(run!==sequence){entry.enabled=entry.input.checked;redraw();}
      });
      if(mode!=='all'){$('atlas-sinan').checked=false;redraw();}
      await Promise.allSettled(tasks);
    }
    $('atlas-show-field').onclick=()=>preset('field');$('atlas-show-all').onclick=()=>preset('all');$('atlas-hide-all').onclick=()=>preset('none');
    $('atlas-show-all').addEventListener('click',()=>{if(!$('atlas-sinan').disabled){$('atlas-sinan').checked=true;$('atlas-sinan').onchange();}});
    let popupPan=false;
    map.on('autopanstart',()=>{popupPan=true;});
    map.on('zoomend',redraw);
    map.on('moveend',()=>{if(popupPan){popupPan=false;return;}redraw();});
    async function refreshCatalog(activate=null){
      const data=await fetchJson(dataset.atlas_urls.catalog), previous=new Map(entries.map(e=>[e.id,e])), enabled=new Set(entries.filter(e=>e.enabled).map(e=>e.id));
      entries.forEach(e=>map.removeLayer(e.group));entries=[];
      addressPromise=null;$('atlas-address-list').replaceChildren();
      $('atlas-earth-list').replaceChildren();$('atlas-local-list').replaceChildren();$('atlas-cadastre-list').replaceChildren();
      source=data.source;
      const addr=data.cnefe_source||{};$('atlas-address-summary').textContent=addr.records?`${addr.number_labels.toLocaleString('pt-BR')} rótulos de imóveis · ${addr.located_records.toLocaleString('pt-BR')} referências no mapa · ${(addr.records-addr.located_records).toLocaleString('pt-BR')} com posição pendente. Organizados em ${addr.neighborhoods} localidades.`:'Base de endereços ainda não importada.';$('atlas-address-toggle').disabled=!addr.records;
      const cad=data.cadastre_source||{};$('atlas-cadastre-summary').textContent=cad.house_numbers?`${cad.house_numbers.toLocaleString('pt-BR')} rótulos de números · ${cad.readable_drawings} croquis · ${cad.street_records} referências de logradouro/CEP. ${cad.drawings_without_numbers} desenhos sem números extraídos; ${cad.unreadable.length} ${cad.unreadable.length===1?'arquivo não lido':'arquivos não lidos'}.`:'Referências cadastrais ainda não importadas.';
      $('atlas-earth-source').textContent=source.imported_at ? `${source.title || 'Google Earth'} · cópia importada em ${new Date(source.imported_at).toLocaleDateString('pt-BR')}. Edições da equipe ficam no atlas.` : 'Importe o projeto completo em Atualizar dados para disponibilizar suas camadas.';
      const loading=[];
      data.layers.forEach(item=>{const created=makeEntry(item,null,previous.get(item.id));entries.push(created.entry);
        $(item.origin?.type==='cnefe'?'atlas-address-list':item.origin?.type==='earth'?'atlas-earth-list':['cadastre','street_catalog'].includes(item.origin?.type)?'atlas-cadastre-list':'atlas-local-list').append(created.wrapper);
        if(enabled.has(item.id)||activate===item.id||!catalogInitialized&&item.default_visible){created.entry.input.checked=true;loading.push(created.entry.input.onchange());}
      });catalogInitialized=true;rebuildYears();
      document.querySelectorAll('[data-atlas-condo]').forEach(button=>{
        const entry=entries.find(e=>e.origin?.type==='condominium'&&e.title.includes(button.dataset.atlasCondo));
        button.disabled=!entry||entry.input.disabled;button.onclick=()=>entry?.focus();
      });
      await Promise.allSettled(loading);await loadHotspots();redraw();
    }
    $('atlas-address-toggle').onchange=async()=>{const checked=$('atlas-address-toggle').checked,items=entries.filter(e=>e.origin?.type==='cnefe');if(checked)try{await addressData();}catch(e){notice(e.message);return;}await Promise.allSettled(items.map(async e=>{e.input.checked=checked;if(checked)e.selectedFolders=new Set(['',...(e.folders||[]).map(f=>f.id)]);await e.input.onchange();}));redraw();};
    map.on('atlasfocusfeature',async event=>{const entry=entries.find(e=>e.id===event.layerId);if(!entry)return;entry.input.checked=true;entry.selectedFolders=new Set(['',...(entry.folders||[]).map(f=>f.id)]);await entry.input.onchange();});
    const H=window.SfaAtlasHotspotsModel, spatial=H.index(territory.features), hotLayer=L.layerGroup().addTo(map);
    let hotKey='',hotSummary=null;
    const hotKind=e=>H.kind(e.title), hotWanted=k=>$(k==='larvae'?'atlas-hot-larvae':'atlas-hot-cases').checked;
    $('atlas-hot-cases').disabled=!dataset.atlas_urls.clinical_allowed;
    async function loadHotspots(){
      const wanted=entries.filter(e=>hotKind(e)&&hotWanted(hotKind(e))&&!e.input.disabled);
      try{await Promise.all(wanted.map(e=>e.load()));notice('');}catch(e){notice(e.message+' A concentração inclui apenas fontes carregadas.');}
      hotKey='';
    }
    function renderHotspots(){
      const enabled=$('atlas-hot-larvae').checked||$('atlas-hot-cases').checked;
      $('atlas-hot-legend').hidden=!enabled;
      const rows=entries.filter(e=>hotKind(e)&&hotWanted(hotKind(e))).flatMap(e=>filteredRows(e,filters()).filter(f=>H.qualifies(f,hotKind(e))).map(f=>({feature:f,kind:hotKind(e),key:e.id+':'+f.id})));
      const key=rows.map(r=>r.key+':'+JSON.stringify(r.feature.geometry)).join('|');
      if(key===hotKey&&hotSummary)return;
      hotKey=key;hotLayer.clearLayers();hotSummary=H.aggregate(rows,spatial);
      hotSummary.blocks.forEach(row=>{
        const p=row.block.properties,total=row.larvae+row.cases,color=total>=5?'#a92e38':total>=2?'#ee8328':'#f5bb66';
        const shape=L.geoJSON(row.block,{pane:'field-hotspots',style:{color,weight:2,fillColor:color,fillOpacity:.48}}).addTo(hotLayer);
        shape.bindTooltip(`<strong>Quadra ${escape(p.block)} · SC ${escape(p.sector)}</strong><br>Larvas: ${row.larvae} · Dengue positivo: ${row.cases}`,{sticky:true});
        shape.bindPopup(`<div class="atlas-popup"><strong>Quadra ${escape(p.block)} · SC ${escape(p.sector)}</strong><p>${row.larvae} registros de larvas · ${row.cases} dengue positivo</p><small>Registros no período e nas pastas selecionadas. Eventos distintos no mesmo imóvel continuam contados separadamente.</small><details><summary>Consultar registros</summary>${row.items.map(r=>popup(r.feature,r.kind==='larvae'?'Larvas':'Dengue positivo')).join('<hr>')}</details></div>`);
      });
      $('atlas-hot-status').textContent=`${hotSummary.blocks.length} quadras · ${hotSummary.located} registros incluídos${hotSummary.outside?' · '+hotSummary.outside+' sem quadra única':''}`;
    }
    ['atlas-hot-larvae','atlas-hot-cases'].forEach(id=>$(id).onchange=async()=>{await loadHotspots();redraw();});
    window.SfaAtlasLayers.refresh=refreshCatalog;
    refreshCatalog().catch(error=>{notice(error.message+' Quadras e mapas originais continuam disponíveis.');});
    redraw();
  }};
})();
