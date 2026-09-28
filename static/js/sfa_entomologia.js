(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const M = window.EntomologiaModel;
  const dataset = JSON.parse($('ento-dataset').textContent);
  const all = dataset.records, features = dataset.census.features;
  const codes = new Set(features.map(f => f.properties.sector));
  const fmt = value => value == null ? '—' : value.toLocaleString('pt-BR', {maximumFractionDigits:1});
  const day = iso => iso.split('-').reverse().join('/');
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {worked:'Imóveis trabalhados',positive:'Imóveis com larvas',aegypti:'Imóveis com A. aegypti',albopictus:'Imóveis com A. albopictus',closed:'Imóveis fechados',refused:'Recusas',aegypti_larvae:'Larvas de A. aegypti',population:'População residente',households:'Domicílios totais',occupied_households:'Particulares ocupados',density:'Densidade (hab./km²)'};
  const state = {rows:[],page:0,census:[],groups:new Map(),visitMap:null,censusMap:null,referenceMap:null};
  const actions = dataset.actions || [];
  const now = new Date();
  const todayIso = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  const openActions = sector => actions.filter(a => a.sector === sector && a.status !== 'VERIFICADA');
  const palette = ['#d0eeea','#80c9bf','#359f98','#097873','#054d50'];
  function options(select, values, empty, chosen='') {
    select.replaceChildren(new Option(empty, ''), ...values.map(value => new Option(value, value)));
    select.value = values.includes(chosen) ? chosen : '';
  }
  function kpi(label, value, note, highlight=false) {
    return `<article class="ento-kpi ${highlight ? 'highlight' : ''}"><div class="label">${escape(label)}</div><div class="value">${value}</div><div class="note">${escape(note)}</div></article>`;
  }
  function filters() {
    return {start:$('date-start').value,end:$('date-end').value,sector:$('sector-filter').value,block:$('block-filter').value,result:$('result-filter').value,species:$('species-filter').value,mapping:$('mapping-filter').value};
  }
  function download(name, rows, columns) {
    const url = URL.createObjectURL(new Blob([M.csv(rows, columns)], {type:'text/csv;charset=utf-8;'}));
    const a = document.createElement('a'); a.href=url; a.download=name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function updateBlocks() {
    const sector = $('sector-filter').value;
    const values = [...new Set(all.filter(r => !sector || r.sector === sector).map(r => r.block))].sort((a,b) => a.localeCompare(b,undefined,{numeric:true}));
    options($('block-filter'), values, 'Todos', $('block-filter').value);
  }
  function selectSector(code) {
    $('sector-filter').value = code;
    updateBlocks(); updateVisits();
  }
  function updateVisits() {
    const f = filters();
    const invalid = !f.start || !f.end || f.start > f.end || !$('date-start').checkValidity() || !$('date-end').checkValidity();
    $('filter-error').hidden = !invalid;
    $('filter-error').textContent = invalid ? 'Informe datas dentro do período disponível, com início anterior ou igual ao fim. O painel mantém o último recorte válido.' : '';
    if (invalid) { $('export-visits').disabled=true; return; }
    state.rows = M.filter(all, f, codes);
    state.groups = M.grouped(state.rows, 'sector');
    state.page = 0;
    const a = M.aggregate(state.rows);
    $('filter-summary').textContent = `${fmt(a.count)} registros • ${fmt(a.sectors)} setores • ${day(f.start)} a ${day(f.end)}`;
    $('visit-kpis').innerHTML = kpi('Registros de visita',fmt(a.count),'Linhas do arquivo no recorte')
      + kpi('Imóveis trabalhados',fmt(a.worked),'Soma nas visitas; pode incluir revisitas')
      + kpi('Imóveis com larvas',fmt(a.positive),'Soma dos valores informados',true)
      + kpi('Preenchimento de larvas',a.coverage == null ? '—' : fmt(a.coverage)+'%',`${fmt(a.informed)} de ${fmt(a.count)} registros`);
    const unmapped = state.rows.filter(r => !codes.has(r.sector));
    $('quality-notice').textContent = a.count
      ? `${fmt(a.missing)} registros sem informação de larvas. ${fmt(unmapped.length)} registros em ${new Set(unmapped.map(r=>r.sector)).size} setores sem correspondência na malha 2022; permanecem nos totais e na tabela.`
      : 'Nenhum registro corresponde aos filtros. Amplie o período ou limpe a seleção.';
    $('visit-detail').innerHTML = '<dl>' + [['A. aegypti — imóveis',a.aegypti],['A. albopictus — imóveis',a.albopictus],['Recipientes com larvas',a.positive_containers],['Larvas de A. aegypti',a.aegypti_larvae],['Imóveis fechados',a.closed],['Recusas',a.refused],['Controle mecânico — imóveis',a.mechanical]].map(([label,value])=>`<dt>${label}</dt><dd>${fmt(value)}</dd>`).join('')+'</dl>';
    updateVisitMap(); updateTrend(); updateRanking(); updateTable();
    $('export-visits').disabled = !a.count;
  }
  function updateTable() {
    const total = state.rows.length, pages = Math.max(1,Math.ceil(total/25));
    const ordered = [...state.rows].reverse().slice(state.page*25,state.page*25+25);
    $('visit-rows').innerHTML = ordered.length ? ordered.map(r => `<tr><td>${day(r.date)}</td><td>${escape(r.sector)}${codes.has(r.sector)?'':' *'}</td><td>${escape(r.block)}</td>${['worked','closed','refused','positive','aegypti','albopictus'].map(k=>`<td>${fmt(r[k])}</td>`).join('')}</tr>`).join('') : '<tr><td colspan="9" class="ento-empty">Nenhum registro neste recorte.</td></tr>';
    $('page-status').textContent = total ? `Página ${state.page+1} de ${pages} • ${fmt(total)} registros` : '0 registros';
    $('page-prev').disabled=state.page===0;
    $('page-next').disabled=state.page+1>=pages;
  }
  function color(value, max) {
    if (value == null) return '#eadbbd';
    if (value === 0) return palette[0];
    return palette[Math.min(4,Math.max(1,Math.ceil(value/Math.max(max,1)*4)))];
  }
  function legend(id, max, label, visits) {
    const items = [[palette[0],'0']];
    for(let i=1;i<=4;i++) items.push([palette[i],`${i===1 ? '> 0' : '> '+fmt(max*(i-1)/4)} até ${fmt(max*i/4)}`]);
    if (!max) items.splice(1);
    items.push(['#eadbbd','Sem informação']);
    if(visits) items.push(['#e2e7e8','Sem registros no recorte']);
    $(id).innerHTML=`<strong>${escape(label)}</strong>`+items.map(([c,t])=>`<span><i class="ento-swatch" style="background:${c}"></i>${t}</span>`).join('');
  }
  function setupMap(id) {
    if (!window.L) {
      $(id).innerHTML='<p class="ento-empty">Não foi possível carregar o mapa. Os indicadores e tabelas continuam disponíveis.</p>'; return null;
    }
    const map = L.map(id,{scrollWheelZoom:false}).setView([-20.720,-47.881],14);
    const tiles=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> | Setores: IBGE 2022'}).addTo(map);
    let warned=false;
    tiles.on('tileerror',()=>{if(!warned){warned=true; const note=document.createElement('p'); note.className='ento-footnote'; note.textContent='Fundo de ruas indisponível. Os limites censitários e dados permanecem visíveis.'; $(id).after(note);}});
    return map;
  }
  function fitCity(map) {
    if (!map) return;
    const urban=features.filter(f=>f.properties.situation==='Urbana');
    map.fitBounds(L.geoJSON(urban).getBounds(),{padding:[18,18]});
  }
  function updateVisitMap() {
    if (!state.visitMap) {state.visitMap=setupMap('visits-map'); if(state.visitMap) fitCity(state.visitMap);}
    if (!state.visitMap) return;
    const metric=$('map-metric').value;
    const max=Math.max(0,...[...state.groups].filter(([code])=>codes.has(code)).map(([,a])=>a[metric]||0));
    if(state.visitLayer) state.visitLayer.remove();
    state.visitLayer=L.geoJSON(features,{
      style:feature=>{const a=state.groups.get(feature.properties.sector); return {color:'#537b7d',weight:1,fillOpacity:.78,fillColor:!a?'#e2e7e8':color(a[metric],max)};},
      onEachFeature:(feature,layer)=>{
        const code=feature.properties.sector,a=state.groups.get(code);
        layer.bindTooltip(`Setor ${code.slice(-4)} • ${a ? fmt(a[metric]) : 'sem registros'}`);
        layer.on('click',()=>selectSector(code));
      }
    }).addTo(state.visitMap);
    if($('sector-filter').value) state.visitLayer.eachLayer(layer=>{if(layer.feature.properties.sector===$('sector-filter').value){layer.setStyle({weight:3,color:'#c56616'});state.visitMap.fitBounds(layer.getBounds(),{padding:[35,35],maxZoom:16});}});
    legend('map-legend',max,labels[metric],true);
    addLayers();
  }
  function addLayers() {
    const layers = dataset.layers || [];
    if (!layers.length || state.overlays || !state.visitMap) return;
    const colors = ['#c56616','#6b4fbb','#d6336c','#2f6fb3','#2b8a3e'];
    const popup = p => `<div class="ento-popup"><strong>${escape(p.name || 'Sem nome')}</strong>${p.folder ? `<small>${escape(p.folder)}</small><br>` : ''}${p.description ? escape(p.description) : ''}</div>`;
    state.overlays = {};
    layers.forEach((item, index) => {
      const color = colors[index % colors.length];
      const layer = L.geoJSON(item.geojson, {
        style: () => ({color, weight: 2, fillOpacity: .12}),
        pointToLayer: (feature, latlng) => L.circleMarker(latlng, {radius: 6, color: '#fff', weight: 1.5, fillColor: color, fillOpacity: .95}),
        onEachFeature: (feature, target) => target.bindPopup(popup(feature.properties || {}))
      }).addTo(state.visitMap);
      state.overlays[`<span style="color:${color}">■</span> ${escape(item.title)}`] = layer;
    });
    L.control.layers(null, state.overlays, {collapsed: false}).addTo(state.visitMap);
    $('layers-note').hidden = false;
    $('layers-note').textContent = `${layers.length} camada(s) enviada(s) pela equipe (Google Earth) sobre o mapa. Use a caixa no canto para mostrar ou ocultar.`;
  }
  function updateTrend() {
    const points=M.timeline(state.rows,$('date-start').value,$('date-end').value,$('trend-metric').value);
    const max=Math.max(1,...points.map(p=>p.value||0)), width=620,height=250,left=42,bottom=205,plotH=160;
    const step=(width-left-12)/Math.max(points.length,1),bar=Math.min(35,step*.65);
    let svg=`<svg class="ento-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(labels[$('trend-metric').value])} por mês">`;
    for(let i=0;i<3;i++){let y=bottom-i*plotH/2;svg+=`<line x1="${left}" x2="${width-8}" y1="${y}" y2="${y}" stroke="#e3ecec"/><text x="${left-6}" y="${y+4}" text-anchor="end">${fmt(max*i/2)}</text>`;}
    points.forEach((p,i)=>{const x=left+step*i+step/2,h=(p.value||0)/max*plotH;svg+=`<g><title>${p.month}: ${p.value==null?'sem informação':fmt(p.value)} (${p.count} registros)</title><rect x="${x-bar/2}" y="${bottom-h}" width="${bar}" height="${h}" rx="3" fill="#13878a"/><text x="${x}" y="${p.value==null?bottom-8:bottom-h-8}" text-anchor="middle">${p.value==null?'s/i':fmt(p.value)}</text><text x="${x}" y="${bottom+22}" text-anchor="middle">${p.month.slice(5)}/${p.month.slice(2,4)}</text></g>`;});
    $('trend-chart').innerHTML=svg+'</svg>';
  }
  function updateRanking() {
    const ranking=[...state.groups].filter(([,a])=>a.positive>0).sort((a,b)=>b[1].positive-a[1].positive).slice(0,8);
    $('ranking-chart').innerHTML=ranking.length?ranking.map(([code,a])=>`<div class="ento-rank"><button type="button" data-sector="${code}" title="Filtrar setor ${code}">Setor ${code.slice(-4)}${codes.has(code)?'':' *'}</button><div class="ento-bar-track"><div class="ento-bar" style="width:${a.positive/ranking[0][1].positive*100}%"></div></div><strong>${fmt(a.positive)}</strong></div>`).join('')+'<p class="ento-footnote mt-3">* Código sem correspondência na malha 2022.</p>':'<p class="ento-empty">Nenhum valor positivo informado neste recorte.</p>';
    $('ranking-chart').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>selectSector(button.dataset.sector)));
  }
  function updateCensus() {
    state.census=features.filter(f=>(!$('census-sector').value||f.properties.sector===$('census-sector').value)&&(!$('census-situation').value||f.properties.situation===$('census-situation').value));
    const rows=state.census.map(f=>f.properties);
    const censusTotal=key=>rows.length&&rows.every(r=>r[key]!=null)?M.sumKnown(rows,key):null;
    $('census-kpis').innerHTML=kpi('Setores selecionados',fmt(rows.length),'Malha do Censo 2022')+kpi('População residente',fmt(censusTotal('population')),'Pessoas • referência 2022',true)+kpi('Domicílios totais',fmt(censusTotal('households')),'Todas as categorias censitárias')+kpi('Particulares ocupados',fmt(censusTotal('occupied_households')),'Domicílios • referência 2022');
    const metric=$('census-metric').value,value=p=>metric==='density'?M.density(p):p[metric];
    const max=Math.max(0,...rows.map(p=>value(p)||0));
    if(!state.censusMap){state.censusMap=setupMap('census-map');if(state.censusMap) fitCity(state.censusMap);}
    if(state.censusMap){
      if(state.censusLayer)state.censusLayer.remove();
      state.censusLayer=L.geoJSON(state.census,{style:f=>({color:'#537b7d',weight:1,fillOpacity:.78,fillColor:color(value(f.properties),max)}),onEachFeature:(feature,layer)=>{const p=feature.properties;layer.bindTooltip(`Setor ${p.sector.slice(-4)} • ${fmt(value(p))}`);layer.on('click',()=>{$('census-sector').value=p.sector;updateCensus();});}}).addTo(state.censusMap);
      if($('census-sector').value&&state.census.length)state.censusMap.fitBounds(state.censusLayer.getBounds(),{padding:[25,25],maxZoom:16});
    }
    legend('census-legend',max,labels[metric],false);
    $('census-rows').innerHTML=rows.length?rows.map(p=>`<tr><td>${p.sector}</td><td>${escape(p.situation)}</td><td>${fmt(p.population)}</td><td>${fmt(p.households)}</td><td>${fmt(p.occupied_households)}</td><td>${p.area_km2==null?'—':p.area_km2.toLocaleString('pt-BR',{maximumFractionDigits:3})}</td><td>${fmt(M.density(p))}</td></tr>`).join(''):'<tr><td colspan="7" class="ento-empty">Nenhum setor corresponde à seleção.</td></tr>';
    $('export-census').disabled=!rows.length;
  }
  function reference() {
    if(!window.L)return;
    const maps=dataset.reference_maps||[];
    if(!maps.length){$('reference-map').innerHTML='<p class="ento-empty">Mapas de referência indisponíveis.</p>';return;}
    if(!state.referenceMap){state.referenceMap=L.map('reference-map',{crs:L.CRS.Simple,minZoom:-3,scrollWheelZoom:false});maps.forEach((m,i)=>$('reference-select').add(new Option(m.title,String(i))));$('reference-select').value=String(Math.max(0,maps.findIndex(m=>m.title==='MAPA VETORES 2018')));}
    const selected=maps[Number($('reference-select').value)||0],bounds=[[0,0],[selected.height,selected.width]];
    if(state.referenceLayer)state.referenceLayer.remove();
    state.referenceLayer=L.imageOverlay(selected.url,bounds).addTo(state.referenceMap);
    state.referenceLayer.on('error',()=>{$('ento-error').hidden=false;$('ento-error').textContent='Não foi possível carregar a imagem do mapa de campo.';});
    state.referenceMap.fitBounds(bounds);
  }
  const queueColumns = {
    focus:[['positive','Com larvas'],['aegypti','A. aegypti'],['previous_positive','Com larvas: anterior'],['positive_days','Datas com achado'],['coverage','Preenchimento (%)']],
    access:[['closed','Fechados'],['refused','Recusas'],['worked','Trabalhados'],['coverage','Preenchimento (%)']],
    quality:[['missing','Sem resultado de larvas'],['count','Registros'],['coverage','Preenchimento (%)']]
  };
  function updatePlanning() {
    const end=$('planning-end').value;
    const invalid=!end||!$('planning-end').checkValidity();
    $('planning-error').hidden=!invalid;
    if(invalid){$('planning-error').textContent='Escolha uma data dentro do período disponível. A lista mantém o último recorte válido.';$('export-planning').disabled=true;return;}
    const plan=M.planning(all,end,Number($('planning-window').value),$('planning-sector').value,$('planning-scale').value);
    state.plan=plan;
    const kind=$('planning-queue').value, queue=M.workQueue(plan.groups,kind), a=plan.current;
    state.queue=queue;
    const now=new Date(), today=new Date(Date.UTC(now.getFullYear(),now.getMonth(),now.getDate()));
    const age=Math.round((today-new Date(dataset.source.end+'T00:00:00Z'))/86400000);
    $('planning-freshness').textContent=`Último registro no arquivo: ${day(dataset.source.end)}${age>=0?` (${age} dias antes da data de hoje)`:' (data posterior à data de hoje; conferir a fonte)'}. Fotografia importada, sem atualização automática. A lista não informa a situação atual de cada imóvel.`;
    $('planning-period').textContent=`${day(plan.start)} a ${day(plan.end)} • ${fmt(a.count)} registros em ${fmt(a.sectors)} setores. Filtros independentes da aba Entomologia.`;
    $('planning-kpis').innerHTML=kpi('Imóveis com larvas',fmt(a.positive),'Soma dos valores informados',true)+kpi('Ocorrências de fechados',fmt(a.closed),'Conferir retornos já realizados')+kpi('Ocorrências de recusa',fmt(a.refused),'Conferir motivos e retornos')+kpi('Preenchimento de larvas',a.coverage==null?'—':fmt(a.coverage)+'%',`${fmt(a.informed)} de ${fmt(a.count)} registros`);
    const rules={focus:'Ordenação: maior soma de A. aegypti, depois maior soma de imóveis com larvas, depois achado mais recente. Conferir a identificação da espécie, o local e as ações já realizadas.',access:'Ordenação: maior soma de imóveis fechados, depois recusas. Conferir se os endereços seguem pendentes e planejar retornos conforme a disponibilidade dos moradores.',quality:'Ordenação: maior número de registros sem resultado de larvas. Revisar a ficha original e distinguir não examinado, não informado e zero; não preencher zeros por suposição.'};
    $('planning-rule').textContent=rules[kind];
    const unmapped=queue.filter(r=>!codes.has(r.sector)).length;
    $('planning-count').textContent=`Exibindo ${Math.min(20,queue.length)} de ${fmt(queue.length)} territórios candidatos. CSV inclui a lista completa. ${fmt(unmapped)} sem código na malha 2022.`;
    const columns=queueColumns[kind];
    $('planning-head').innerHTML='<tr><th>Território</th>'+columns.map(([,label])=>`<th>${label}</th>`).join('')+'<th>Último registro</th><th>Consultar</th></tr>';
    $('planning-rows').innerHTML=queue.length?queue.slice(0,20).map((r,index)=>{const open=openActions(r.sector);return `<tr><td><strong>Setor ${escape(r.sector.slice(-4))}${codes.has(r.sector)?'':' *'}</strong><small class="ento-code">${escape(r.sector)}${$('planning-scale').value==='block'?` • área ${escape(r.area)} / quadra ${escape(r.block)}`:''}</small>${open.length?`<span class="ento-badge ok">${open.length} ação(ões) em aberto: ${open.map(a=>'#'+a.id).join(', ')}</span>`:''}</td>${columns.map(([key])=>`<td>${fmt(r[key])}</td>`).join('')}<td>${day(r.last_visit)}</td><td><div class="ento-row-actions"><button class="btn btn-sm btn-outline-secondary" type="button" data-queue-index="${index}">Ver registros</button><button class="btn btn-sm btn-outline-primary" type="button" data-action-index="${index}">Criar ação</button></div></td></tr>`;}).join(''):`<tr><td colspan="${columns.length+3}" class="ento-empty">Nenhum território com esse sinal no recorte. Isso não comprova ausência de risco.</td></tr>`;
    $('planning-rows').querySelectorAll('[data-action-index]').forEach(button=>button.addEventListener('click',()=>openActionDialog(state.queue[Number(button.dataset.actionIndex)],kind,plan)));
    $('planning-rows').querySelectorAll('[data-queue-index]').forEach(button=>button.addEventListener('click',()=>{
      const r=state.queue[Number(button.dataset.queueIndex)];
      $('date-start').value=plan.start<dataset.source.start?dataset.source.start:plan.start;$('date-end').value=plan.end;
      $('sector-filter').value=r.sector;updateBlocks();$('block-filter').value=r.block;
      ['result-filter','species-filter','mapping-filter'].forEach(id=>$(id).value='');
      activate('visits');$('tab-visits').focus();
    }));
    const partial=plan.previousStart<dataset.source.start;
    $('planning-comparison-note').textContent=`Atual: ${day(plan.start)} a ${day(plan.end)}. Anterior: ${day(plan.previousStart)} a ${day(plan.previousEnd)}. ${partial?`Atenção: o arquivo não cobre toda a janela ${plan.start<dataset.source.start?'atual nem a anterior':'anterior'}; a comparação é incompleta.`:'Janelas com igual duração dentro do período do arquivo; locais e preenchimento podem diferir.'}`;
    $('planning-comparison').innerHTML=[['count','Registros'],['sectors','Setores com registros'],['worked','Imóveis trabalhados'],['positive','Imóveis com larvas'],['closed','Imóveis fechados'],['refused','Recusas'],['coverage','Preenchimento de larvas (%)']].map(([key,label])=>`<tr><td>${label}</td><td>${fmt(a[key])}</td><td>${fmt(plan.previous[key])}</td></tr>`).join('');
    $('export-planning').disabled=!queue.length;
  }
  const statusLabels = {ABERTA:'Aberta', EM_ANDAMENTO:'Em andamento', EXECUTADA:'Executada — aguardando verificação', VERIFICADA:'Verificada'};
  const transitions = {ABERTA:[['EM_ANDAMENTO','Em andamento'],['EXECUTADA','Executada']], EM_ANDAMENTO:[['EXECUTADA','Executada']],
    EXECUTADA:[['VERIFICADA','Verificada'],['ABERTA','Reabrir']], VERIFICADA:[['ABERTA','Reabrir']]};
  function renderActions() {
    const panel = $('acoes-territoriais');
    if (!panel) return;
    const canEdit = panel.dataset.podeAlterar === '1', csrf = panel.dataset.csrf, trabalho = panel.dataset.trabalhoUrl;
    const url = id => panel.dataset.andamentoUrl.replace('/acoes/0/', `/acoes/${id}/`);
    let owner = ''; try { owner = localStorage.getItem('ento-responsavel') || ''; } catch (error) { /* sem armazenamento local */ }
    const open = actions.filter(a => a.status !== 'VERIFICADA').sort((a,b) => (a.prazo||'').localeCompare(b.prazo||'') || a.id-b.id);
    const done = actions.filter(a => a.status === 'VERIFICADA').sort((a,b) => (b.verificado_em||'').localeCompare(a.verificado_em||'')).slice(0, 10);
    const field = (name, label, type='text') => `<div><label>${label}<input type="${type}" name="${name}" ${type==='number'?'min="0" step="0.01"':''} maxlength="3000"></label></div>`;
    const form = a => canEdit && a.territorial ? `<details class="mt-2"><summary>Registrar andamento</summary><form method="post" action="${escape(url(a.id))}" class="ento-form-stack mt-2">
        <input type="hidden" name="csrf_token" value="${escape(csrf)}">
        <div><label>Nova situação<select name="status" required>${(transitions[a.status]||[]).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select></label></div>
        ${field('resultado','Resultado (obrigatório ao executar ou verificar)')}${field('evidencia_verificacao','Evidência da verificação (obrigatória ao verificar)')}
        <div class="ento-inline-form">${field('horas','Horas aplicadas','number')}${field('custo','Custo em R$','number')}</div>
        <div><label>Responsável<input name="responsavel" maxlength="160" required value="${escape(owner)}"></label></div>
        <button class="btn btn-sm btn-primary">Salvar andamento</button></form></details>`
      : (trabalho ? `<a class="ento-footnote px-0" href="${escape(trabalho)}#acoes">Atualizar em Organização do trabalho</a>` : '');
    const item = a => `<article class="ento-action ${a.status==='VERIFICADA'?'done':''}"><div class="ento-action-head"><strong>#${a.id} ${escape(a.tipo)}</strong><span class="ento-badge ${a.status==='VERIFICADA'?'ok':''}">${escape(statusLabels[a.status]||a.status)}</span></div>
      <div class="ento-code">Setor ${escape(a.sector)} • prazo <span class="${a.status!=='VERIFICADA'&&a.prazo&&a.prazo<todayIso?'text-danger fw-bold':''}">${day(a.prazo||'')}</span>${a.responsavel?` • ${escape(a.responsavel)}`:''}</div>
      ${a.motivo?`<p class="mb-1">${escape(a.motivo)}</p>`:''}${a.resultado?`<p class="mb-1"><em>Resultado:</em> ${escape(a.resultado)}</p>`:''}${a.status!=='VERIFICADA'?form(a):''}</article>`;
    $('acoes-lista').innerHTML = (open.length ? open.map(item).join('') : '<p class="ento-empty">Nenhuma ação territorial em aberto. Use “Criar ação” nas listas acima.</p>')
      + (done.length ? `<details class="mt-3"><summary>Verificadas recentemente (${done.length})</summary>${done.map(item).join('')}</details>` : '');
    $('acoes-lista').querySelectorAll('form').forEach(f => f.addEventListener('submit', () => { try { localStorage.setItem('ento-responsavel', f.responsavel.value); } catch (error) { /* sem armazenamento local */ } }));
  }
  function goToActions() { activate('planning'); requestAnimationFrame(() => $('acoes-territoriais').scrollIntoView({behavior:'smooth'})); }
  const actionTypes = {focus:'Verificar foco registrado', access:'Recuperar acesso aos imóveis', quality:'Completar registro de campo'};
  function openActionDialog(r, kind, plan) {
    const block = $('planning-scale').value==='block' ? ` • área ${r.area} / quarteirão ${r.block}` : '';
    const facts = {focus:`${fmt(r.positive)} ocorrência(s) com larvas, ${fmt(r.aegypti)} com A. aegypti; último achado em ${day(r.last_positive||r.last_visit)}.`,
      access:`${fmt(r.closed)} imóveis fechados e ${fmt(r.refused)} recusas em ${fmt(r.count)} registros.`,
      quality:`${fmt(r.missing)} de ${fmt(r.count)} registros sem resultado de larvas.`}[kind];
    const goal = {focus:'Objetivo: conferir a espécie, o local e a eliminação dos criadouros; registrar o resultado.',
      access:'Objetivo: combinar retornos (horários alternativos, contato com ACS) e registrar quantos imóveis foram inspecionados.',
      quality:'Objetivo: revisar as fichas originais e distinguir zero, não examinado e não informado.'}[kind];
    $('action-sector').value = r.sector;
    $('action-territory').textContent = `Setor ${r.sector}${block}`;
    $('action-type').value = actionTypes[kind];
    $('action-reason').value = `Planejamento ${day(plan.start)} a ${day(plan.end)}${block}: ${facts} ${goal}`;
    const deadline = new Date(); deadline.setDate(deadline.getDate()+7);
    $('action-deadline').value = `${deadline.getFullYear()}-${String(deadline.getMonth()+1).padStart(2,'0')}-${String(deadline.getDate()).padStart(2,'0')}`;
    $('action-deadline').min = todayIso;
    try { $('action-owner').value = localStorage.getItem('ento-responsavel') || ''; } catch (error) { /* sem armazenamento local */ }
    if ($('action-dialog').showModal) $('action-dialog').showModal(); else $('action-dialog').setAttribute('open','');
  }
  function badge(item, mode) {
    const pct = item.target ? Math.max(0, Math.min(100, item.id==='access' ? (item.value==null?0:100*Math.min(1,item.target/Math.max(item.value,0.1))) : 100*(item.value||0)/item.target)) : 0;
    const unit = ['quality','access'].includes(item.id) ? '%' : '';
    const value = item.value==null ? '—' : fmt(item.value)+unit;
    const target = item.target==null ? 'sem base' : (item.id==='access'?'até ':'')+fmt(item.target)+unit;
    const status = mode==='progress' ? (item.earned ? 'Meta alcançada' : item.noBase ? 'Sem base de comparação' : 'Em andamento') : (item.earned ? 'Conquistada' : item.noBase ? 'Sem base' : 'Não alcançada');
    return `<article class="ento-badge-card ${item.earned?'earned':''}"><div class="ento-badge-icon" aria-hidden="true"><i class="fas ${item.icon}"></i></div><div><div class="ento-badge-status">${status}</div><h3>${escape(item.title)}</h3><div class="ento-badge-value"><strong>${value}</strong> <span>meta: ${target}</span></div>${mode==='progress'&&!item.noBase?`<div class="ento-progress" role="progressbar" aria-valuenow="${Math.round(pct)}" aria-valuemin="0" aria-valuemax="100" aria-label="${escape(item.title)}"><div style="width:${pct}%"></div></div>`:''}<p>${escape(item.text)}${item.overdue?` ${fmt(item.overdue)} ação(ões) com prazo vencido.`:''}</p></div></article>`;
  }
  function updateTeam() {
    const end = dataset.source.end;
    const firstWeek = M.weekStart(dataset.source.start);
    const totalWeeks = Math.round((new Date(M.weekStart(end)+'T12:00:00Z')-new Date(firstWeek+'T12:00:00Z'))/604800000)+1;
    const weeks = M.teamWeeks(all, end, Math.max(totalWeeks, 9));
    const current = weeks[weeks.length-1], complete = current.partial ? weeks.slice(0,-1) : weeks;
    const last = complete[complete.length-1];
    const cover = M.baseline(weeks,'coverage');
    $('team-headline').innerHTML = `Semana de <strong>${day(current.start)} a ${day(current.end)}</strong>${current.partial?' (em andamento no arquivo)':''}: <strong>${fmt(current.blocks)}</strong> quarteirões em <strong>${fmt(current.sectors)}</strong> setores; resultado de larvas em <strong>${current.coverage==null?'—':fmt(current.coverage)+'%'}</strong> das visitas${cover==null?'':` (média recente: ${fmt(cover)}%)`}. Sequência: <strong>${fmt(M.streak(weeks))}</strong> semanas com envio.`;
    const steps = M.nextSteps(all, actions, end, todayIso);
    const pub = dataset.publication;
    if (!pub || pub.fim < M.shiftDate(end, -7)) steps.push({kind:'publish'});
    const planningLink = '<button type="button" class="btn btn-link p-0 align-baseline" data-go="planning">abrir o Planejamento</button>';
    const text = {data:s=>`<i class="fas fa-upload"></i> O último registro é de ${day(end)} (${s.days} dias atrás). <a href="${document.querySelector('.ento-hero-actions a').href}">Envie a exportação mais recente</a> para as metas refletirem o trabalho real.`,
      focus:s=>`<i class="fas fa-bug"></i> ${s.total} setor(es) com foco nos últimos 14 dias sem ação aberta: ${s.sectors.map(c=>'setor '+escape(c.slice(-4))).join(', ')}${s.total>s.sectors.length?` e mais ${s.total-s.sectors.length}`:''}. Crie a ação no ${planningLink}.`,
      overdue:s=>`<i class="fas fa-clock"></i> ${s.total} ação(ões) territorial(is) com prazo vencido. <button type="button" class="btn btn-link p-0 align-baseline" data-go-actions>Atualizar andamento</button>.`,
      publish:()=>`<i class="fas fa-bullhorn"></i> ${pub?`O boletim público vai até ${day(pub.fim)}.`:'Ainda não há boletim público.'} <a href="${document.querySelector('.ento-hero-actions a').href}#publicar">Confira a prévia e publique</a> para a população acompanhar o trabalho.`,
      verify:s=>`<i class="fas fa-magnifying-glass"></i> ${s.total} ação(ões) executada(s) aguardando verificação do resultado. <button type="button" class="btn btn-link p-0 align-baseline" data-go-actions>Verificar</button>.`};
    $('team-next').innerHTML = steps.length ? steps.map(s=>`<li>${text[s.kind](s)}</li>`).join('') : '<li><i class="fas fa-circle-check"></i> Nada pendente nas verificações automáticas. Bom trabalho!</li>';
    $('team-next').querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>{activate(b.dataset.go);$('tab-'+b.dataset.go).focus();}));
    $('team-next').querySelectorAll('[data-go-actions]').forEach(b=>b.addEventListener('click',goToActions));
    $('team-progress-note').textContent = current.partial ? `Registros de ${day(current.start)} até ${day(end)}. A barra mostra quanto falta para igualar a média das últimas semanas.` : 'A semana mais recente do arquivo está completa; confira abaixo as conquistas.';
    $('team-progress').innerHTML = M.achievements(weeks, actions, todayIso).map(item=>badge(item,'progress')).join('');
    $('team-badges-note').textContent = last ? `Semana de ${day(last.start)} a ${day(last.end)}.` : '';
    $('team-badges').innerHTML = last ? M.achievements(complete, actions, todayIso).map(item=>badge(item,'final')).join('') : '<p class="ento-empty">Ainda não há semana completa no arquivo.</p>';
    const history = complete.slice(-8).map((w,i,arr)=>({week:w, items:M.achievements(complete.slice(0, complete.length-arr.length+i+1), actions, todayIso)}));
    $('team-history-head').innerHTML = '<tr><th>Conquista</th>'+history.map(h=>`<th>${day(h.week.start)}</th>`).join('')+'</tr>';
    $('team-history').innerHTML = (history[0]?.items||[]).map((item,row)=>`<tr><td><i class="fas ${item.icon}" aria-hidden="true"></i> ${escape(item.title)}</td>${history.map(h=>{const it=h.items[row];return `<td>${h.week.count===0?'<span class="ento-dot-empty" title="Sem registros">·</span>':it.earned?'<span class="ento-dot-earned" title="Conquistada">●</span>':'<span class="ento-dot-miss" title="Não alcançada">○</span>'}</td>`;}).join('')}</tr>`).join('');
    const cyc = M.cycle(all, end), pct = cyc.blocksKnown ? 100*cyc.blocksVisited/cyc.blocksKnown : 0;
    $('team-cycle-note').textContent = `Ciclo ${cyc.number} (${day(cyc.start)} até ${day(cyc.end)}): ${fmt(cyc.blocksVisited)} de ${fmt(cyc.blocksKnown)} quarteirões conhecidos (${fmt(pct)}%). ${fmt(cyc.done)} setor(es) com todos os quarteirões visitados.`;
    $('team-cycle-bar').setAttribute('aria-valuenow', Math.round(pct)); $('team-cycle-bar').firstElementChild.style.width = pct+'%';
    $('team-cycle-sectors').innerHTML = cyc.sectors.slice(0,12).map(r=>`<div class="ento-rank"><button type="button" data-sector="${escape(r.sector)}" title="Ver registros do setor ${escape(r.sector)}">Setor ${escape(r.sector.slice(-4))}</button><div class="ento-bar-track"><div class="ento-bar" style="width:${r.pct}%"></div></div><strong>${r.visited}/${r.known}</strong></div>`).join('') + (cyc.sectors.length>12?`<p class="ento-footnote px-0">Mostrando os 12 setores com menor cobertura de ${cyc.sectors.length}.</p>`:'');
    $('team-cycle-sectors').querySelectorAll('[data-sector]').forEach(b=>b.addEventListener('click',()=>{$('date-start').value=cyc.start<dataset.source.start?dataset.source.start:cyc.start;$('date-end').value=end;activate('visits');selectSector(b.dataset.sector);$('tab-visits').focus();}));
    const withData = weeks.filter(w=>w.count>0 && !w.partial);
    const best = (key, label, unit='') => { const top = withData.filter(w=>w[key]!=null).sort((a,b)=>b[key]-a[key])[0]; return top?`<div class="ento-record"><span>${label}</span><strong>${fmt(top[key])}${unit}</strong><small>semana de ${day(top.start)}</small></div>`:''; };
    $('team-records').innerHTML = best('blocks','Mais quarteirões percorridos') + best('coverage','Maior preenchimento de larvas','%') + best('mechanical','Mais imóveis com controle mecânico') || '<p class="ento-empty">Sem semanas completas.</p>';
    const recent = weeks.slice(-12), max = Math.max(1,...recent.map(w=>w.blocks)), base = M.baseline(weeks,'blocks');
    const width=560,height=210,left=36,bottom=170,plotH=130,step=(width-left-8)/recent.length,bar=Math.min(30,step*.62);
    let svg=`<svg class="ento-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Quarteirões por semana">`;
    recent.forEach((w,i)=>{const x=left+step*i+step/2,h=w.blocks/max*plotH;svg+=`<g><title>Semana de ${day(w.start)}: ${fmt(w.blocks)} quarteirões${w.partial?' (em andamento)':''}</title><rect x="${x-bar/2}" y="${bottom-h}" width="${bar}" height="${h}" rx="3" fill="#13878a" opacity="${w.partial?.45:1}"/><text x="${x}" y="${bottom-h-6}" text-anchor="middle">${w.count?fmt(w.blocks):'—'}</text><text x="${x}" y="${bottom+18}" text-anchor="middle">${day(w.start).slice(0,5)}</text></g>`;});
    if(base!=null){const y=bottom-base/max*plotH;svg+=`<line x1="${left}" x2="${width-8}" y1="${y}" y2="${y}" stroke="#c56616" stroke-dasharray="5 4"/><text x="${width-8}" y="${y-6}" text-anchor="end" fill="#c56616">meta ${fmt(base)}</text>`;}
    $('team-chart').innerHTML=svg+'</svg>';
  }
  function activate(view) {
    document.querySelectorAll('[data-view]').forEach(button=>{const active=button.dataset.view===view;button.setAttribute('aria-selected',active);button.tabIndex=active?0:-1;$('panel-'+button.dataset.view).hidden=!active;});
    if(view==='team')updateTeam();
    if(view==='planning'){updatePlanning();renderActions();}
    if(view==='census')updateCensus();
    if(view==='reference')reference();
    if(view==='visits')updateVisits();
    requestAnimationFrame(()=>{const map=state[{visits:'visitMap',census:'censusMap',reference:'referenceMap'}[view]];if(map)map.invalidateSize();});
  }
  try {
    $('source-period').textContent=`${day(dataset.source.start)} a ${day(dataset.source.end)}`;
    if(dataset.source.imported_at)$('source-updated').textContent=`Atualizada em ${day(dataset.source.imported_at.slice(0,10))} • ${(dataset.updates||[]).length} envio(s) da equipe`;
    $('source-area').textContent=`Área operacional: ${[...new Set(all.map(r=>r.area))].join(', ')} • fonte municipal`;
    ['date-start','date-end'].forEach(id=>{$(id).min=dataset.source.start;$(id).max=dataset.source.end;});
    $('date-start').value=dataset.source.start;$('date-end').value=dataset.source.end;
    options($('sector-filter'),[...new Set([...all.map(r=>r.sector),...codes])].sort(),'Todos os setores');
    options($('census-sector'),[...codes].sort(),'Todo o município');updateBlocks();
    options($('planning-sector'),[...new Set(all.map(r=>r.sector))].sort(),'Todos os setores');
    $('planning-end').min=dataset.source.start;$('planning-end').max=dataset.source.end;$('planning-end').value=dataset.source.end;
    $('planning-filters').addEventListener('submit',event=>{event.preventDefault();updatePlanning();});
    $('planning-filters').addEventListener('change',updatePlanning);
    $('planning-queue').addEventListener('change',updatePlanning);
    $('export-planning').addEventListener('click',()=>download(`planejamento-${$('planning-queue').value}-${state.plan.end}.csv`,state.queue.map(r=>({...r,start:state.plan.start,end:state.plan.end,previous_start:state.plan.previousStart,previous_end:state.plan.previousEnd,queue:$('planning-queue').selectedOptions[0].textContent,mapping:codes.has(r.sector)?'Código presente; limites a validar':'Código ausente',status:'Candidato para revisão; situação atual não informada'})),[['start','Início'],['end','Fim'],['previous_start','Início anterior'],['previous_end','Fim anterior'],['queue','Frente de trabalho'],['status','Situação'],['area','Área'],['sector','Setor'],['block','Quarteirão'],['mapping','Correspondência territorial'],['positive','Com larvas'],['aegypti','A. aegypti'],['closed','Fechados'],['refused','Recusas'],['worked','Trabalhados'],['count','Registros'],['informed','Com resultado de larvas'],['missing','Sem resultado de larvas'],['coverage','Preenchimento %'],['previous_positive','Com larvas anterior'],['positive_days','Datas com achado'],['last_positive','Último achado'],['last_visit','Último registro']]));
    $('ento-filters').addEventListener('submit',event=>{event.preventDefault();updateVisits();});
    $('ento-filters').addEventListener('change',event=>{if(event.target.id==='sector-filter')updateBlocks();updateVisits();});
    $('ento-filters').addEventListener('reset',event=>{event.preventDefault();$('date-start').value=dataset.source.start;$('date-end').value=dataset.source.end;['sector-filter','block-filter','result-filter','species-filter','mapping-filter'].forEach(id=>$(id).value='');updateBlocks();updateVisits();fitCity(state.visitMap);});
    $('map-metric').addEventListener('change',updateVisitMap);$('trend-metric').addEventListener('change',updateTrend);
    $('map-reset').addEventListener('click',()=>fitCity(state.visitMap));
    $('page-prev').addEventListener('click',()=>{state.page--;updateTable();});$('page-next').addEventListener('click',()=>{state.page++;updateTable();});
    $('export-visits').addEventListener('click',()=>download(`entomologia-${$('date-start').value}-${$('date-end').value}.csv`,state.rows,[['date','Data'],['area','Área operacional'],['sector','Setor censitário'],['block','Quarteirão'],...M.metrics.map(k=>[k,labels[k]||({vacant:'Imóveis desocupados',temporary:'Imóveis temporários',partial:'Imóveis parciais',mechanical:'Controle mecânico',alternative:'Controle alternativo',focal:'Tratamento focal',containers:'Recipientes existentes',water:'Recipientes com água',positive_containers:'Recipientes com larvas',aegypti_containers:'Recipientes A. aegypti',albopictus_containers:'Recipientes A. albopictus',albopictus_larvae:'Larvas A. albopictus'})[k]])]));
    ['census-sector','census-situation','census-metric'].forEach(id=>$(id).addEventListener('change',updateCensus));
    $('census-reset').addEventListener('click',()=>{$('census-sector').value='';$('census-situation').value='';updateCensus();fitCity(state.censusMap);});
    $('export-census').addEventListener('click',()=>download('censo-orlandia-2022.csv',state.census.map(f=>({...f.properties,year:2022,density:M.density(f.properties)})),[['year','Ano'],['sector','Setor censitário'],['situation','Situação'],['population','População'],['households','Domicílios totais'],['occupied_households','Particulares ocupados'],['area_km2','Área km2'],['density','Hab/km2']]));
    const tabs=[...document.querySelectorAll('[data-view]')];
    tabs.forEach((button,index)=>{button.addEventListener('click',()=>activate(button.dataset.view));button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();activate(tabs[next].dataset.view);}});});
    $('reference-select').addEventListener('change',reference);
    $('print-planning').addEventListener('click',()=>window.print());
    $('action-cancel').addEventListener('click',()=>{if($('action-dialog').close)$('action-dialog').close();else $('action-dialog').removeAttribute('open');});
    $('action-dialog').querySelector('form').addEventListener('submit',()=>{try{localStorage.setItem('ento-responsavel',$('action-owner').value);}catch(error){/* sem armazenamento local */}});
    updatePlanning();
    activate(location.hash==='#acao-criada'?'planning':'team');
    if(location.hash==='#acao-criada')goToActions();
  } catch(error) {
    $('ento-error').hidden=false;$('ento-error').textContent='Não foi possível inicializar o painel. Recarregue a página ou contate o administrador.';
    console.error('Entomologia dashboard:',error);
  }
})();
