(function () {
  'use strict';
  const $ = id => document.getElementById(id), M = window.SfaFieldMapModel;
  const dataset = JSON.parse($('ento-dataset').textContent);
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const colors = ['#65e3df','#a8cf72','#eec36b','#9db4ff','#e99ba1','#bcabf1','#69b9f0','#efd18b','#b5d9c4'];
  const areaNames = {
    'SETOR 1':'Área 1', 'SETOR 2':'Área 2',
    'SETOR 3 BRAZÃO/STA RITA':'Área 3 · Brazão e Santa Rita',
    'SETOE 3 PARISE E ADJACENTES':'Área 3 · Parise e adjacências',
    'SETOR 4  BANDEIRANTES':'Área 4 · Bandeirantes', 'SETOR 4 GRUTA':'Área 4 · Gruta',
    'SETOR 5':'Área 5 · Centro', 'SETOR 6 TEIXEIRA':'Área 6 · Teixeira', 'SETOR 6 VILINHA':'Área 6 · Vilinha'
  };
  let map, basemap, territory, blockLayer, censusLayer, selectedLayer, labelLayer;
  let loading = null, selected = null, shown = [], districts = [], labelFrame = null, searchTimer;
  const areaName = district => areaNames[district] || district;
  const areaColor = district => colors[Math.max(0, districts.indexOf(district)) % colors.length];
  const filterValues = () => ({district:$('field-district').value, sector:$('field-sector').value, search:''});
  const latLng = f => [f.properties.label[1], f.properties.label[0]];
  function message(text) { $('field-error').textContent = text; $('field-error').hidden = !text; }
  function fit(items) {
    if (!items.length || !map) return;
    map.fitBounds(L.geoJSON(items).getBounds(), {padding:[35,35], maxZoom:items.length === 1 ? 18 : 16});
  }
  function updateSectors() {
    const district = $('field-district').value, current = $('field-sector').value;
    const sectors = [...new Set(territory.features.filter(f => !district || f.properties.district === district).map(f => f.properties.sector))].sort((a,b) => Number(a)-Number(b));
    $('field-sector').replaceChildren(new Option('Todos os setores', ''), ...sectors.map(s => new Option(`SC ${s}`, s)));
    $('field-sector').value = sectors.includes(current) ? current : '';
  }
  function select(feature, focus = false) {
    selected = feature;
    if (selectedLayer) selectedLayer.remove();
    const p = feature.properties;
    selectedLayer = L.geoJSON(feature, {pane:'field-selection', style:{color:'#fff', weight:3, fillColor:'#fff', fillOpacity:.14}}).addTo(map);
    if (focus) fit([feature]);
    const matchingSectors = [...new Set(dataset.records.map(r => r.sector))].filter(s => Number(s.slice(-4)) === Number(p.sector));
    const rows = matchingSectors.length === 1 ? dataset.records.filter(r => r.sector === matchingSectors[0] && r.block === p.block) : [];
    const issues = [p.duplicate_key ? 'Código de quadra repetido na fonte.' : '', !p.geometry_valid ? 'Geometria irregular na fonte.' : ''].filter(Boolean);
    $('field-selection').innerHTML = `<div class="ento-eyebrow">QUADRA SELECIONADA</div><div class="field-selected-number">${escape(p.block)}<span>SC ${escape(p.sector)}</span></div><p>${escape(areaName(p.district))}</p>${issues.length ? `<p class="field-review-note">${escape(issues.join(' '))} Conferir com a equipe.</p>` : ''}<p class="field-match-note">${rows.length ? `${rows.length} registros com os mesmos códigos no arquivo de visitas. Vínculo territorial a conferir.` : 'Sem registros com os mesmos códigos no arquivo de visitas. Isso não comprova ausência de trabalho.'}</p>${rows.length ? '<button type="button" id="field-history" class="field-tool-button">Consultar registros ↗</button>' : ''}<button type="button" id="field-clear-selection" class="field-clear-selection">Limpar seleção</button>`;
    $('field-clear-selection').onclick = clearSelection;
    if ($('field-history')) $('field-history').onclick = () => {
      if ($('field-workspace').classList.contains('is-expanded')) $('field-fullscreen').click();
      $('date-start').value = dataset.source.start; $('date-end').value = dataset.source.end;
      $('sector-filter').value = matchingSectors[0];
      $('sector-filter').dispatchEvent(new Event('change', {bubbles:true}));
      $('block-filter').value = p.block;
      ['result-filter','species-filter','mapping-filter'].forEach(id => $(id).value = '');
      $('tab-visits').click(); $('tab-visits').focus();
    };
    scheduleLabels();
  }
  function clearSelection() {
    selected = null;
    if (selectedLayer) selectedLayer.remove();
    selectedLayer = null;
    $('field-selection').innerHTML = '<div class="ento-eyebrow">CONSULTA DO TERRITÓRIO</div><h3>Escolha uma quadra</h3><p>Clique em um contorno para consultar seu número, setor e área de campo.</p>';
    scheduleLabels();
  }
  function draw(enframe = false) {
    shown = M.filter(territory.features, filterValues());
    if (blockLayer) blockLayer.remove();
    blockLayer = L.geoJSON(shown, {
      pane:'field-blocks',
      style:f => ({color:areaColor(f.properties.district), weight:map.getZoom() >= 16 ? 1.8 : 1.2, opacity:.95, fillColor:areaColor(f.properties.district), fillOpacity:.07}),
      onEachFeature:(f, layer) => {
        const p = f.properties;
        layer.bindTooltip(`<strong>Quadra ${escape(p.block)}</strong> · SC ${escape(p.sector)}<br>${escape(areaName(p.district))}`, {sticky:true, className:'field-tooltip'});
        layer.on('click', () => select(f));
        layer.on('mouseover', () => layer.setStyle({weight:3, fillOpacity:.23}));
        layer.on('mouseout', () => blockLayer.resetStyle(layer));
      }
    });
    if ($('field-blocks').checked) blockLayer.addTo(map);
    if (selected && !shown.some(f => f.id === selected.id)) clearSelection();
    const sectorCount = new Set(shown.map(f => f.properties.sector)).size;
    $('field-count').textContent = `${shown.length.toLocaleString('pt-BR')} de ${territory.features.length.toLocaleString('pt-BR')} quadras · ${sectorCount} ${sectorCount === 1 ? 'setor' : 'setores'} de campo`;
    if (!shown.length) message('Nenhuma quadra corresponde à busca. Use o número exato, como “436”, ou um setor, como “SC 023”.');
    else message('');
    if (enframe && shown.length) fit(shown);

    scheduleLabels();
  }
  function groupLabels(key, prefix) {
    const groups = new Map();
    shown.forEach(f => {const value = f.properties[key]; if (!groups.has(value)) groups.set(value, []); groups.get(value).push(f);});
    return [...groups].map(([value, items]) => {
      const center = items.reduce((a,f) => [a[0]+f.properties.label[0]/items.length, a[1]+f.properties.label[1]/items.length], [0,0]);
      // Use an actual interior point of the nearest quadra, never the mean in a road.
      const anchor = items.reduce((best,f) => {
        const distance = g => (g.properties.label[0]-center[0])**2+(g.properties.label[1]-center[1])**2;
        return distance(f) < distance(best) ? f : best;
      }, items[0]);
      return {feature:anchor, text:prefix+value, group:key, title:key === 'district' ? areaName(value) : `Setor de campo SC ${value}`, count:items.length};
    });
  }
  function scheduleLabels() {
    if (labelFrame != null) cancelAnimationFrame(labelFrame);
    labelFrame = requestAnimationFrame(drawLabels);
  }
  function drawLabels() {
    labelFrame = null;
    if (!map || !territory) return;
    labelLayer.clearLayers();
    const zoom = map.getZoom(), size = map.getSize();
    const blockMode = zoom >= 16, districtMode = zoom < 14;
    $('field-zoom-note').textContent = blockMode ? 'Números das quadras · clique para consultar' : districtMode ? 'Áreas de campo · aproxime para ver os setores' : 'Setores de campo · aproxime para ver cada quadra';
    if (!$('field-numbers').checked) return;
    let labels = blockMode ? shown.map(f => ({feature:f, text:f.properties.block, group:'block'})) : groupLabels(districtMode ? 'district' : 'sector', districtMode ? '' : 'SC ');
    if (selected && !blockMode) labels.unshift({feature:selected, text:selected.properties.block, group:'block', priority:1000});
    const candidates = labels.map(item => {
      const point = map.latLngToContainerPoint(latLng(item.feature));
      const text = item.group === 'district' ? areaName(item.text).split(' · ')[0] : item.text;
      return {...item, text, x:point.x, y:point.y, width:item.group === 'district' ? 90 : Math.max(30,text.length*8+14), height:item.group === 'district' ? 40 : 25,
        priority:item.priority || (selected?.id === item.feature.id ? 1000 : 0)};
    });
    const mapRect = $('field-map').getBoundingClientRect();
    const reserved = [...$('field-workspace').querySelectorAll('.field-map-caption > span, #field-map .leaflet-control, #field-map .atlas-cluster, #field-map .atlas-house-label, #field-map .atlas-condo-overview, #field-map .atlas-condo-street')].map(element => {
      const r = element.getBoundingClientRect();
      return {left:r.left-mapRect.left-3, right:r.right-mapRect.left+3, top:r.top-mapRect.top-3, bottom:r.bottom-mapRect.top+3};
    });
    M.placeLabels(candidates, size.x, size.y, 5, reserved).forEach(c => {
      const p = c.feature.properties, district = c.group === 'district';
      const marker = L.marker(latLng(c.feature), {keyboard:false, interactive:c.group === 'block', pane:'field-labels',
        icon:L.divIcon({className:`field-label field-label-${c.group}${selected?.id === c.feature.id ? ' is-selected' : ''}`,
          html:`<span style="--area-color:${areaColor(p.district)}">${escape(c.text)}${district ? `<small>${c.count} quadras</small>` : ''}</span>`,
          iconSize:[c.width,c.height], iconAnchor:[c.width/2,c.height/2]})});
      if (c.group === 'block') marker.on('click', () => select(c.feature));
      marker.addTo(labelLayer);
    });
    blockLayer?.setStyle({weight:zoom >= 16 ? 1.8 : 1.2});
  }
  function originals() {
    $('field-original-grid').innerHTML = (dataset.reference_maps || []).map((m,i) => `<button type="button" data-original-index="${i}"><img src="${escape(m.url)}" alt="" loading="lazy"><span>${escape(m.title)}</span></button>`).join('');
  }
  function setup() {
    if (!window.L) throw Error('Biblioteca de mapas indisponível.');
    map = L.map('field-map', {scrollWheelZoom:true, minZoom:11, maxZoom:21}).setView([-20.72,-47.88],14);
    for (const [name,z] of [['field-events',610],['field-event-labels',630],['field-census',410],['field-blocks',420],['field-hotspots',425],['field-selection',430],['field-labels',620]]) {
      map.createPane(name).style.zIndex = z;
      if (name === 'field-labels') map.getPane(name).style.pointerEvents = 'none';
    }
    basemap = window.SfaMapLayers.attach(map, {status:text => $('field-base-status').textContent = text});
    map.on('sfabasemapchange', e => {$('field-basemap').value = e.mode;});
    $('field-basemap').value = basemap.getMode();
    labelLayer = L.layerGroup().addTo(map);
    censusLayer = L.geoJSON(dataset.census, {pane:'field-census', interactive:false, style:{color:'#8fc9ff', weight:2, dashArray:'6 5', fillOpacity:0}});
    window.SfaAtlasLayers.attach(map,dataset,territory);
    window.SfaAtlasEditor.attach(map,dataset);
    districts = [...new Set(territory.features.map(f => f.properties.district))];
    $('field-district').replaceChildren(new Option('Todas as áreas', ''), ...districts.map(d => new Option(areaName(d),d)));
    updateSectors();
    $('field-inventory').innerHTML = `<span><strong>${territory.source.blocks}</strong> quadras</span><span><strong>${territory.source.sectors}</strong> setores</span><span><strong>${dataset.reference_maps.length}</strong> mapas originais</span>`;
    $('field-area-legend').innerHTML = districts.map(d => `<button type="button" data-district="${escape(d)}"><i style="background:${areaColor(d)}"></i><span>${escape(areaName(d))}</span></button>`).join('');
    $('field-provenance').textContent = `Fonte: ${territory.source.file}, camada Quadras. ${territory.source.blocks} geometrias em ${territory.source.districts} áreas e ${territory.source.sectors} códigos SC. ${territory.source.invalid_geometries} geometria irregular e ${territory.source.duplicate_keys} chave setor/quadra repetida, sinalizadas na consulta. Coordenadas originais preservadas; posições dos rótulos calculadas no interior dos polígonos. As folhas em papel não foram georreferenciadas. Hash SHA-256: ${territory.source.sha256}.`;
    map.attributionControl.addAttribution('Quadras: referência municipal · IBGE 2022 (camada opcional)');
    map.on('zoomend moveend resize atlaslayerschange', scheduleLabels);
    const atlasSearch=window.SfaAtlasSearch.attach(map,dataset,territory,{select,fit,areaName});
    $('field-district').onchange = () => {updateSectors(); draw(true);};
    $('field-sector').onchange = () => draw(true);
    $('field-area-legend').onclick = e => {const button = e.target.closest('[data-district]'); if (!button) return; $('field-district').value = button.dataset.district; atlasSearch.clear(); updateSectors(); $('field-sector').value = ''; draw(true);};
    $('field-basemap').onchange = () => basemap.setMode($('field-basemap').value);
    $('field-blocks').onchange = () => {$('field-blocks').checked ? blockLayer.addTo(map) : blockLayer.remove();};
    $('field-numbers').onchange = scheduleLabels;
    $('field-census').onchange = () => {$('field-census').checked ? censusLayer.addTo(map) : censusLayer.remove();};
    $('field-reset').onclick = () => {clearTimeout(searchTimer); atlasSearch.clear(); $('field-district').value = ''; $('field-sector').value = ''; updateSectors(); clearSelection(); draw(true);};
    document.querySelectorAll('[data-atlas-panel]').forEach(button=>button.onclick=()=>{const target=$(button.dataset.atlasPanel);target?.scrollIntoView({block:'start',behavior:'auto'});});
    draw(true);
  }
  $('field-fullscreen').onclick = () => {
    const workspace = $('field-workspace'), expanded = workspace.classList.toggle('is-expanded');
    $('field-fullscreen').textContent = expanded ? 'Reduzir mapa' : 'Expandir mapa';
    $('field-fullscreen').setAttribute('aria-pressed', expanded);
    document.body.classList.toggle('field-map-expanded', expanded);
    requestAnimationFrame(() => map?.invalidateSize());
  };
  document.addEventListener('keydown', e => {if (e.key === 'Escape' && $('field-workspace').classList.contains('is-expanded')) {$('field-fullscreen').click(); $('field-fullscreen').focus();}});
  originals();
  window.SfaFieldMap = {open() {
    if (map) {requestAnimationFrame(() => map.invalidateSize()); return Promise.resolve();}
    if (loading) return loading;
    loading = fetch(dataset.territory_url, {credentials:'same-origin', cache:'no-store'}).then(response => {
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw Error('Não foi possível acessar a referência territorial.');
      return response.json();
    }).then(data => {territory = data; setup();}).catch(error => {
      loading = null;
      if (map) {map.remove(); map = null;}
      $('field-count').textContent = 'Território indisponível'; $('field-inventory').textContent = 'Consulte os mapas originais abaixo';
      message(`${error.message} Os mapas originais continuam disponíveis. Reabra a aba para tentar novamente.`);
    });
    return loading;
  }};
})();
