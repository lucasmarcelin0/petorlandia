/* Página pública /aedes: somente dados agregados por setor, já aprovados pela equipe. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const fmt = value => value == null ? '—' : Number(value).toLocaleString('pt-BR');
  const day = iso => iso ? iso.slice(8, 10) + '/' + iso.slice(5, 7) : '';
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const status = {
    foco: {label: 'Foco encontrado no período', color: 'var(--accent)', hex: '#d9622b'},
    sem_foco: {label: 'Sem foco nas visitas com resultado', color: 'var(--brand)', hex: '#0b7a75'},
    sem_informacao: {label: 'Visitada, resultado não informado', color: 'var(--sand)', hex: '#e9dfc8'},
    sem_visita: {label: 'Sem visita registrada no período', color: 'var(--none)', hex: '#e4e9e8'}
  };

  function checklist() {
    const boxes = [...document.querySelectorAll('.checklist input')];
    const update = () => {
      const done = boxes.filter(b => b.checked).length;
      $('checklist-count').textContent = done === boxes.length ? 'Tudo conferido. Obrigado por cuidar da sua casa e da vizinhança!'
        : done ? `${done} de ${boxes.length} itens conferidos.` : '';
    };
    boxes.forEach(b => b.addEventListener('change', update));
  }

  function share() {
    const button = $('share');
    if (!button) return;
    button.hidden = false;
    button.addEventListener('click', async () => {
      const data = {title: document.title, url: location.href.split('#')[0]};
      try {
        if (navigator.share) await navigator.share(data);
        else { await navigator.clipboard.writeText(data.url); button.textContent = 'Link copiado'; }
      } catch (error) { /* compartilhamento cancelado */ }
    });
  }

  function pointInRing(point, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if (((yi > point[1]) !== (yj > point[1])) && point[0] < (xj - xi) * (point[1] - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function contains(geometry, point) {
    const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.type === 'MultiPolygon' ? geometry.coordinates : [];
    return polygons.some(rings => pointInRing(point, rings[0]) && !rings.slice(1).some(hole => pointInRing(point, hole)));
  }

  function dashboard(data) {
    const b = data.boletim, t = b.totais, features = data.census.features;
    const kpi = (label, value, note, lead) => `<article class="kpi${lead ? ' lead' : ''}"><div class="label">${escape(label)}</div><div class="value">${value}</div><div class="note">${escape(note)}</div></article>`;
    $('kpis').innerHTML = kpi('Quarteirões percorridos', fmt(t.quarteiroes), `em ${fmt(t.setores)} regiões da cidade`, true)
      + kpi('Imóveis trabalhados', fmt(t.trabalhados), 'soma das visitas no período')
      + kpi('Remoção de criadouros', fmt(t.controle_mecanico), 'imóveis com controle mecânico')
      + kpi('Regiões com foco', `${fmt(t.setores_com_foco)} de ${fmt(t.setores)}`, 'larvas encontradas em ao menos uma visita')
      + kpi('Resultado registrado', t.preenchimento == null ? '—' : fmt(t.preenchimento) + '%', 'das visitas têm resultado de larvas');

    const byCode = b.setores;
    const mapped = new Set(features.map(f => f.properties.sector));
    const outside = Object.keys(byCode).filter(code => !mapped.has(code)).length;
    $('map-note').textContent = `Período de ${day(b.inicio)} a ${day(b.fim)}.` + (outside ? ` ${outside} região(ões) do cadastro de campo sem correspondência no mapa do Censo entram nos totais, mas não aparecem no mapa.` : '');
    $('legend').innerHTML = Object.values(status).map(s => `<li><span class="swatch" style="background:${s.color}"></span>${s.label}</li>`).join('');

    function describe(code) {
      const s = byCode[code];
      const kind = s ? s.situacao : 'sem_visita';
      $('detail').innerHTML = `<p class="eyebrow">Região selecionada</p><span class="status ${kind}">${escape(status[kind].label)}</span>`
        + (s ? `<dl><dt>Última visita</dt><dd>${day(s.ultima_visita)}</dd><dt>Quarteirões percorridos</dt><dd>${fmt(s.quarteiroes)}</dd><dt>Imóveis trabalhados</dt><dd>${fmt(s.trabalhados)}</dd><dt>Remoção de criadouros</dt><dd>${fmt(s.controle_mecanico)}</dd></dl>`
          : '<p>Nenhuma visita registrada nesta região no período. As equipes percorrem a cidade em ciclos; faça a sua parte com a lista de 10 minutos.</p>')
        + `<p class="footnote">Setor censitário ${escape(code.slice(-4))} (IBGE 2022).</p>`;
    }

    if (window.L) {
      const map = L.map('map', {scrollWheelZoom: false});
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; OpenStreetMap | Setores: IBGE 2022'}).addTo(map);
      let selected = null;
      const layer = L.geoJSON(data.census, {
        style: f => { const s = byCode[f.properties.sector]; return {color: '#ffffff', weight: 1, fillOpacity: .78, fillColor: status[s ? s.situacao : 'sem_visita'].hex}; },
        onEachFeature: (feature, polygon) => {
          polygon.on('click', () => select(feature.properties.sector, polygon));
          polygon.bindTooltip(status[(byCode[feature.properties.sector] || {}).situacao || 'sem_visita'].label, {sticky: true});
        }
      }).addTo(map);
      // Enquadra as regiões visitadas; sem elas, a área urbana; por fim, tudo.
      const frame = [features.filter(f => byCode[f.properties.sector]), features.filter(f => f.properties.situation !== 'Rural')]
        .map(list => L.geoJSON({type: 'FeatureCollection', features: list}).getBounds()).find(bounds => bounds.isValid());
      map.fitBounds(frame || layer.getBounds(), {padding: [16, 16]});
      function select(code, polygon) {
        if (selected) layer.resetStyle(selected);
        selected = polygon;
        polygon.setStyle({weight: 3, color: '#12302f'});
        polygon.bringToFront();
        describe(code);
      }
      $('locate').addEventListener('click', () => {
        if (!navigator.geolocation) { $('detail').querySelector('p:last-child').textContent = 'Localização indisponível neste navegador.'; return; }
        $('locate').textContent = 'Localizando…';
        navigator.geolocation.getCurrentPosition(position => {
          $('locate').textContent = 'Usar minha localização';
          const point = [position.coords.longitude, position.coords.latitude];
          let found = null;
          layer.eachLayer(polygon => { if (!found && contains(polygon.feature.geometry, point)) found = polygon; });
          if (found) { map.fitBounds(found.getBounds(), {maxZoom: 16, padding: [30, 30]}); select(found.feature.properties.sector, found); }
          else $('detail').innerHTML = '<p class="eyebrow">Sua localização</p><h3>Fora das regiões do mapa</h3><p>Você parece estar fora dos setores de Orlândia. Toque em uma região para consultar.</p>';
        }, () => {
          $('locate').textContent = 'Usar minha localização';
          $('detail').innerHTML = '<p class="eyebrow">Sua localização</p><h3>Não foi possível localizar</h3><p>Permita o acesso à localização ou toque diretamente no mapa.</p>';
        }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000});
      });
    } else {
      $('map').innerHTML = '<p style="padding:24px">Não foi possível carregar o mapa. Os números acima continuam válidos.</p>';
      $('locate').hidden = true;
    }

    const weeks = b.semanas, max = Math.max(1, ...weeks.map(w => w.quarteiroes || 0));
    const width = 640, height = 230, left = 36, bottom = 190, plot = 150, step = (width - left - 8) / weeks.length, bar = Math.min(44, step * .62);
    let svg = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">`;
    [0, .5, 1].forEach(f => { const y = bottom - f * plot; svg += `<line class="grid" x1="${left}" x2="${width - 4}" y1="${y}" y2="${y}"/><text x="${left - 6}" y="${y + 4}" text-anchor="end">${fmt(Math.round(max * f))}</text>`; });
    weeks.forEach((w, i) => {
      const x = left + step * i + step / 2, h = (w.quarteiroes || 0) / max * plot;
      svg += `<g><title>Semana de ${day(w.inicio)}: ${w.registros ? fmt(w.quarteiroes) + ' quarteirões' : 'sem registro enviado'}${w.parcial ? ' (semana em andamento)' : ''}</title>`
        + `<rect class="bar${w.parcial ? ' partial' : ''}" x="${x - bar / 2}" y="${bottom - h}" width="${bar}" height="${h}" rx="5"/>`
        + `<text x="${x}" y="${bottom - h - 8}" text-anchor="middle">${w.registros ? fmt(w.quarteiroes) : '—'}</text>`
        + `<text x="${x}" y="${bottom + 20}" text-anchor="middle">${day(w.inicio)}${w.parcial ? '*' : ''}</text></g>`;
    });
    $('chart').innerHTML = svg + '</svg>' + (weeks.some(w => w.parcial) ? '<p class="footnote">* Semana ainda em andamento no fim do período.</p>' : '');
  }

  checklist();
  share();
  const node = $('aedes-data');
  if (node) {
    try { dashboard(JSON.parse(node.textContent)); }
    catch (error) { console.error('Painel Aedes:', error); }
  }
})();
