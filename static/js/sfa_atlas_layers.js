(function(){
  'use strict';
  const $=id=>document.getElementById(id), M=window.SfaAtlasLayersModel;
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const day=v=>v ? v.slice(8,10)+'/'+v.slice(5,7)+'/'+v.slice(0,4) : 'Não informada';
  const resultNames={positive:'Positivo',negative:'Negativo',pending:'Pendente / suspeito',unknown:'Sem resultado reconhecido'};
  const resultColors={positive:'#dd7587',negative:'#69bfce',pending:'#edbb6f',unknown:'#bbc3d0'};
  window.SfaAtlasLayers={attach(map,dataset){
    let entries=[], sheet=null, sheetPromise=null, source=null, sequence=0, unlocatedLimit=50, catalogInitialized=false;
    const renderer=L.canvas({padding:.3,pane:'field-events'}), pointLayer=L.layerGroup().addTo(map);
    let pointFeatures=[];
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
      if(p.__atlas_layer && (p.name||p.address||p.notes||p.precision))return `<div class="atlas-popup"><strong>${escape(p.name||p.label||title)}</strong><p class="atlas-popup-path">${escape((p.folder_path||[title,p.category||'Cadastro']).join(' › '))}</p>${p.address?'<p>'+escape(p.address)+'</p>':''}${p.date?'<p>'+day(p.date)+'</p>':p.period_year?'<p>Mês da pasta: '+escape(p.month||'não informado')+' / '+escape(p.period_year)+' · sem dia informado</p>':''}${p.notes?'<p>'+escape(p.notes)+'</p>':''}${p.precision?'<small>'+escape(p.precision)+'</small>':''}${p.position_status?'<small class="editor-point-state">'+escape({imported:'Posição do Earth · a conferir',estimated:'Posição estimada',to_review:'Posição a conferir',verified:'Conferida pela equipe',unlocated:'Sem posição'}[p.position_status]||p.position_status)+'</small>':''}<p><button type="button" data-atlas-layer="${escape(p.__atlas_layer)}" data-atlas-feature="${escape(feature.id)}">Consultar / editar registro</button></p></div>`;
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
      const visible=pointFeatures.filter(f=>!isHouse(f)&&map.getBounds().pad(.1).contains([f.geometry.coordinates[1],f.geometry.coordinates[0]]));
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
      if(entry.origin?.type!=='sheet_snapshot')return window.SfaAtlasFoldersModel.filter(features,current,entry.selectedFolders,['condominium','reference'].includes(entry.origin?.type));
      return M.sheetFilter(features.filter(f=>!entry.selectedFolders||entry.selectedFolders.has(f.properties.folder_id||'')).map(f=>{
        const p=f.properties, result=String(p.exam_result||'').toLowerCase();
        return {...p,result_group:/\bnegativo\b/.test(result)?'negative':/\bpositivo\b/.test(result)?'positive':/suspeito|aguard|pendente/.test(result)?'pending':'unknown',feature:f};
      }),current).map(row=>row.feature);
    }
    function redraw(){
      const current=filters();let visible=0, enabled=0;pointFeatures=[];
      entries.forEach(entry=>{
        const rows=filteredRows(entry,current);
        render(entry,rows);visible+=entry.enabled?rows.length:0;enabled+=Number(entry.enabled);
        entry.folderWidget?.refresh(rows);
        if(entry.counter)entry.counter.textContent=entry.enabled?`${rows.length} nos filtros`:`${entry.count ?? 'Restrito'} ${entry.count==null?'':'elementos'}`;
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
      renderPoints();map.fire('atlaslayerschange');
      $('atlas-active-count').textContent=`${enabled} ${enabled===1?'camada ativa':'camadas ativas'} · ${visible} elementos filtrados`;
    }
    function makeEntry(item,features=null,previous=null){
      const entry={...item,features,enabled:false,group:L.layerGroup().addTo(map),loading:null,selectedFolders:previous?.selectedFolders,openFolders:previous?.openFolders};
      if(previous){
        const all=['',...(previous.folders||[]).map(n=>n.id)].every(id=>previous.selectedFolders?.has(id));
        if(all)entry.selectedFolders=new Set(['',...(item.folders||[]).map(n=>n.id)]);
      }
      const wrapper=document.createElement('div');wrapper.className='atlas-layer-row';
      const label=document.createElement('label'), input=document.createElement('input'), info=document.createElement('span'), dot=document.createElement('i'), name=document.createElement('strong'), small=document.createElement('small');
      input.type='checkbox';input.disabled=item.allowed===false;input.setAttribute('aria-label',item.title);
      dot.style.background=item.color;name.textContent=item.title;small.textContent=input.disabled?'Acesso interno SFA necessário':`${item.count} elementos`;
      info.append(name,small);label.append(input,dot,info);wrapper.append(label);
      const focus=document.createElement('button');focus.type='button';focus.className='atlas-focus';focus.textContent='↗';focus.title='Enquadrar '+item.title;focus.setAttribute('aria-label','Enquadrar '+item.title);focus.disabled=input.disabled;
      wrapper.append(focus);entry.input=input;entry.counter=small;
      entry.folderWidget=window.SfaAtlasFolders.attach(entry,wrapper,{change:()=>input.onchange(),focus:async node=>{
        if(!entry.enabled)entry.selectedFolders=new Set(node.ids);
        input.checked=true;await input.onchange();const rows=filteredRows(entry,filters()).filter(f=>node.ids.has(f.properties.folder_id||''));
        if(rows.length)map.fitBounds(L.geoJSON(rows).getBounds(),{padding:[30,30],maxZoom:18});
      }});
      async function load(){
        if(entry.features)return;
        if(!entry.loading)entry.loading=fetchJson(dataset.atlas_urls.layer.replace('LAYER',item.id)).then(data=>{entry.features=data.features.map(f=>({...f,properties:{...f.properties,__atlas_layer:item.id}}));}).catch(error=>{entry.loading=null;throw error;});
        await entry.loading;
      }
      input.onchange=async()=>{
        entry.enabled=input.checked;small.textContent='Carregando…';
        try{if(entry.enabled)await load();redraw();notice('');}catch(error){entry.enabled=false;input.checked=false;redraw();notice(error.message+' As outras camadas continuam disponíveis.');}
      };
      focus.onclick=async()=>{input.checked=true;await input.onchange();const rows=filteredRows(entry,filters());if(rows.length)map.fitBounds(L.geoJSON(rows).getBounds(),{padding:[28,28],maxZoom:entry.origin?.type==='condominium'?19:17});};
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
        entry.input.checked=mode==='all'||mode==='field'&&!entry.clinical;entry.enabled=entry.input.checked;
        await entry.input.onchange();
        if(entry.enabled){entry.selectedFolders=new Set(['',...(entry.folders||[]).map(n=>n.id)]);redraw();}
        if(run!==sequence){entry.enabled=entry.input.checked;redraw();}
      });
      if(mode!=='all'){$('atlas-sinan').checked=false;redraw();}
      await Promise.allSettled(tasks);
    }
    $('atlas-show-field').onclick=()=>preset('field');$('atlas-show-all').onclick=()=>preset('all');$('atlas-hide-all').onclick=()=>preset('none');
    $('atlas-show-all').addEventListener('click',()=>{if(!$('atlas-sinan').disabled){$('atlas-sinan').checked=true;$('atlas-sinan').onchange();}});
    map.on('zoomend moveend',redraw);
    async function refreshCatalog(activate=null){
      const data=await fetchJson(dataset.atlas_urls.catalog), previous=new Map(entries.map(e=>[e.id,e])), enabled=new Set(entries.filter(e=>e.enabled).map(e=>e.id));
      entries.forEach(e=>map.removeLayer(e.group));entries=[];
      $('atlas-earth-list').replaceChildren();$('atlas-local-list').replaceChildren();
      source=data.source;
      $('atlas-earth-source').textContent=source.imported_at ? `${source.title || 'Google Earth'} · cópia importada em ${new Date(source.imported_at).toLocaleDateString('pt-BR')}. Edições da equipe ficam no atlas.` : 'Importe o projeto completo em Atualizar dados para disponibilizar suas camadas.';
      const loading=[];
      data.layers.forEach(item=>{const created=makeEntry(item,null,previous.get(item.id));entries.push(created.entry);
        $(item.origin?.type==='earth'?'atlas-earth-list':'atlas-local-list').append(created.wrapper);
        if(enabled.has(item.id)||activate===item.id||!catalogInitialized&&item.default_visible){created.entry.input.checked=true;loading.push(created.entry.input.onchange());}
      });catalogInitialized=true;rebuildYears();
      document.querySelectorAll('[data-atlas-condo]').forEach(button=>{
        const entry=entries.find(e=>e.origin?.type==='condominium'&&e.title.includes(button.dataset.atlasCondo));
        button.disabled=!entry||entry.input.disabled;button.onclick=()=>entry?.focus();
      });
      await Promise.allSettled(loading);redraw();
    }
    window.SfaAtlasLayers.refresh=refreshCatalog;
    refreshCatalog().catch(error=>{notice(error.message+' Quadras e mapas originais continuam disponíveis.');});
    redraw();
  }};
})();
