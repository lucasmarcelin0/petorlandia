/* Casa a Casa + Prefeitura integrada, sem sair do mapa:
   - o botão 🏛️ abre a tela de comunicar numa janela por cima do mapa (a mesma página, com foto, local e envio
     sem internet); "Abrir em outra aba" continua disponível para quem preferir;
   - abaixo de "Cores", a camada mostra no mapa as comunicações da Prefeitura integrada.
   Só usa o que o casa_a_casa.js expõe em window.CasaACasa: se algo aqui falhar, o Casa a Casa segue igual. */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  let cfg = {};
  try { cfg = JSON.parse($('cac-config').textContent).urls || {}; } catch (e) { return; }
  const PREFS = 'cac:prefeitura:v1';
  const ATUALIZAR_MS = 120000;
  const CORES = { aberta: '#e8590c', concluida: '#2f9e44' };
  const ROTULOS = { aberta: 'Aguardando atendimento', concluida: 'Atendimento comprovado' };

  const lerPrefs = () => { try { return JSON.parse(localStorage.getItem(PREFS)) || {}; } catch (e) { return {}; } };
  const salvarPrefs = valor => { try { localStorage.setItem(PREFS, JSON.stringify(valor)); } catch (e) { /* só conveniência */ } };
  const mapa = () => (window.CasaACasa && window.CasaACasa.estado && window.CasaACasa.estado.mapa) || null;

  function el(tag, props, ...filhos) {
    const no = document.createElement(tag);
    for (const [chave, valor] of Object.entries(props || {})) {
      if (valor === null || valor === undefined || valor === false) continue;
      if (chave === 'class') no.className = valor;
      else if (chave.startsWith('on')) no.addEventListener(chave.slice(2), valor);
      else no.setAttribute(chave, valor === true ? '' : valor);
    }
    for (const filho of filhos.flat()) {
      if (filho === null || filho === undefined || filho === false || filho === '') continue;
      no.append(filho.nodeType ? filho : document.createTextNode(String(filho)));
    }
    return no;
  }

  // ---------------------------------------------------------------- janela
  const janela = $('cac-pi-janela'), moldura = $('cac-pi-moldura');
  let focoAntes = null;

  function abrirJanela(url, titulo) {
    if (!janela || !moldura || !url) return false;
    const destino = new URL(url, location.href).href;
    // A mesma tela continua como estava (um rascunho não se perde ao fechar e abrir de novo).
    let atual = '';
    try { atual = moldura.contentWindow && moldura.contentWindow.location.href; } catch (e) { atual = ''; }
    if (!atual || atual === 'about:blank' || new URL(atual).pathname !== new URL(destino).pathname) moldura.src = destino;
    $('cac-pi-titulo').textContent = titulo;
    $('cac-pi-aba').href = destino;
    focoAntes = document.activeElement;
    janela.hidden = false;
    if (!navigator.onLine) aviso('Sem internet: a tela abre se já foi usada neste aparelho; o envio fica guardado e segue depois.');
    janela.querySelector('.cac-pi-folha').focus();
    return true;
  }

  function fecharJanela() {
    if (!janela || janela.hidden) return;
    janela.hidden = true;
    if (focoAntes && focoAntes.focus) focoAntes.focus();
    if (camadaLigada()) carregar();   // uma comunicação nova já aparece no mapa
  }

  function aviso(texto) {
    const area = $('cac-avisos');
    if (!area) return;
    const item = el('div', { class: 'cac-aviso' }, texto);
    area.append(item);
    setTimeout(() => item.classList.add('sai'), 3200);
    setTimeout(() => item.remove(), 3700);
  }

  if (janela) {
    $('cac-pi-fechar').addEventListener('click', fecharJanela);
    janela.addEventListener('click', evento => { if (evento.target === janela) fecharJanela(); });
    document.addEventListener('keydown', evento => {
      if (evento.key === 'Escape' && !janela.hidden) { evento.preventDefault(); fecharJanela(); }
    });
  }

  const botao = $('cac-prefeitura');
  if (botao && janela && cfg.prefeitura) {
    botao.addEventListener('click', evento => {
      if (evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.button > 0) return;  // outra aba, se a pessoa quiser
      if (abrirJanela(cfg.prefeitura, '🏛️ Comunicar à Prefeitura')) evento.preventDefault();
    });
  }

  // ---------------------------------------------------------------- camada no mapa
  const painel = $('cac-pi');
  if (!painel || !cfg.prefeitura_mapa) return;
  const opcoes = $('cac-pi-opcoes');
  if (!opcoes) return;
  const caixas = Object.keys(ROTULOS).map(status => {
    const caixa = el('input', { type: 'checkbox', 'data-pi-status': status });
    opcoes.append(el('label', {}, caixa, ' ', el('i', { class: 'cac-pi-cor ' + status }), ' ' + ROTULOS[status]));
    return caixa;
  });
  const nota = $('cac-pi-nota');
  const prefs = lerPrefs();
  let camada = null, pontos = null, relogio = null, pedindo = false;

  caixas.forEach(caixa => { caixa.checked = Boolean(prefs[caixa.dataset.piStatus]); });
  if (caixas.some(caixa => caixa.checked)) painel.open = true;

  function camadaLigada() { return caixas.some(caixa => caixa.checked); }
  function ligados() { return new Set(caixas.filter(caixa => caixa.checked).map(caixa => caixa.dataset.piStatus)); }

  function urlDoItem(id) {
    return cfg.prefeitura_item ? cfg.prefeitura_item.replace(/\/0(?=$|[/?#])/, '/' + id) : '';
  }

  function balao(ponto) {
    const corpo = el('div', { class: 'cac-pi-balao' },
      el('strong', {}, `Nº ${ponto.numero} · ${ponto.categoria_rotulo || 'Comunicação'}`),
      el('span', { class: 'cac-pi-selo ' + ponto.status }, ponto.status_rotulo || ROTULOS[ponto.status] || ponto.status),
      ponto.descricao ? el('p', {}, ponto.descricao) : null,
      ponto.referencia ? el('p', {}, '📍 ' + ponto.referencia) : null,
      ponto.criado_local ? el('small', {}, 'Comunicada em ' + ponto.criado_local) : null,
      ponto.foto ? el('img', { src: ponto.foto, alt: 'Foto da comunicação', loading: 'lazy' }) : null);
    const item = urlDoItem(ponto.id);
    if (item) {
      corpo.append(el('button', { type: 'button', class: 'cac-pi-abrir', onclick: () => {
        const m = mapa(); if (m) m.closePopup();
        abrirJanela(item, `🏛️ Comunicação nº ${ponto.numero}`);
      } }, 'Ver comunicação'));
    }
    return corpo;
  }

  function desenhar() {
    const m = mapa();
    if (!m) return;
    if (!camada) camada = L.layerGroup();
    camada.clearLayers();
    if (!camadaLigada() || !pontos) { m.removeLayer(camada); return; }
    const status = ligados();
    let total = 0;
    for (const ponto of pontos) {
      if (!status.has(ponto.status) || typeof ponto.lat !== 'number' || typeof ponto.lon !== 'number') continue;
      total += 1;
      const icone = L.divIcon({
        className: 'cac-pi-marca ' + ponto.status,
        html: `<span style="background:${CORES[ponto.status] || '#495057'}">${ponto.status === 'concluida' ? '✓' : '!'}</span>`,
        iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -12],
      });
      L.marker([ponto.lat, ponto.lon], { icon: icone, keyboard: true, title: `Prefeitura integrada nº ${ponto.numero}`, zIndexOffset: 5000 })
        .bindPopup(() => balao(ponto), { maxWidth: 260, autoPanPadding: [16, 16] })
        .addTo(camada);
    }
    camada.addTo(m);
    escrever(total ? `${total} ${total === 1 ? 'comunicação' : 'comunicações'} no mapa.` : 'Nenhuma comunicação nesse filtro.');
  }

  function escrever(texto) { if (nota) nota.textContent = texto; }

  async function carregar() {
    clearTimeout(relogio);
    if (!camadaLigada()) { desenhar(); return; }
    if (!navigator.onLine) {
      escrever(pontos ? 'Sem internet: mostrando o último retrato.' : 'Sem internet: a camada aparece quando o sinal voltar.');
      desenhar();
      relogio = setTimeout(carregar, ATUALIZAR_MS);
      return;
    }
    if (pedindo) return;
    pedindo = true;
    if (!pontos) escrever('Carregando…');
    try {
      const resposta = await fetch(cfg.prefeitura_mapa, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      const tipo = resposta.headers.get('Content-Type') || '';
      if (resposta.status === 403) throw new Error('Sua conta não vê o mapa da Prefeitura integrada.');
      if (!resposta.ok || resposta.redirected || !tipo.includes('json')) throw new Error('Não foi possível carregar agora.');
      const dados = await resposta.json();
      pontos = Array.isArray(dados.pontos) ? dados.pontos : [];
      desenhar();
    } catch (erro) {
      escrever(erro.message || 'Não foi possível carregar agora.');
      desenhar();
    } finally {
      pedindo = false;
      if (camadaLigada()) relogio = setTimeout(carregar, ATUALIZAR_MS);
    }
  }

  caixas.forEach(caixa => caixa.addEventListener('change', () => {
    const novo = {};
    caixas.forEach(c => { novo[c.dataset.piStatus] = c.checked; });
    salvarPrefs(novo);
    if (!camadaLigada()) { escrever(''); desenhar(); clearTimeout(relogio); return; }
    if (pontos) desenhar();
    carregar();
  }));
  window.addEventListener('online', () => { if (camadaLigada()) carregar(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && camadaLigada()) carregar(); });

  // O mapa nasce no casa_a_casa.js, carregado antes deste arquivo.
  if (camadaLigada()) carregar();
})();
