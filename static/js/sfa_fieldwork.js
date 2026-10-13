(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const M = window.SfaFieldworkModel;

  const PASTEL_COLORS = [
    { name: 'Verde Menta', hex: '#bbf7d0', border: '#16a34a' },
    { name: 'Azul Bebê', hex: '#bae6fd', border: '#0284c7' },
    { name: 'Amarelo Claro', hex: '#fef08a', border: '#ca8a04' },
    { name: 'Pêssego', hex: '#fed7aa', border: '#ea580c' },
    { name: 'Lavanda', hex: '#e9d5ff', border: '#9333ea' },
    { name: 'Rosa Suave', hex: '#fbcfe8', border: '#db2777' },
    { name: 'Sem Cor', hex: '#ffffff', border: '#cbd5e1' },
  ];

  let map = null;
  let territoryData = null;
  let addressFeatures = [];
  let blockLayer = null;
  let houseLayer = null;
  let activeBlock = null;
  let activeHouse = null;
  let currentMode = 'office'; // 'office' ou 'field'
  let selectedColor = PASTEL_COLORS[0].hex;
  let dataset = null;

  function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // --------------------------------------------------------------------------
  // Disparo de Confetes Festivos (CSS)
  // --------------------------------------------------------------------------
  function triggerCelebration() {
    const wrap = document.createElement('div');
    wrap.className = 'fieldwork-confetti-wrap';
    const colors = ['#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#8b5cf6'];
    for (let i = 0; i < 60; i++) {
      const p = document.createElement('div');
      p.className = 'fieldwork-confetti-particle';
      p.style.left = Math.random() * 100 + 'vw';
      p.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
      p.style.animationDelay = Math.random() * 0.8 + 's';
      p.style.width = (Math.random() * 8 + 6) + 'px';
      p.style.height = (Math.random() * 8 + 6) + 'px';
      wrap.appendChild(p);
    }
    document.body.appendChild(wrap);
    setTimeout(() => wrap.remove(), 3200);
  }

  // --------------------------------------------------------------------------
  // Inicialização e Carga dos Dados
  // --------------------------------------------------------------------------
  async function loadData() {
    if (!territoryData) {
      const res = await fetch(dataset.territory_url, { credentials: 'same-origin' });
      territoryData = await res.json();
    }

    if (!addressFeatures.length && dataset.atlas_urls?.addresses) {
      try {
        const res = await fetch(dataset.atlas_urls.addresses, { credentials: 'same-origin' });
        const data = await res.json();
        const layers = data.layers || [];
        layers.forEach(l => {
          (l.features || []).forEach(f => {
            if (f.geometry?.type === 'Point') {
              addressFeatures.push(f);
            }
          });
        });
      } catch (e) {
        console.warn('Endereços CNEFE não disponíveis para o trabalho de campo:', e);
      }
    }

    // Carrega status salvo do servidor e mescla com local
    if (dataset.fieldwork_urls?.state) {
      try {
        const res = await fetch(dataset.fieldwork_urls.state, { credentials: 'same-origin' });
        const data = await res.json();
        if (data.quarteiroes) {
          M.saveBlocksBatch(data.quarteiroes);
        }
      } catch (e) {
        console.warn('Usando dados locais de quarteirões:', e);
      }
    }
  }

  function setupMap() {
    if (map) return;
    if (!window.L) return;

    map = L.map('fieldwork-map', {
      scrollWheelZoom: true,
      minZoom: 12,
      maxZoom: 20,
    }).setView([-20.720, -47.881], 14);

    // Fundo do mapa: camada cartográfica limpa / em branco
    const cartoLight = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      maxZoom: 20,
      opacity: 0.85,
    }).addTo(map);

    blockLayer = L.layerGroup().addTo(map);
    houseLayer = L.layerGroup().addTo(map);

    map.on('zoomend moveend', onMapMove);
  }

  // --------------------------------------------------------------------------
  // Renderização das Quadras
  // --------------------------------------------------------------------------
  function renderBlocks() {
    if (!blockLayer || !territoryData) return;
    blockLayer.clearLayers();

    const blocksSaved = M.getBlocks();
    const sectorFilter = $('fieldwork-sector-select')?.value || '';

    const features = territoryData.features.filter(f => !sectorFilter || f.properties.sector === sectorFilter);

    features.forEach(feature => {
      const p = feature.properties;
      const key = `${p.sector}-${p.block}`;
      const saved = blocksSaved[key] || {};
      const fillColor = saved.cor || '#ffffff';
      const isDone = saved.status === 'TRABALHADO';

      const poly = L.geoJSON(feature, {
        style: {
          color: isDone ? '#10b981' : (saved.cor ? '#0284c7' : '#94a3b8'),
          weight: isDone ? 2.5 : 1.5,
          fillColor: fillColor,
          fillOpacity: saved.cor && saved.cor !== '#ffffff' ? 0.45 : 0.08,
        },
      });

      poly.on('click', () => onBlockClick(feature, key));
      poly.on('mouseover', () => poly.setStyle({ weight: 3, fillOpacity: 0.55 }));
      poly.on('mouseout', () => poly.setStyle({
        weight: isDone ? 2.5 : 1.5,
        fillOpacity: saved.cor && saved.cor !== '#ffffff' ? 0.45 : 0.08
      }));

      poly.addTo(blockLayer);

      // Rótulo com número da quadra
      if (p.label && map.getZoom() <= 17) {
        const summary = M.summarizeBlock(p.sector, p.block, 0);
        const badgeDone = isDone ? 'is-done' : '';
        const icon = L.divIcon({
          className: 'fieldwork-block-label',
          html: `<div class="fieldwork-block-badge ${badgeDone}" title="Quadra ${p.block} · SC ${p.sector}">${escapeHtml(p.block)}<small>${isDone ? '✔️ 100%' : (summary.totalVisits ? summary.totalVisits + ' vis.' : '')}</small></div>`,
          iconSize: [44, 44],
          iconAnchor: [22, 22],
        });
        L.marker([p.label[1], p.label[0]], { icon, interactive: false }).addTo(blockLayer);
      }
    });
  }

  // --------------------------------------------------------------------------
  // Renderização das Casas / Imóveis (Zoom >= 16)
  // --------------------------------------------------------------------------
  function renderHouses() {
    if (!houseLayer) return;
    houseLayer.clearLayers();

    const zoom = map.getZoom();
    if (zoom < 16) return; // Só mostra casas em zoom aproximado

    const bounds = map.getBounds();
    const visibleHouses = addressFeatures.filter(f => bounds.contains([f.geometry.coordinates[1], f.geometry.coordinates[0]]));
    const allVisits = M.getVisits();

    visibleHouses.forEach(f => {
      const p = f.properties || {};
      const num = p.house_number || p.numero || (p.address ? p.address.split(',')[1]?.trim() : '');
      if (!num) return;

      const lat = f.geometry.coordinates[1];
      const lng = f.geometry.coordinates[0];

      // Busca visita existente para esta casa
      const visit = allVisits.find(v => (v.cnefe_id && v.cnefe_id === p.cnefe_id) ||
        (v.logradouro === p.street && String(v.numero) === String(num)));

      let houseClass = '';
      if (visit) {
        if (visit.larvas) houseClass = 'house-larvas';
        else if (visit.situacao === 'ABERTA') houseClass = 'house-aberta';
        else if (visit.situacao === 'FECHADA') houseClass = 'house-fechada';
        else if (visit.situacao === 'RECUSA') houseClass = 'house-recusa';
        else if (visit.situacao === 'DESABITADO') houseClass = 'house-desabitado';
      }

      const icon = L.divIcon({
        className: `fieldwork-house-marker ${houseClass}`,
        html: `<span>${escapeHtml(num)}</span>`,
        iconSize: [28, 20],
        iconAnchor: [14, 10],
      });

      const marker = L.marker([lat, lng], { icon });
      marker.on('click', () => openHouseModal(f, visit));
      marker.addTo(houseLayer);
    });
  }

  function onMapMove() {
    $('fieldwork-zoom-note').textContent = map.getZoom() >= 16
      ? '🔎 Zoom em casas · Toque num número para registrar visita'
      : '🗺️ Visão de quarteirões · Aproxime para ver cada residência';
    renderHouses();
  }

  // --------------------------------------------------------------------------
  // Interações com Quarteirões
  // --------------------------------------------------------------------------
  function onBlockClick(feature, key) {
    const p = feature.properties;
    activeBlock = feature;

    if (currentMode === 'office') {
      // Modo Escritório: Pintura com a cor selecionada
      const agentName = $('fieldwork-agent-name')?.value || '';
      const updated = M.saveBlock(p.sector, p.block, {
        cor: selectedColor,
        responsavel: agentName,
      });

      renderBlocks();
      updateBlockSummary(p.sector, p.block);

      // Sincroniza salvamento no servidor
      if (dataset.fieldwork_urls?.save_blocks) {
        fetch(dataset.fieldwork_urls.save_blocks, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': $('csrf-token')?.content || '' },
          body: JSON.stringify({ items: [updated] }),
        }).catch(err => console.warn('Erro ao salvar no servidor:', err));
      }
    } else {
      // Modo Campo: Zoom na quadra para trabalhar casa a casa
      map.fitBounds(L.geoJSON(feature).getBounds(), { padding: [30, 30], maxZoom: 18 });
      updateBlockSummary(p.sector, p.block);
    }
  }

  function updateBlockSummary(setor, quarteirao) {
    const summary = M.summarizeBlock(setor, quarteirao, 25);
    const saved = M.getBlocks()[`${setor}-${quarteirao}`] || {};

    $('fieldwork-block-num').textContent = `Quadra ${quarteirao}`;
    $('fieldwork-block-sector').textContent = `Setor de Campo SC ${setor}`;
    $('fieldwork-prog-pct').textContent = `${summary.pct}%`;
    $('fieldwork-prog-fill').style.width = `${summary.pct}%`;
    $('fieldwork-prog-count').textContent = `${summary.totalVisits} de ~${summary.totalKnown} imóveis`;

    $('kpi-abertas').textContent = summary.abertas;
    $('kpi-fechadas').textContent = summary.fechadas;
    $('kpi-recusas').textContent = summary.recusas;
    $('kpi-larvas').textContent = summary.larvas;

    // Atualiza metadados da prancha de impressão
    $('print-meta-quadra').textContent = `Quadra: ${quarteirao} (SC ${setor})`;
    $('print-meta-agente').textContent = `Agente/Equipe: ${saved.responsavel || 'Não atribuído'}`;
  }

  // --------------------------------------------------------------------------
  // Modal / BottomSheet da Casa (Visita Casa a Casa)
  // --------------------------------------------------------------------------
  function openHouseModal(houseFeature, existingVisit) {
    activeHouse = houseFeature;
    const p = houseFeature.properties || {};
    const street = p.street || p.logradouro || 'Rua não informada';
    const number = p.house_number || p.numero || 'SN';

    $('sheet-address-title').textContent = `${street}, nº ${number}`;
    $('sheet-address-sub').textContent = p.neighborhood ? `Bairro ${p.neighborhood}` : 'Orlândia / SP';

    // Reseta ou preenche campos
    const situacao = existingVisit?.situacao || 'ABERTA';
    document.querySelectorAll('.fieldwork-opt-btn').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.situation === situacao);
    });

    const criadouros = existingVisit?.criadouros || [];
    document.querySelectorAll('.fieldwork-chip').forEach(chip => {
      const input = chip.querySelector('input');
      const checked = criadouros.includes(input.value);
      input.checked = checked;
      chip.classList.toggle('is-checked', checked);
    });

    $('sheet-larvas-toggle').checked = Boolean(existingVisit?.larvas);
    $('sheet-obs').value = existingVisit?.observacao || '';

    $('fieldwork-house-sheet').hidden = false;
  }

  function closeHouseModal() {
    $('fieldwork-house-sheet').hidden = true;
    activeHouse = null;
  }

  function saveCurrentVisit() {
    if (!activeHouse) return;

    const p = activeHouse.properties || {};
    const number = p.house_number || p.numero || '';
    const street = p.street || p.logradouro || '';
    const activeBtn = document.querySelector('.fieldwork-opt-btn.is-active');
    const situacao = activeBtn?.dataset.situation || 'ABERTA';

    const criadouros = [];
    document.querySelectorAll('.fieldwork-chip input:checked').forEach(input => {
      criadouros.push(input.value);
    });

    const larvas = $('sheet-larvas-toggle').checked;
    const obs = $('sheet-obs').value.trim();

    // Determina o setor e quarteirão a partir da quadra ativa ou endereço
    const setor = activeBlock?.properties?.sector || p.sector || '028';
    const quarteirao = activeBlock?.properties?.block || p.block || '1';

    const visit = M.saveVisit({
      setor,
      quarteirao,
      logradouro: street,
      numero: number,
      cnefe_id: p.cnefe_id || '',
      latitude: activeHouse.geometry.coordinates[1],
      longitude: activeHouse.geometry.coordinates[0],
      situacao,
      criadouros,
      larvas,
      agente: $('fieldwork-agent-name')?.value || 'Agente de Campo',
      observacao: obs,
    });

    closeHouseModal();
    renderHouses();
    updateBlockSummary(setor, quarteirao);
    updateGamificationUI();
    updateSyncBadge();

    // Se a quadra atingiu 100%, celebração com confetes!
    const summary = M.summarizeBlock(setor, quarteirao, 25);
    if (summary.pct === 100) {
      M.saveBlock(setor, quarteirao, { status: 'TRABALHADO' });
      renderBlocks();
      triggerCelebration();
      alert(`🎉 Parabéns! A Quadra ${quarteirao} foi 100% concluída com sucesso!`);
    }
  }

  // --------------------------------------------------------------------------
  // Gamificação e Placar do Dia
  // --------------------------------------------------------------------------
  function updateGamificationUI() {
    const visits = M.getVisits();
    const blocks = M.getBlocks();
    const g = M.computeGamification(visits, blocks);

    $('game-points').textContent = g.pontos;
    $('game-level').textContent = `Nível ${g.nivel} · ${g.tituloNivel}`;
    $('game-familias').textContent = g.familiasProtegidas;
    $('game-visitas-hoje').textContent = g.todayCount;
    $('game-criadouros').textContent = g.totalCriadouros;
    $('game-larvas').textContent = g.totalLarvas;

    // Badges
    const badgeContainer = $('fieldwork-badges-list');
    if (badgeContainer) {
      badgeContainer.innerHTML = g.badges.map(b => `
        <div class="fieldwork-badge-item">
          <span class="fieldwork-badge-icon">${b.icon}</span>
          <div class="fieldwork-badge-info">
            <strong>${escapeHtml(b.title)}</strong>
            <small>${escapeHtml(b.desc)}</small>
          </div>
        </div>
      `).join('') || '<p class="text-muted small">Realize visitas para desbloquear medalhas!</p>';
    }
  }

  // --------------------------------------------------------------------------
  // Sincronização & Conexão
  // --------------------------------------------------------------------------
  function updateSyncBadge() {
    const online = navigator.onLine;
    const queue = M.getPendingQueue();
    const badge = $('fieldwork-sync-status');
    const syncBtn = $('fieldwork-sync-btn');

    if (online) {
      badge.className = 'fieldwork-status-badge fieldwork-status-online';
      badge.textContent = queue.length ? `🟢 Online (${queue.length} pendentes)` : '🟢 Sincronizado';
    } else {
      badge.className = 'fieldwork-status-badge fieldwork-status-offline';
      badge.textContent = `📶 Offline (${queue.length} salvas)`;
    }

    if (syncBtn) {
      syncBtn.disabled = !online || queue.length === 0;
      syncBtn.textContent = queue.length ? `Sincronizar (${queue.length}) ⬆️` : 'Tudo Sincronizado ✔️';
    }
  }

  async function syncVisits() {
    const queue = M.getPendingQueue();
    if (!queue.length || !dataset.fieldwork_urls?.sync_visits) return;

    try {
      const res = await fetch(dataset.fieldwork_urls.sync_visits, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': $('csrf-token')?.content || '' },
        body: JSON.stringify({ visitas: queue }),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        M.markSynced(queue.map(q => q.uuid_local));
        updateSyncBadge();
        alert(`✨ ${queue.length} visitas sincronizadas com sucesso com o servidor municipal!`);
      }
    } catch (e) {
      alert('Não foi possível conectar ao servidor. As visitas permanecem salvas com segurança no seu celular.');
    }
  }

  // --------------------------------------------------------------------------
  // Interface e Eventos
  // --------------------------------------------------------------------------
  function bindUI() {
    // Alternador de modo (Escritório vs Campo)
    $('btn-mode-office')?.addEventListener('click', () => {
      currentMode = 'office';
      $('btn-mode-office').classList.add('is-active');
      $('btn-mode-field').classList.remove('is-active');
      $('fieldwork-office-tools').hidden = false;
    });

    $('btn-mode-field')?.addEventListener('click', () => {
      currentMode = 'field';
      $('btn-mode-field').classList.add('is-active');
      $('btn-mode-office').classList.remove('is-active');
      $('fieldwork-office-tools').hidden = true;
    });

    // Paleta de cores suaves
    const swatches = $('fieldwork-swatches');
    if (swatches) {
      swatches.innerHTML = PASTEL_COLORS.map(c => `
        <button type="button" class="fieldwork-swatch ${c.hex === selectedColor ? 'is-selected' : ''}"
                style="background:${c.hex}; border-color:${c.border}" data-color="${c.hex}" title="${c.name}"></button>
      `).join('');

      swatches.addEventListener('click', e => {
        const btn = e.target.closest('[data-color]');
        if (!btn) return;
        selectedColor = btn.dataset.color;
        swatches.querySelectorAll('.fieldwork-swatch').forEach(s => s.classList.remove('is-selected'));
        btn.classList.add('is-selected');
      });
    }

    // Botão de marcar quadra como trabalhada
    $('btn-mark-worked')?.addEventListener('click', () => {
      if (!activeBlock) {
        alert('Clique em uma quadra no mapa primeiro para marcá-la.');
        return;
      }
      const p = activeBlock.properties;
      M.saveBlock(p.sector, p.block, { status: 'TRABALHADO' });
      renderBlocks();
      updateBlockSummary(p.sector, p.block);
      triggerCelebration();
    });

    // Botão de impressão A4
    $('btn-print-board')?.addEventListener('click', () => {
      $('print-meta-data').textContent = `Data: ${new Date().toLocaleDateString('pt-BR')}`;
      window.print();
    });

    // Botão de exportação CSV
    $('btn-export-csv')?.addEventListener('click', () => {
      const csv = M.toCSV(M.getVisits());
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `visitas_orlandia_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    });

    // Botões de situação do imóvel no modal
    document.querySelectorAll('.fieldwork-opt-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.fieldwork-opt-btn').forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');
      });
    });

    // Chips de criadouros
    document.querySelectorAll('.fieldwork-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const input = chip.querySelector('input');
        input.checked = !input.checked;
        chip.classList.toggle('is-checked', input.checked);
      });
    });

    $('sheet-close-btn')?.addEventListener('click', closeHouseModal);
    $('sheet-save-btn')?.addEventListener('click', saveCurrentVisit);
    $('fieldwork-sync-btn')?.addEventListener('click', syncVisits);

    // Eventos de conectividade do navegador
    window.addEventListener('online', updateSyncBadge);
    window.addEventListener('offline', updateSyncBadge);

    // Filtro por setor
    $('fieldwork-sector-select')?.addEventListener('change', () => {
      renderBlocks();
      renderHouses();
    });
  }

  // --------------------------------------------------------------------------
  // Inicialização Pública
  // --------------------------------------------------------------------------
  window.SfaFieldwork = {
    async open(initialDataset) {
      dataset = initialDataset || JSON.parse($('ento-dataset')?.textContent || '{}');
      setupMap();
      bindUI();
      await loadData();

      // Preenche opções de setores censitários
      const sectors = [...new Set((territoryData?.features || []).map(f => f.properties.sector))].sort((a, b) => Number(a) - Number(b));
      const sel = $('fieldwork-sector-select');
      if (sel) {
        sel.replaceChildren(new Option('Todos os setores de campo', ''), ...sectors.map(s => new Option(`SC ${s}`, s)));
      }

      renderBlocks();
      renderHouses();
      updateGamificationUI();
      updateSyncBadge();

      requestAnimationFrame(() => map?.invalidateSize());
    },
  };
})();
