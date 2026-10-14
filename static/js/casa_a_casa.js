/* Casa a casa: mapa em branco dos quarteirões, plano do dia, visita imóvel a imóvel, ao vivo e sem internet. */
(function () {
  'use strict';

  const M = window.CasaACasaModel;
  const cfg = JSON.parse(document.getElementById('cac-config').textContent);
  // Os mesmos nomes que o service worker preserva ao trocar de versão.
  const CACHE_APP = 'petorlandia-casa-a-casa-v1';
  const CACHE_DADOS = 'petorlandia-casa-a-casa-dados-v1';
  const FILA = 'cac:fila:v1', ACOES = 'cac:acoes:v1', RECUSADAS = 'cac:recusadas:v1', PREFS = 'cac:prefs:v1';
  const ZOOM_CASAS = 16.5, ZOOM_NUMEROS = 17.5, ZOOM_ROTULOS = 14.5, ZOOM_RUAS = 15.5;
  const $ = id => document.getElementById(id);

  // ---------------------------------------------------------------- utilidades
  function h(tag, props, ...filhos) {
    const no = document.createElement(tag);
    for (const [chave, valor] of Object.entries(props || {})) {
      if (valor === null || valor === undefined || valor === false) continue;
      if (chave === 'class') no.className = valor;
      else if (chave === 'style') no.style.cssText = valor;
      else if (chave === 'dataset') Object.assign(no.dataset, valor);
      else if (chave.startsWith('on')) no.addEventListener(chave.slice(2), valor);
      else no.setAttribute(chave, valor === true ? '' : valor);
    }
    for (const filho of filhos.flat(3)) {
      if (filho === null || filho === undefined || filho === false) continue;
      no.append(filho.nodeType ? filho : document.createTextNode(String(filho)));
    }
    return no;
  }
  const lerLocal = (chave, padrao) => { try { return JSON.parse(localStorage.getItem(chave)) ?? padrao; } catch (e) { return padrao; } };
  const salvarLocal = (chave, valor) => { try { localStorage.setItem(chave, JSON.stringify(valor)); return true; } catch (e) { return false; } };
  // Dia de hoje em Orlândia (aaaa-mm-dd), qualquer que seja o fuso ou o idioma do aparelho.
  const hojeNoAparelho = () => {
    const partes = Object.fromEntries(new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' })
      .formatToParts(new Date()).map(parte => [parte.type, parte.value]));
    return `${partes.year}-${partes.month}-${partes.day}`;
  };
  const dataBr = iso => iso ? iso.slice(8, 10) + '/' + iso.slice(5, 7) : '';
  const horaBr = iso => { const t = Date.parse(iso || ''); return Number.isFinite(t) ? new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit' }).format(t) : ''; };
  const somarDias = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const plural = (n, um, varios) => n + ' ' + (n === 1 ? um : varios);
  const primeiroNome = nome => String(nome || '').trim().split(/\s+/)[0] || 'Sem nome';

  async function guardarCache(chave, dados) {
    try {
      const cache = await caches.open(CACHE_DADOS);
      await cache.put('/__casa-a-casa/' + chave, new Response(JSON.stringify(dados), { headers: { 'Content-Type': 'application/json' } }));
    } catch (e) { /* sem Cache Storage (http ou navegador antigo): segue só com a rede */ }
  }
  async function lerCache(chave) {
    try {
      const cache = await caches.open(CACHE_DADOS);
      const resposta = await cache.match('/__casa-a-casa/' + chave);
      return resposta ? await resposta.json() : null;
    } catch (e) { return null; }
  }

  // ---------------------------------------------------------------- estado
  const S = {
    base: null, blocos: [], porId: new Map(), casaPorId: new Map(),
    planos: [], visitas: new Map(), doDia: new Map(), ultimas: new Map(), agentes: [],
    hoje: hojeNoAparelho(), cursor: 0, completo: false, csrf: cfg.csrf,
    fila: lerLocal(FILA, []), acoes: lerLocal(ACOES, []), recusadas: lerLocal(RECUSADAS, []),
    prefs: Object.assign({ modo: cfg.registra ? 'rua' : 'escritorio', ruas: false, painel: true, vista: null }, lerLocal(PREFS, {})),
    aba: null, blocoAtivo: null, diaPlano: null, responsavelPlano: cfg.usuario ? cfg.usuario.id : null, planejando: true,
    selecionados: new Set(), origemPlano: null, salvandoPlano: false, buscaPlano: '', setorPlano: '', filtroCasas: 'todas',
    aoVivo: false, enviando: false, precisaEntrar: false, pronto: false, novas: new Set(),
    mapa: null, tela: null, poligonos: new Map(), camadaRotulos: null, camadaCasas: null, camadaRuas: null, camadaVias: null, eu: null,
  };
  if (!cfg.registra) S.prefs.modo = 'escritorio';
  const eu = () => cfg.usuario;
  // Tipos de recipiente da ficha do SISAWEB (1 a 40), vindos do servidor com a página.
  const GRUPOS_RECIPIENTE = cfg.recipientes || [];
  const TIPO_RECIPIENTE = new Map(GRUPOS_RECIPIENTE.flatMap(grupo => grupo.tipos.map(([numero, nome]) => [numero, { g: grupo.g, grupo: grupo.nome, nome }])));
  const codigoDoTipo = t => (TIPO_RECIPIENTE.has(t) ? TIPO_RECIPIENTE.get(t).g : '') + t;
  // Cada agente com uma cor, na ordem da equipe, para o plano no mapa.
  const CORES_AGENTE = ['#1c7ed6', '#d6336c', '#f08c00', '#2f9e44', '#7048e8', '#0c8599', '#e8590c', '#5c940d'];
  const corDoAgente = id => { const posicao = (cfg.equipe || []).findIndex(p => p.id === id); return posicao < 0 ? '#495057' : CORES_AGENTE[posicao % CORES_AGENTE.length]; };
  const casasDe = bloco => bloco.extras && bloco.extras.length ? bloco.casas.concat(bloco.extras) : bloco.casas;
  const nomeDoBloco = bloco => 'Quarteirão ' + bloco.n;
  const concluidosLocais = () => new Set(S.acoes.filter(a => a.acao === 'concluir').flatMap(a => a.blocos));

  function avisar(texto, tipo) {
    const aviso = h('div', { class: 'cac-aviso' + (tipo ? ' ' + tipo : '') }, texto);
    $('cac-avisos').append(aviso);
    setTimeout(() => aviso.classList.add('sai'), 3200);
    setTimeout(() => aviso.remove(), 3700);
  }

  function festa() {
    const palco = h('div', { class: 'cac-festa', 'aria-hidden': 'true' });
    const cores = ['#f59f00', '#2f9e44', '#1c7ed6', '#e64980', '#7950f2'];
    for (let i = 0; i < 70; i += 1) {
      palco.append(h('i', { style: `left:${Math.random() * 100}%;background:${cores[i % cores.length]};animation-delay:${Math.random() * 0.7}s;width:${6 + Math.random() * 7}px;height:${8 + Math.random() * 9}px` }));
    }
    document.body.append(palco);
    setTimeout(() => palco.remove(), 3400);
    if (navigator.vibrate) navigator.vibrate([40, 60, 40, 60, 120]);
  }

  // ---------------------------------------------------------------- dados
  function prepararBase(base) {
    S.base = base;
    S.vias = base.vias && base.vias.pontos ? base.vias : { nomes: [], pontos: [] };
    S.porId.clear(); S.casaPorId.clear();
    S.blocos = base.blocos.map((bloco, posicao) => {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const poligono of bloco.g) for (const [x, y] of poligono[0]) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
      const pronto = Object.assign({}, bloco, { posicao, casas: [], extras: [], caixa: [x0, y0, x1, y1], estado: null });
      S.porId.set(bloco.id, pronto);
      return pronto;
    });
    for (const [id, x, y, rua, n, cp, posicao] of base.imoveis) {
      const bloco = S.blocos[posicao];
      if (!bloco) continue;
      const casa = { id, x, y, rua: base.ruas[rua] || '', n, cp, bloco };
      bloco.casas.push(casa);
      S.casaPorId.set(id, casa);
    }
  }

  async function carregarBase() {
    const guardada = await lerCache('base');
    try {
      const cabecalhos = { Accept: 'application/json' };
      if (guardada) cabecalhos['If-None-Match'] = '"cac-' + guardada.versao + '"';
      const resposta = await fetch(cfg.urls.base, { credentials: 'same-origin', headers: cabecalhos });
      if (resposta.status === 304 && guardada) return guardada;
      if (resposta.ok && !resposta.redirected && (resposta.headers.get('Content-Type') || '').includes('json')) {
        const dados = await resposta.json();
        guardarCache('base', dados);
        return dados;
      }
    } catch (e) { /* sem rede: usa a que está no aparelho */ }
    return guardada;
  }

  async function pedir(url, corpo, repetir = true) {
    const opcoes = { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } };
    if (corpo) {
      opcoes.method = 'POST';
      // A página oculta o Referer por privacidade. Em HTTPS, CSRFProtect exige
      // a origem do formulário; envie-a só para este mesmo site, nunca a terceiros.
      opcoes.referrerPolicy = 'same-origin';
      opcoes.headers['Content-Type'] = 'application/json';
      opcoes.headers['X-CSRFToken'] = S.csrf;
      opcoes.body = JSON.stringify(corpo);
    }
    const resposta = await fetch(url, opcoes);
    const json = (resposta.headers.get('Content-Type') || '').includes('json');
    if (resposta.redirected || [401, 403, 404].includes(resposta.status)) { const erro = new Error('Entre de novo para continuar.'); erro.sessao = true; throw erro; }
    const dados = json ? await resposta.json() : null;
    const csrfRecusado = resposta.status === 400 && (!json || (dados &&
      (dados.error === 'CSRF token missing or invalid' || (dados.errors && dados.errors.csrf_token))));
    if (corpo && csrfRecusado && repetir) {
      // Token de formulário vencido (a tela ficou aberta ou veio do aparelho): pega um novo e repete uma vez.
      const estado = await pedir(cfg.urls.estado + (cfg.urls.estado.includes('?') ? '&' : '?') + 'desde=' + S.cursor);
      S.csrf = estado.csrf || S.csrf;
      return pedir(url, corpo, false);
    }
    if (!resposta.ok || !dados) {
      const erro = new Error(csrfRecusado ? 'Não foi possível renovar a sessão. Sua seleção e as visitas foram preservadas. Tente salvar novamente.'
        : (dados && (dados.erro || dados.message)) || 'O servidor não respondeu como esperado.');
      erro.conflito = resposta.status === 409;
      throw erro;
    }
    return dados;
  }

  function aplicarEstado(dados) {
    if (dados.csrf) S.csrf = dados.csrf;
    const mudouDia = dados.hoje && dados.hoje !== S.hoje;
    if (dados.hoje) S.hoje = dados.hoje;
    const assinatura = JSON.stringify(dados.planos);
    let mudou = assinatura !== S.assinaturaPlanos || mudouDia;
    S.assinaturaPlanos = assinatura;
    S.planos = dados.planos || [];
    S.agentes = dados.agentes || [];
    if (!dados.parcial) {
      S.visitas = new Map(); S.doDia = new Map();
      mudou = true;
    }
    for (const v of dados.visitas || []) {
      const anterior = S.visitas.get(v.m);
      S.visitas.set(v.m, M.maisRecente(anterior, v));
      if (v.d === S.hoje) S.doDia.set(v.i, v);
      if (dados.parcial && (!eu() || v.ai !== eu().id)) S.novas.add(v.m);
      mudou = true;
    }
    if (mudouDia) for (const [chave, v] of S.doDia) if (v.d !== S.hoje) S.doDia.delete(chave);
    S.cursor = Math.max(S.cursor, dados.cursor || 0);
    S.completo = !mudouDia;
    if (!dados.parcial || (dados.visitas || []).length || mudou) {
      guardarCache('estado', { hoje: S.hoje, cursor: S.cursor, planos: S.planos, agentes: S.agentes, visitas: Array.from(S.visitas.values()) });
    }
    if (S.base && dados.versao_base && dados.versao_base !== S.base.versao && !S.recarregandoBase) {
      S.recarregandoBase = true;
      carregarBase().then(base => { if (base && base.versao !== S.base.versao) { prepararBase(base); montarQuarteiroes(); recalcular(); desenhar(); } }).finally(() => { S.recarregandoBase = false; });
    }
    return mudou;
  }

  function recalcular() {
    const daFila = S.fila.map(visita => M.comoRegistro(visita, eu()));
    S.ultimas = M.juntarVisitas(S.visitas.values(), daFila);
    for (const bloco of S.blocos) bloco.extras = [];
    for (const v of S.ultimas.values()) {
      if (S.casaPorId.has(v.m)) continue;
      const bloco = S.porId.get(v.b);
      if (bloco) bloco.extras.push({ id: v.m, x: v.lo ?? bloco.c[0], y: v.la ?? bloco.c[1], rua: v.lg || 'Imóvel acrescentado', n: v.n || 's/n', cp: v.cp || '', bloco, extra: true });
    }
    const planos = new Map();
    for (const plano of S.planos) { if (!planos.has(plano.b)) planos.set(plano.b, []); planos.get(plano.b).push(plano); }
    const agora = new Date().toISOString();
    for (const id of concluidosLocais()) {
      const lista = (planos.get(id) || []).map(p => (!p.c && p.d <= S.hoje ? Object.assign({}, p, { c: agora, local: true }) : p));
      if (!lista.some(p => p.c && M.dia(p.c) === M.dia(agora))) lista.push({ b: id, d: S.hoje, c: agora, ri: eu() && eu().id, r: eu() ? eu().nome : '', local: true });
      planos.set(id, lista);
    }
    for (const bloco of S.blocos) {
      bloco.planos = planos.get(bloco.id) || [];
      bloco.estado = M.estadoDoBloco(bloco.planos, casasDe(bloco), S.ultimas, S.hoje, S.base.janela_dias);
    }
  }

  // ---------------------------------------------------------------- envio e atualização
  async function enviarPendentes() {
    if (!cfg.registra || S.enviando || (!S.fila.length && !S.acoes.length)) return;
    S.enviando = true;
    desenharConexao();
    try {
      while (S.fila.length) {
        const lote = S.fila.slice(0, 100);
        const resposta = await pedir(cfg.urls.visitas, { visitas: lote });
        const aceitas = new Set(resposta.aceitas || []);
        const recusadas = new Map((resposta.recusadas || []).map(r => [r.uuid, r.motivo]));
        for (const visita of lote) {
          if (recusadas.has(visita.uuid)) S.recusadas.push({ visita, motivo: recusadas.get(visita.uuid) });
        }
        const antes = S.fila.length;
        S.fila = S.fila.filter(visita => !aceitas.has(visita.uuid) && !recusadas.has(visita.uuid));
        salvarLocal(FILA, S.fila); salvarLocal(RECUSADAS, S.recusadas);
        if (S.fila.length === antes) break;
      }
      while (S.acoes.length) {
        await pedir(cfg.urls.plano, S.acoes[0]);
        S.acoes.shift();
        salvarLocal(ACOES, S.acoes);
      }
      S.precisaEntrar = false;
    } catch (erro) {
      if (erro.sessao) S.precisaEntrar = true;
    } finally {
      S.enviando = false;
    }
  }

  async function atualizar() {
    try {
      const sufixo = S.completo && S.cursor ? (cfg.urls.estado.includes('?') ? '&' : '?') + 'desde=' + S.cursor : '';
      const mudou = aplicarEstado(await pedir(cfg.urls.estado + sufixo));
      S.aoVivo = true; S.precisaEntrar = false;
      if (mudou) { recalcular(); desenhar(); }
    } catch (erro) {
      S.aoVivo = false;
      if (erro.sessao) S.precisaEntrar = true;
    }
  }

  async function ciclo() {
    clearTimeout(S.relogio);
    if (navigator.onLine) {
      const tinha = S.fila.length + S.acoes.length;
      await enviarPendentes();
      await atualizar();
      if (tinha && !S.fila.length && !S.acoes.length && S.aoVivo) {
        if (S.ficouFora) avisar(`${plural(tinha, 'registro enviado', 'registros enviados')} para a equipe ✔`, 'bom');
        S.ficouFora = false;
        recalcular(); desenhar();
      }
    } else {
      S.aoVivo = false;
    }
    if (!S.aoVivo && (S.fila.length || S.acoes.length)) S.ficouFora = true;
    desenharConexao();
    S.relogio = setTimeout(ciclo, document.hidden ? 45000 : (S.aoVivo ? 8000 : 15000));
  }

  // ---------------------------------------------------------------- mapa
  function iniciarMapa() {
    S.mapa = L.map('cac-mapa', { preferCanvas: true, zoomControl: false, attributionControl: false, minZoom: 12, maxZoom: 21, zoomSnap: 0.5, zoomDelta: 0.5 });
    L.control.zoom({ position: 'bottomright', zoomInTitle: 'Aproximar', zoomOutTitle: 'Afastar' }).addTo(S.mapa);
    S.tela = L.canvas({ padding: 0.4 });
    S.camadaQuarteiroes = L.layerGroup().addTo(S.mapa);
    S.camadaVias = L.layerGroup().addTo(S.mapa);
    S.camadaCasas = L.layerGroup().addTo(S.mapa);
    S.camadaRotulos = L.layerGroup().addTo(S.mapa);
    S.mapa.on('moveend', () => {
      const centro = S.mapa.getCenter();
      S.prefs.vista = [centro.lat, centro.lng, S.mapa.getZoom()];
      salvarLocal(PREFS, S.prefs);
      desenharDetalhes();
    });
  }

  function verCidade() {
    const caixas = S.blocos.map(b => b.caixa);
    if (!caixas.length) { S.mapa.setView([-20.72, -47.88], 14); return; }
    S.mapa.fitBounds([[Math.min(...caixas.map(c => c[1])), Math.min(...caixas.map(c => c[0]))], [Math.max(...caixas.map(c => c[3])), Math.max(...caixas.map(c => c[2]))]], { padding: [12, 12] });
  }

  function estiloDoBloco(bloco) {
    const cores = M.BLOCOS[bloco.estado ? bloco.estado.tipo : 'livre'];
    const selecionado = S.prefs.modo === 'escritorio' && S.selecionados.has(bloco.id);
    const ativo = S.blocoAtivo === bloco || selecionado;
    const plano = S.prefs.modo === 'escritorio' && (bloco.planos || []).find(p => p.d === (S.diaPlano || S.hoje));
    const escritorio = S.prefs.modo === 'escritorio';
    return {
      renderer: S.tela, color: ativo ? '#0b6568' : (plano ? corDoAgente(plano.ri) : cores.borda), weight: ativo ? 4 : (plano ? 2 : 1),
      fillColor: selecionado ? '#b2f2e5' : (plano ? corDoAgente(plano.ri) : escritorio ? '#fff' : cores.fundo), fillOpacity: plano && !selecionado ? 0.22 : (S.prefs.ruas ? 0.55 : 1), dashArray: selecionado ? '5 3' : null,
    };
  }

  function montarQuarteiroes() {
    S.camadaQuarteiroes.clearLayers();
    S.poligonos.clear();
    for (const bloco of S.blocos) {
      const forma = L.polygon(bloco.g.map(poligono => poligono.map(anel => anel.map(([x, y]) => [y, x]))), estiloDoBloco(bloco));
      forma.on('click', evento => { L.DomEvent.stopPropagation(evento); tocarBloco(bloco); });
      forma.addTo(S.camadaQuarteiroes);
      S.poligonos.set(bloco.id, forma);
    }
  }

  function naVista(caixa, limites) {
    return caixa[2] >= limites.getWest() && caixa[0] <= limites.getEast() && caixa[3] >= limites.getSouth() && caixa[1] <= limites.getNorth();
  }

  /* Nome das ruas, escrito ao longo do eixo quando o mapa está aproximado. Cada rua tem pontos a cada ~70 m;
     entra na tela o que não encosta em outro nome, e o mesmo nome não se repete a poucos passos. */
  function desenharNomesDeRua(zoom, limites) {
    S.camadaVias.clearLayers();
    if (zoom < ZOOM_RUAS || !S.vias.pontos.length) return;
    const letra = zoom >= 18.5 ? 15 : (zoom >= 17.5 ? 13.5 : (zoom >= 16.5 ? 12 : 11));
    const repeticao = zoom >= 18 ? 300 : 220;
    const postos = [];
    for (const [x, y, giro, indice] of S.vias.pontos) {
      if (!limites.contains([y, x])) continue;
      const nome = S.vias.nomes[indice];
      const ponto = S.mapa.latLngToContainerPoint([y, x]);
      const meia = nome.length * letra * 0.29 + 4;
      let cabe = true;
      for (const outro of postos) {
        const dx = ponto.x - outro.x, dy = ponto.y - outro.y, distancia = dx * dx + dy * dy;
        const minima = outro.indice === indice ? repeticao : (meia + outro.meia) * 0.72;
        if (distancia < minima * minima) { cabe = false; break; }
      }
      if (!cabe) continue;
      postos.push({ x: ponto.x, y: ponto.y, meia, indice });
      const icone = L.divIcon({ className: 'cac-via', html: '<span></span>', iconSize: [0, 0] });
      const marcador = L.marker([y, x], { icon: icone, interactive: false, keyboard: false, zIndexOffset: 4000 }).addTo(S.camadaVias);
      const texto = marcador.getElement() && marcador.getElement().querySelector('span');
      if (texto) { texto.textContent = nome; texto.style.cssText = `font-size:${letra}px;transform:translate(-50%,-50%) rotate(${giro}deg)`; }
      if (postos.length >= 150) break;
    }
  }

  function desenharDetalhes() {
    if (!S.mapa || !S.base) return;
    const zoom = S.mapa.getZoom(), limites = S.mapa.getBounds().pad(0.08);
    S.camadaRotulos.clearLayers();
    S.camadaCasas.clearLayers();
    desenharNomesDeRua(zoom, limites);
    const visiveis = S.blocos.filter(bloco => naVista(bloco.caixa, limites));
    // Número do quarteirão: sempre que couber; afastado, só os que têm trabalho.
    let rotulos = 0;
    for (const bloco of visiveis) {
      const tipo = bloco.estado.tipo;
      if (zoom < ZOOM_ROTULOS && (tipo === 'livre' || tipo === 'anterior') && S.blocoAtivo !== bloco) continue;
      if (rotulos > 450) continue;
      const prog = bloco.estado.prog;
      const comConta = (S.prefs.modo === 'rua' || (S.diaPlano || S.hoje) === S.hoje) && (tipo === 'andamento' || tipo === 'planejado' || tipo === 'concluido') && prog.total && zoom >= 14;
      const plano = zoom >= 14 ? planoDoRotulo(bloco) : null;
      const icone = L.divIcon({
        className: 'cac-rotulo cac-rotulo-' + tipo + (S.blocoAtivo === bloco ? ' ativo' : ''),
        html: '<div><b></b>' + (comConta ? '<i></i>' : '') + (plano ? '<u></u>' : '') + '</div>', iconSize: [0, 0],
      });
      const marcador = L.marker([bloco.c[1], bloco.c[0]], { icon: icone, interactive: false, keyboard: false }).addTo(S.camadaRotulos);
      const no = marcador.getElement();
      if (no) {
        no.querySelector('b').textContent = bloco.n;
        if (comConta) no.querySelector('i').textContent = prog.feitas + '/' + prog.total;
        if (plano) { const quem = no.querySelector('u'); quem.textContent = primeiroNome(plano.r); quem.style.background = corDoAgente(plano.ri); }
      }
      rotulos += 1;
    }
    $('cac-dica').textContent = S.prefs.modo === 'escritorio' && S.aba === 'plano' ? 'Selecione quarteirões no mapa ou pela busca'
      : zoom >= ZOOM_NUMEROS ? 'Toque no número da casa para registrar'
      : (zoom >= ZOOM_CASAS ? 'Aproxime mais um pouco para ver os números' : (S.prefs.modo === 'rua' ? 'Toque em um quarteirão para trabalhar nele' : ''));
    if (zoom < ZOOM_CASAS) return;
    // Casas: ponto colorido; bem perto, o número.
    const casas = [];
    for (const bloco of visiveis) for (const casa of casasDe(bloco)) if (limites.contains([casa.y, casa.x])) casas.push(casa);
    const comNumero = zoom >= ZOOM_NUMEROS && casas.length <= 420;
    const recuo = comNumero ? 13 : 7;
    const centros = new Map();
    for (const casa of casas) {
      const visita = S.ultimas.get(casa.id);
      const cor = M.corDaCasa(visita, casa.bloco.estado.inicio);
      if (!centros.has(casa.bloco)) centros.set(casa.bloco, S.mapa.latLngToContainerPoint([casa.bloco.c[1], casa.bloco.c[0]]));
      const naTela = S.mapa.latLngToContainerPoint([casa.y, casa.x]), centro = centros.get(casa.bloco);
      const dx = centro.x - naTela.x, dy = centro.y - naTela.y, distancia = Math.hypot(dx, dy);
      const lugar = distancia > recuo * 2 ? S.mapa.containerPointToLatLng([naTela.x + dx / distancia * recuo, naTela.y + dy / distancia * recuo]) : [casa.y, casa.x];
      if (comNumero) {
        const icone = L.divIcon({ className: 'cac-casa' + (cor.vazia ? ' vazia' : '') + (cor.apagada ? ' apagada' : '') + (S.novas.has(casa.id) ? ' nova' : ''), html: '<span></span>', iconSize: [0, 0] });
        const marcador = L.marker(lugar, { icon: icone, keyboard: false }).addTo(S.camadaCasas);
        const no = marcador.getElement();
        if (no) {
          const etiqueta = no.querySelector('span');
          etiqueta.textContent = casa.n;
          etiqueta.style.cssText = `background:${cor.fundo};color:${cor.texto};border-color:${cor.cor}`;
          no.title = casa.rua + ', ' + casa.n;
        }
        marcador.on('click', () => abrirCasa(casa));
      } else {
        L.circleMarker(lugar, { renderer: S.tela, radius: 5, color: cor.cor, weight: 1.5, fillColor: cor.fundo, fillOpacity: 1 })
          .on('click', () => abrirCasa(casa)).addTo(S.camadaCasas);
      }
    }
    S.novas.clear();
  }

  // Quem trabalha o quarteirão: no escritório, o plano do dia escolhido; na rua, o plano em aberto.
  function planoDoRotulo(bloco) {
    if (S.prefs.modo === 'escritorio') {
      const dia = S.diaPlano || S.hoje;
      const plano = (bloco.planos || []).find(p => p.d === dia && !p.c);
      return plano && plano.r ? plano : null;
    }
    const e = bloco.estado;
    return (e.tipo === 'planejado' || e.tipo === 'andamento') && e.plano && e.plano.r ? e.plano : null;
  }

  function desenharMapa() {
    for (const bloco of S.blocos) { const forma = S.poligonos.get(bloco.id); if (forma) forma.setStyle(estiloDoBloco(bloco)); }
    desenharDetalhes();
  }

  function irParaBloco(bloco) {
    S.mapa.fitBounds([[bloco.caixa[1], bloco.caixa[0]], [bloco.caixa[3], bloco.caixa[2]]], { padding: [34, 34], maxZoom: 19 });
  }

  function alternarRuas() {
    S.prefs.ruas = !S.prefs.ruas;
    salvarLocal(PREFS, S.prefs);
    aplicarRuas();
    desenharMapa();
  }
  function aplicarRuas() {
    $('cac-ruas').setAttribute('aria-pressed', String(S.prefs.ruas));
    if (S.camadaRuas) { S.mapa.removeLayer(S.camadaRuas); S.camadaRuas = null; }
    if (!S.prefs.ruas) return;
    S.camadaRuas = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom: 19, maxZoom: 21, opacity: 0.8 }).addTo(S.mapa);
    S.camadaRuas.bringToBack();
    if (!navigator.onLine) avisar('As ruas ao fundo aparecem quando houver internet.');
  }

  function ondeEstou() {
    if (!navigator.geolocation) { avisar('Este aparelho não informa a localização.'); return; }
    navigator.geolocation.getCurrentPosition(posicao => {
      const ponto = [posicao.coords.latitude, posicao.coords.longitude];
      S.posicao = ponto;
      if (S.eu) S.eu.setLatLng(ponto);
      else S.eu = L.circleMarker(ponto, { radius: 8, color: '#fff', weight: 3, fillColor: '#1c7ed6', fillOpacity: 1, interactive: false }).addTo(S.mapa);
      S.mapa.setView(ponto, Math.max(S.mapa.getZoom(), 18));
    }, () => avisar('Não consegui pegar a localização. Confira a permissão do navegador.'), { enableHighAccuracy: true, timeout: 9000, maximumAge: 20000 });
  }

  // ---------------------------------------------------------------- ações
  function tocarBloco(bloco) {
    if (S.prefs.modo === 'escritorio' && S.planejando && cfg.registra && S.aba === 'plano') { selecionarBloco(bloco); return; }
    S.blocoAtivo = bloco;
    S.aba = 'quarteirao';
    abrirPainel(true);
    desenhar();
    if (S.prefs.modo === 'rua' || S.mapa.getZoom() < 15) irParaBloco(bloco);
  }

  async function mudarPlano(corpo, sucesso) {
    if (S.salvandoPlano) return false;
    if (!navigator.onLine) { avisar('O plano é feito com internet. Tente de novo quando o sinal voltar.'); return false; }
    S.salvandoPlano = true;
    desenharPainel();
    try {
      const dados = await pedir(cfg.urls.plano, corpo);
      aplicarEstado(Object.assign({ parcial: false }, dados));
      recalcular(); desenhar();
      if (sucesso) avisar(sucesso(dados), 'bom');
      return true;
    } catch (erro) {
      if (erro.conflito) await atualizar().catch(() => {});
      if (erro.sessao) { S.precisaEntrar = true; desenharConexao(); }
      avisar(erro.message || 'Não deu para salvar o plano.', 'ruim');
      return false;
    } finally {
      S.salvandoPlano = false;
      desenharPainel();
    }
  }

  function selecionarBloco(bloco) {
    if (S.salvandoPlano) return;
    if (S.origemPlano) { avisar('Finalize ou cancele o reagendamento antes de selecionar outros quarteirões.'); return; }
    if (S.selecionados.has(bloco.id)) S.selecionados.delete(bloco.id);
    else if (S.selecionados.size < 400) S.selecionados.add(bloco.id);
    else { avisar('Selecione até 400 quarteirões por vez.'); return; }
    desenhar();
  }

  function fotografiaPlano(blocos, dia) {
    return blocos.map(b => {
      const p = b.planos.find(p => p.d === dia);
      return p ? { b: b.id, id: p.id, ri: p.ri, c: p.c, v: p.v } : { b: b.id };
    });
  }

  async function aplicarSelecao() {
    const blocos = S.blocos.filter(b => S.selecionados.has(b.id));
    if (!blocos.length || S.salvandoPlano) return;
    const dia = S.diaPlano || S.hoje;
    const ok = await mudarPlano({ acao: S.origemPlano ? 'reagendar' : 'planejar', blocos: blocos.map(b => b.id), data: dia,
      origem: S.origemPlano, responsavel_id: S.responsavelPlano, esperado: fotografiaPlano(blocos, S.origemPlano || dia) },
      dados => `${dados.feitos} de ${blocos.length} quarteirões salvos para ${dataBr(dia)}.${dados.feitos < blocos.length ? ' Quarteirões concluídos foram preservados.' : ''}`);
    if (ok) { S.selecionados.clear(); S.origemPlano = null; desenhar(); }
  }

  function reagendarBloco(bloco, dia) {
    S.selecionados = new Set([bloco.id]); S.origemPlano = dia;
    S.responsavelPlano = bloco.planos.find(p => p.d === dia).ri || null;
    const seguinte = M.diasDeTrabalho(somarDias(dia < S.hoje ? S.hoje : dia, 1), 1)[0];
    S.diaPlano = seguinte <= somarDias(S.hoje, 60) ? seguinte : S.hoje;
    desenhar(); $('cac-conteudo').scrollTop = 0;
  }

  function removerDoPlano(bloco, dia) {
    if (!window.confirm(`Retirar ${nomeDoBloco(bloco)} (SC ${bloco.s}) do plano de ${dataBr(dia)}? Visitas registradas serão preservadas.`)) return;
    mudarPlano({ acao: 'remover', blocos: [bloco.id], data: dia, esperado: fotografiaPlano([bloco], dia) },
      dados => dados.feitos ? 'Quarteirão retirado do plano.' : 'Este quarteirão já começou e foi mantido no plano.');
  }

  function concluirBloco(bloco) {
    const faltam = bloco.estado.prog.total - bloco.estado.prog.feitas;
    if (faltam > 0 && !window.confirm(`Ainda ${faltam === 1 ? 'falta 1 imóvel' : 'faltam ' + faltam + ' imóveis'} sem registro em ${nomeDoBloco(bloco)}. Concluir mesmo assim?`)) return;
    const acoes = S.acoes.concat({ acao: 'concluir', blocos: [bloco.id] });
    if (!salvarLocal(ACOES, acoes)) { avisar('Não foi possível guardar a conclusão. Libere espaço no aparelho e tente de novo.', 'ruim'); return; }
    S.acoes = acoes;
    recalcular(); desenhar();
    festa();
    avisar(`${nomeDoBloco(bloco)} concluído! +${M.XP.quarteirao} pontos 🏁`, 'bom');
    ciclo();
  }

  function reabrirBloco(bloco) {
    const local = S.acoes.findIndex(a => a.acao === 'concluir' && a.blocos.includes(bloco.id));
    if (local >= 0) { S.acoes.splice(local, 1); salvarLocal(ACOES, S.acoes); recalcular(); desenhar(); return; }
    mudarPlano({ acao: 'reabrir', blocos: [bloco.id] }, () => nomeDoBloco(bloco) + ' reaberto');
  }

  function registrar(casa, dados, seguir) {
    const bloco = casa.bloco;
    const anterior = S.ultimas.get(casa.id);
    const feitasAntes = bloco.estado.prog.feitas;
    const visita = M.novaVisita(Object.assign({}, dados, {
      bloco: bloco.id, imovel: casa.id, data: S.hoje, logradouro: casa.rua, numero: casa.n, complemento: casa.cp, lat: casa.y, lng: casa.x,
    }));
    const fila = S.fila.concat(visita);
    if (!salvarLocal(FILA, fila)) { avisar('Não foi possível guardar a visita: o aparelho está sem espaço. Mantenha a ficha aberta e libere espaço para tentar de novo.', 'ruim'); return; }
    S.fila = fila;
    recalcular();
    const recuperou = anterior && M.PENDENCIA.has(anterior.s) && M.INSPECIONADO.has(visita.situacao);
    const ganho = M.XP.visita + (recuperou ? M.XP.recuperada : 0);
    if (navigator.vibrate) navigator.vibrate(25);
    avisar(`${casa.rua}, ${casa.n}: ${M.POR_ID[visita.situacao].nome} · +${ganho} pontos${recuperou ? ' (pendência recuperada 🔑)' : ''}`, 'bom');
    const prog = bloco.estado.prog;
    const fechou = prog.total > 0 && prog.feitas === prog.total && feitasAntes < prog.total;
    fecharFicha(true);
    desenhar();
    if (fechou) { festa(); avisar(`Todas as casas de ${nomeDoBloco(bloco)} registradas! Toque em “Concluir quarteirão”.`, 'bom'); S.blocoAtivo = bloco; S.aba = 'quarteirao'; desenharPainel(); }
    else if (seguir) { const proxima = M.proximaCasa(casasDe(bloco), S.ultimas, bloco.estado.inicio, casa.id); if (proxima) { S.mapa.panTo([proxima.y, proxima.x]); abrirCasa(proxima); } }
    ciclo();
  }

  // ---------------------------------------------------------------- ficha do imóvel
  function fecharFicha(forcar = false) {
    if (forcar !== true && S.fichaSuja && !window.confirm('Sair sem salvar as alterações desta visita?')) return;
    $('cac-ficha').hidden = true; S.fichaCasa = null; S.fichaSuja = false;
    document.querySelector('.cac-corpo').inert = false;
    document.querySelector('.cac-topo').inert = false;
    if (S.focoAnterior && S.focoAnterior.isConnected) S.focoAnterior.focus();
  }

  function contador(rotulo, valor, aoMudar) {
    const campo = h('input', { type: 'number', inputmode: 'numeric', min: '0', max: '999', value: String(valor), 'aria-label': rotulo });
    const mudar = delta => { campo.value = String(Math.max(0, Math.min(999, (parseInt(campo.value, 10) || 0) + delta))); aoMudar(parseInt(campo.value, 10) || 0); };
    campo.addEventListener('input', () => aoMudar(Math.max(0, Math.min(999, parseInt(campo.value, 10) || 0))));
    return h('div', { class: 'cac-contador' }, h('span', {}, rotulo),
      h('div', {}, h('button', { type: 'button', 'aria-label': 'Menos em ' + rotulo, onclick: () => mudar(-1) }, '−'), campo, h('button', { type: 'button', 'aria-label': 'Mais em ' + rotulo, onclick: () => mudar(1) }, '+')));
  }

  function abrirCasa(casa, nova) {
    if (!cfg.registra) { mostrarVisita(casa); return; }
    S.fichaCasa = casa;
    S.fichaSuja = false;
    S.focoAnterior = document.activeElement;
    S.blocoAtivo = casa.bloco;
    const anterior = S.ultimas.get(casa.id);
    const deHoje = anterior && anterior.d === S.hoje ? anterior : null;
    const versaoAoAbrir = anterior ? anterior.u : null;
    const d = {
      situacao: deHoje ? deHoje.s : '', recipientes_existentes: deHoje ? deHoje.re : 0, recipientes_agua: deHoje ? deHoje.ra : 0,
      recipientes_larva: deHoje ? deHoje.rl : 0, larvas: deHoje ? Boolean(deHoje.l) : false, tubitos: deHoje ? deHoje.t : 0,
      controle_mecanico: deHoje ? Boolean(deHoje.cm) : false, controle_alternativo: deHoje ? Boolean(deHoje.ca) : false,
      tratamento_focal: deHoje ? Boolean(deHoje.tf) : false, observacao: deHoje ? deHoje.o : '',
      recipientes: deHoje && deHoje.rt ? deHoje.rt.map(r => Object.assign({}, r)) : [],
    };
    $('cac-ficha-titulo').textContent = nova ? 'Imóvel que não está na lista' : `${casa.rua}, ${casa.n}`;
    const posicaoCasa = casasDe(casa.bloco).findIndex(c => c.id === casa.id) + 1;
    $('cac-ficha-sub').textContent = `${nomeDoBloco(casa.bloco)} · SC ${casa.bloco.s}` + (casa.cp ? ' · ' + casa.cp : '') + (posicaoCasa ? ` · Imóvel ${posicaoCasa} de ${casasDe(casa.bloco).length}` : '');
    const corpo = $('cac-ficha-corpo');
    $('cac-ficha').querySelector('.cac-ficha-acoes')?.remove();
    corpo.replaceChildren();

    if (nova) {
      const ruas = Array.from(new Set(casa.bloco.casas.map(c => c.rua))).sort();
      const lista = h('datalist', { id: 'cac-ruas-do-bloco' }, ruas.map(rua => h('option', { value: rua })));
      corpo.append(h('div', { class: 'cac-nova' },
        h('label', {}, 'Rua', h('input', { type: 'text', id: 'cac-nova-rua', list: 'cac-ruas-do-bloco', maxlength: '200', value: ruas[0] || '', autocomplete: 'off' })), lista,
        h('label', {}, 'Número', h('input', { type: 'text', id: 'cac-nova-numero', maxlength: '20', inputmode: 'numeric', autocomplete: 'off' })),
        h('label', {}, 'Complemento', h('input', { type: 'text', id: 'cac-nova-complemento', maxlength: '60', placeholder: 'fundos, casa 2…', autocomplete: 'off' }))));
    }
    if (anterior) {
      const s = M.POR_ID[anterior.s];
      corpo.append(h('p', { class: 'cac-ultima' }, `Última visita: ${s.icone} ${s.nome}${anterior.l ? ' com larva' : ''} em ${dataBr(anterior.d)}${anterior.a ? ' por ' + primeiroNome(anterior.a) : ''}${anterior.pendente ? ' (ainda não enviada)' : ''}`));
    }

    const detalhes = h('div', { class: 'cac-detalhes' });
    const acoes = h('div', { class: 'cac-ficha-acoes' });
    const botoes = h('div', { class: 'cac-situacoes', role: 'radiogroup', 'aria-label': 'Situação do imóvel' });
    function desenharDetalhesDaFicha() {
      detalhes.replaceChildren();
      for (const botao of botoes.children) botao.setAttribute('aria-checked', String(botao.dataset.id === d.situacao));
      acoes.hidden = !d.situacao;
      if (!d.situacao) return;
      if (M.INSPECIONADO.has(d.situacao)) {
        const larvas = h('input', { type: 'checkbox', id: 'cac-larvas' });
        larvas.checked = d.larvas;
        larvas.addEventListener('change', () => { d.larvas = larvas.checked; });
        const chip = (rotulo, chave) => {
          const marca = h('input', { type: 'checkbox' });
          marca.checked = d[chave];
          marca.addEventListener('change', () => { d[chave] = marca.checked; });
          return h('label', { class: 'cac-chip' }, marca, h('span', {}, rotulo));
        };
        const marcarLarva = v => { if (v > 0 && !larvas.checked) { larvas.checked = true; d.larvas = true; } };
        // Totais do boletim: digitados, ou a soma dos tipos quando há tipo anotado.
        const totais = h('div', { class: 'cac-contadores' });
        const notaTotais = h('p', { class: 'cac-nota' });
        const desenharTotais = () => {
          const soma = M.recipientesPorTipo(d.recipientes).length ? M.somaDosTipos(d.recipientes) : null;
          notaTotais.textContent = soma ? 'Soma dos tipos anotados abaixo' : '';
          notaTotais.hidden = !soma;
          totais.replaceChildren(...(soma
            ? [['Existentes', soma.e], ['Com água', soma.a], ['Com larva', soma.l]].map(([rotulo, valor]) => h('div', { class: 'cac-contador cac-soma' }, h('span', {}, rotulo), h('output', {}, String(valor))))
            : [contador('Existentes', d.recipientes_existentes, v => { d.recipientes_existentes = v; }),
              contador('Com água', d.recipientes_agua, v => { d.recipientes_agua = v; }),
              contador('Com larva', d.recipientes_larva, v => { d.recipientes_larva = v; marcarLarva(v); })]));
        };
        const tipos = h('div', { class: 'cac-tipos' });
        const desenharTipos = () => {
          tipos.replaceChildren(...d.recipientes.map(linha => {
            const info = TIPO_RECIPIENTE.get(linha.t) || { nome: 'Tipo ' + linha.t, grupo: '' };
            const mudar = chave => v => { linha[chave] = v; if (chave === 'l') marcarLarva(v); desenharTotais(); };
            return h('div', { class: 'cac-tipo' },
              h('div', { class: 'cac-tipo-topo' }, h('strong', {}, codigoDoTipo(linha.t)), h('span', {}, info.nome, info.grupo ? h('small', {}, ' · ' + info.grupo) : null),
                h('button', { type: 'button', class: 'cac-tipo-tirar', 'aria-label': 'Tirar ' + info.nome, onclick: () => { d.recipientes = d.recipientes.filter(r => r !== linha); desenharTipos(); desenharTotais(); } }, '×')),
              h('div', { class: 'cac-contadores' }, contador('Existentes', linha.e || 0, mudar('e')), contador('Com água', linha.a || 0, mudar('a')), contador('Com larva', linha.l || 0, mudar('l'))));
          }));
        };
        const escolherTipo = h('select', { class: 'cac-tipo-escolha', 'aria-label': 'Anotar tipo de recipiente' },
          h('option', { value: '' }, '＋ Anotar tipo de recipiente…'),
          GRUPOS_RECIPIENTE.map(grupo => h('optgroup', { label: `${grupo.g} · ${grupo.nome}` }, grupo.tipos.map(([numero, nome]) => h('option', { value: String(numero) }, `${numero} · ${nome}`)))));
        escolherTipo.addEventListener('change', () => {
          const t = parseInt(escolherTipo.value, 10);
          escolherTipo.value = '';
          if (!t) return;
          if (!d.recipientes.some(r => r.t === t)) d.recipientes.push({ t, e: 1, a: 0, l: 0 });
          desenharTipos(); desenharTotais();
          const linhas = tipos.querySelectorAll('.cac-tipo');
          const posicao = d.recipientes.findIndex(r => r.t === t);
          if (linhas[posicao]) linhas[posicao].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        });
        desenharTotais(); desenharTipos();
        detalhes.append(
          h('h3', {}, 'Recipientes'),
          totais, notaTotais,
          ...(GRUPOS_RECIPIENTE.length ? [h('h3', {}, 'Tipos de recipiente'), tipos, escolherTipo] : []),
          h('div', { class: 'cac-larvas' }, h('label', { for: 'cac-larvas' }, larvas, h('span', {}, '🟣 Imóvel com larva')), contador('Tubitos', d.tubitos, v => { d.tubitos = v; })),
          h('h3', {}, 'Controle feito'),
          h('div', { class: 'cac-chips' }, chip('Mecânico', 'controle_mecanico'), chip('Alternativo', 'controle_alternativo'), chip('Focal', 'tratamento_focal')));
      }
      const obs = h('textarea', { rows: '2', maxlength: '1000', placeholder: 'Observação (opcional)', 'aria-label': 'Observação' });
      obs.value = d.observacao;
      obs.addEventListener('input', () => { d.observacao = obs.value; });
      detalhes.append(obs);
    }
    for (const s of M.SITUACOES) {
      botoes.append(h('button', { type: 'button', role: 'radio', dataset: { id: s.id }, style: `--cor:${s.cor};--clara:${s.clara}`, onclick: () => { d.situacao = s.id; desenharDetalhesDaFicha(); } },
        h('span', { 'aria-hidden': 'true' }, s.icone), s.nome));
    }
    const salvar = seguir => {
      if (!d.situacao || S.fichaCasa !== casa) return;
      const atual = S.ultimas.get(casa.id);
      if ((atual ? atual.u : null) !== versaoAoAbrir) { avisar('Este imóvel recebeu outra visita enquanto a ficha estava aberta. Reabra a ficha para conferir.', 'ruim'); return; }
      let alvo = casa;
      if (nova) {
        const numero = $('cac-nova-numero').value.trim(), rua = $('cac-nova-rua').value.trim();
        if (!rua || !numero) { avisar('Informe a rua e o número do imóvel.', 'ruim'); return; }
        const ponto = S.posicao || [casa.bloco.c[1], casa.bloco.c[0]];
        alvo = { id: 'novo-' + M.uuid().replace(/[^A-Za-z0-9]/g, '').slice(0, 20), rua, n: numero.slice(0, 20), cp: $('cac-nova-complemento').value.trim().slice(0, 60), y: ponto[0], x: ponto[1], bloco: casa.bloco, extra: true };
      }
      registrar(alvo, d, seguir && !nova);
    };
    acoes.append(h('p', { class: 'cac-nota-salvar' }, 'Confira o endereço e a situação. A visita fica guardada no aparelho até o envio.'), h('button', { type: 'button', class: 'cac-botao', onclick: () => salvar(false) }, 'Salvar'),
      !nova && h('button', { type: 'button', class: 'cac-botao forte', onclick: () => salvar(true) }, 'Salvar e próxima ▶'));
    corpo.append(h('h3', {}, 'Situação do imóvel'), botoes, detalhes);
    $('cac-ficha').querySelector('.cac-folha').append(acoes);
    desenharDetalhesDaFicha();
    $('cac-ficha').hidden = false;
    document.querySelector('.cac-corpo').inert = true;
    document.querySelector('.cac-topo').inert = true;
    corpo.querySelector('button')?.focus();
  }

  function mostrarVisita(casa) {
    S.fichaSuja = false;
    $('cac-ficha').querySelector('.cac-ficha-acoes')?.remove();
    const v = S.ultimas.get(casa.id);
    $('cac-ficha-titulo').textContent = `${casa.rua}, ${casa.n}`;
    $('cac-ficha-sub').textContent = `${nomeDoBloco(casa.bloco)} · SC ${casa.bloco.s}`;
    const corpo = $('cac-ficha-corpo');
    corpo.replaceChildren(v ? resumoDaVisita(v) : h('p', { class: 'cac-ultima' }, 'Sem visita registrada no período.'));
    $('cac-ficha').hidden = false;
  }

  function resumoDaVisita(v) {
    const s = M.POR_ID[v.s];
    const linhas = [`${s.icone} ${s.nome} em ${dataBr(v.d)}${horaBr(v.h) ? ' às ' + horaBr(v.h) : ''}${v.a ? ' · ' + v.a : ''}`];
    if (M.INSPECIONADO.has(v.s)) {
      linhas.push(`Recipientes: ${v.re} existentes, ${v.ra} com água, ${v.rl} com larva`);
      if (v.rt && v.rt.length) linhas.push('Tipos: ' + v.rt.map(r => `${codigoDoTipo(r.t)} ${(TIPO_RECIPIENTE.get(r.t) || { nome: '' }).nome} ×${r.e}${r.l ? ' (' + r.l + ' com larva)' : ''}`).join('; '));
      if (v.l) linhas.push(`🟣 Imóvel com larva${v.t ? ' · ' + plural(v.t, 'tubito', 'tubitos') : ''}`);
      const controles = [v.cm && 'mecânico', v.ca && 'alternativo', v.tf && 'focal'].filter(Boolean);
      if (controles.length) linhas.push('Controle: ' + controles.join(', '));
    }
    if (v.o) linhas.push('Obs.: ' + v.o);
    return h('div', { class: 'cac-ultima' }, linhas.map(linha => h('p', {}, linha)));
  }

  // ---------------------------------------------------------------- painel
  const ABAS = {
    rua: [['missao', '🎯 Missão'], ['quarteirao', '🏘️ Quarteirão'], ['equipe', '🏆 Equipe']],
    escritorio: [['plano', '🗓️ Plano'], ['aovivo', '📡 Ao vivo'], ['quarteirao', '🏘️ Quarteirão']],
  };

  function abrirPainel(aberto) {
    S.prefs.painel = aberto;
    salvarLocal(PREFS, S.prefs);
    $('cac-painel').classList.toggle('recolhido', !aberto);
    $('cac-puxador').setAttribute('aria-expanded', String(aberto));
    setTimeout(() => S.mapa && S.mapa.invalidateSize(), 260);
  }

  function barra(pct, cor) {
    return h('div', { class: 'cac-barra', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(pct) }, h('span', { style: `width:${pct}%;${cor ? 'background:' + cor : ''}` }));
  }

  function chipsDeSituacao(porSituacao, larvas) {
    const chips = M.SITUACOES.filter(s => porSituacao[s.id]).map(s => h('span', { class: 'cac-selo', style: `--cor:${s.cor};--clara:${s.clara}` }, `${s.icone} ${s.nome} ${porSituacao[s.id]}`));
    if (larvas) chips.push(h('span', { class: 'cac-selo', style: `--cor:${M.LARVA.cor};--clara:${M.LARVA.clara}` }, `🟣 Com larva ${larvas}`));
    return h('div', { class: 'cac-selos' }, chips);
  }

  function linhaDeBloco(bloco, extra) {
    const prog = bloco.estado.prog, cores = M.BLOCOS[bloco.estado.tipo];
    return h('button', { type: 'button', class: 'cac-linha-bloco', onclick: () => { S.blocoAtivo = bloco; S.aba = 'quarteirao'; desenhar(); irParaBloco(bloco); } },
      h('span', { class: 'cac-numero', style: `background:${cores.fundo};border-color:${cores.borda}` }, bloco.n),
      h('span', { class: 'cac-linha-meio' }, h('strong', {}, `SC ${bloco.s}` + (extra ? ' · ' + extra : '')), barra(prog.pct, bloco.estado.tipo === 'concluido' ? '#2f9e44' : null)),
      h('span', { class: 'cac-linha-fim' }, bloco.estado.tipo === 'concluido' ? '🏁' : `${prog.feitas}/${prog.total}`));
  }

  function meuResumo() {
    const meu = eu() ? S.agentes.find(a => a.id === eu().id) : null;
    const minhaFila = S.fila;
    return M.comFila(meu, minhaFila, S.hoje, concluidosLocais().size);
  }

  function painelMissao() {
    const meu = eu() ? eu().id : null;
    const abertos = S.blocos.filter(b => b.estado.tipo === 'planejado' || b.estado.tipo === 'andamento');
    const concluidos = S.blocos.filter(b => b.estado.tipo === 'concluido');
    const meus = abertos.filter(b => b.estado.plano && b.estado.plano.ri === meu);
    const semDono = abertos.filter(b => b.estado.plano && !b.estado.plano.ri);
    const meusFeitos = concluidos.filter(b => b.estado.plano && (b.estado.plano.ri === meu || b.estado.plano.local));
    const missao = meus.concat(meusFeitos);
    const total = missao.reduce((soma, b) => soma + b.estado.prog.total, 0);
    const feitas = missao.reduce((soma, b) => soma + b.estado.prog.feitas, 0);
    const pct = total ? Math.round(100 * feitas / total) : 0;
    const resumo = meuResumo(), nivel = M.nivel(M.pontos(resumo));
    const visitasDeHoje = Array.from(S.ultimas.values()).filter(v => v.d === S.hoje && (v.pendente || v.ai === meu));
    const doDia = M.resumoDoDia(visitasDeHoje, S.hoje);
    const anel = h('div', { class: 'cac-anel', style: `--pct:${pct}` }, h('strong', {}, pct + '%'), h('small', {}, 'da missão'));
    return [
      h('section', { class: 'cac-cartao cac-missao' }, anel,
        h('div', {}, h('h2', {}, missao.length ? 'Missão de hoje' : 'Sem missão marcada'),
          h('p', {}, missao.length ? `${feitas} de ${plural(total, 'imóvel', 'imóveis')} · ${meusFeitos.length} de ${plural(missao.length, 'quarteirão', 'quarteirões')}` : 'Toque em um quarteirão no mapa para começar a registrar.'),
          h('p', { class: 'cac-hoje' }, `Hoje você registrou ${plural(resumo.hoje, 'imóvel', 'imóveis')}`))),
      h('section', { class: 'cac-cartao cac-nivel' },
        h('div', { class: 'cac-nivel-topo' }, h('strong', {}, `Nível ${nivel.numero} · ${nivel.titulo}`), h('span', {}, `${nivel.xp} pontos`)),
        barra(nivel.pct, '#f59f00'),
        h('small', {}, nivel.teto ? `Faltam ${nivel.teto - nivel.xp} pontos para o próximo nível` : 'Nível máximo. Lenda!'),
        h('div', { class: 'cac-medalhas' }, M.medalhas(resumo).map(m => h('span', { class: m.ganha ? 'ganha' : '', title: `${m.nome}: ${m.como}` }, m.icone)))),
      doDia.total ? h('section', { class: 'cac-cartao' }, h('h3', {}, 'Seu dia'), chipsDeSituacao(doDia.porSituacao, doDia.larvas)) : null,
      meus.length ? h('section', { class: 'cac-cartao' }, h('h3', {}, 'Seus quarteirões'), meus.map(b => linhaDeBloco(b))) : null,
      meusFeitos.length ? h('section', { class: 'cac-cartao' }, h('h3', {}, 'Concluídos hoje'), meusFeitos.map(b => linhaDeBloco(b))) : null,
      semDono.length ? h('section', { class: 'cac-cartao' }, h('h3', {}, 'No plano, sem responsável'), semDono.map(b => linhaDeBloco(b))) : null,
    ];
  }

  function painelQuarteirao() {
    const bloco = S.blocoAtivo;
    if (!bloco) return [h('section', { class: 'cac-cartao cac-vazio' }, h('p', {}, 'Toque em um quarteirão no mapa para ver as casas dele.'))];
    const prog = bloco.estado.prog, cores = M.BLOCOS[bloco.estado.tipo], plano = bloco.estado.plano;
    const casas = casasDe(bloco);
    const lista = h('div', { class: 'cac-casas' });
    let ruaAtual = null;
    for (const casa of casas) {
      const atual = S.ultimas.get(casa.id);
      if (S.filtroCasas === 'faltam' && atual && atual.d >= bloco.estado.inicio) continue;
      if (S.filtroCasas === 'retorno' && (!atual || !M.PENDENCIA.has(atual.s))) continue;
      if (casa.rua !== ruaAtual) { ruaAtual = casa.rua; lista.append(h('h4', {}, casa.rua)); }
      const visita = S.ultimas.get(casa.id), cor = M.corDaCasa(visita, bloco.estado.inicio);
      const s = visita ? M.POR_ID[visita.s] : null;
      const texto = !visita ? 'toque para registrar'
        : `${s.icone} ${s.nome}${visita.l ? ' · com larva' : ''} · ${visita.d === S.hoje ? horaBr(visita.h) : dataBr(visita.d)}${visita.a ? ' · ' + primeiroNome(visita.a) : ''}${visita.pendente ? ' · a enviar' : ''}`;
      lista.append(h('button', { type: 'button', class: 'cac-linha-casa' + (cor.apagada ? ' apagada' : ''), onclick: () => { S.mapa.setView([casa.y, casa.x], Math.max(S.mapa.getZoom(), 18.5)); abrirCasa(casa); } },
        h('span', { class: 'cac-casa-num', style: `background:${cor.fundo};color:${cor.texto};border-color:${cor.cor}` }, casa.n),
        h('span', { class: 'cac-linha-meio' }, casa.cp ? h('small', {}, casa.cp) : null, h('span', {}, texto))));
    }
    const rua = S.prefs.modo === 'rua';
    return [
      h('section', { class: 'cac-cartao' },
        h('div', { class: 'cac-bloco-topo' }, h('span', { class: 'cac-numero grande', style: `background:${cores.fundo};border-color:${cores.borda}` }, bloco.n),
          h('div', {}, h('h2', {}, nomeDoBloco(bloco)), h('p', {}, `SC ${bloco.s}${bloco.d ? ' · ' + bloco.d : ''} · ${plural(prog.total, 'imóvel', 'imóveis')}`))),
        h('p', { class: 'cac-estado', style: `background:${cores.fundo};border-color:${cores.borda}` }, descricaoDoEstado(bloco)),
        prog.total ? [barra(prog.pct), h('p', { class: 'cac-conta' }, `${prog.feitas} de ${prog.total} registrados (${prog.pct}%)`)] : null,
        chipsDeSituacao(prog.porSituacao, prog.larvas),
        cfg.registra ? h('div', { class: 'cac-bloco-acoes' },
          bloco.estado.tipo === 'concluido'
            ? h('button', { type: 'button', class: 'cac-botao', onclick: () => reabrirBloco(bloco) }, 'Reabrir quarteirão')
            : (bloco.estado.tipo === 'planejado' || bloco.estado.tipo === 'andamento' || prog.feitas
              ? h('button', { type: 'button', class: 'cac-botao forte', onclick: () => concluirBloco(bloco) }, 'Concluir quarteirão 🏁') : null),
          rua ? h('button', { type: 'button', class: 'cac-botao', onclick: () => abrirCasa({ id: '', rua: '', n: '', cp: '', bloco }, true) }, '＋ Imóvel que não está na lista') : null) : null,
        plano && plano.r ? h('p', { class: 'cac-conta' }, 'Responsável: ' + plano.r) : null),
      h('section', { class: 'cac-cartao' },
        h('div', { class: 'cac-bloco-acoes' },
          rua && cfg.registra && M.proximaCasa(casas, S.ultimas, bloco.estado.inicio) ? h('button', { type: 'button', class: 'cac-botao forte', onclick: () => abrirCasa(M.proximaCasa(casas, S.ultimas, bloco.estado.inicio)) }, 'Começar pela próxima casa ▶') : null,
          h('button', { type: 'button', class: 'cac-botao', onclick: () => imprimir({ bloco }) }, 'Roteiro A4')),
        h('h3', { class: 'cac-etapa' }, casas.length ? 'Casas, na ordem da volta' : 'Sem casas cadastradas neste quarteirão'),
        h('div', { class: 'cac-filtros-casas', role: 'group', 'aria-label': 'Mostrar imóveis' }, [['todas', 'Todos'], ['faltam', 'Faltam registrar'], ['retorno', 'Retornos']].map(([id, nome]) =>
          h('button', { type: 'button', 'aria-pressed': String(S.filtroCasas === id), onclick: () => { S.filtroCasas = id; desenharPainel(); } }, nome))),
        lista.children.length ? lista : h('p', { class: 'cac-vazio' }, casas.length ? 'Nenhum imóvel neste filtro.' : 'Acrescente os imóveis encontrados em campo.')),
    ];
  }

  function descricaoDoEstado(bloco) {
    const e = bloco.estado;
    if (e.tipo === 'planejado') return e.plano.d === S.hoje ? 'No plano de hoje' : `No plano desde ${dataBr(e.plano.d)}`;
    if (e.tipo === 'andamento') return 'Em andamento';
    if (e.tipo === 'concluido') return 'Concluído hoje' + (e.plano && e.plano.cp ? ' por ' + primeiroNome(e.plano.cp) : '');
    if (e.tipo === 'agendado') return 'Planejado para ' + dataBr(e.plano.d);
    if (e.ha === null) return 'Sem trabalho registrado nos últimos ' + S.base.janela_dias + ' dias';
    return e.ha === 0 ? 'Trabalhado hoje' : (e.ha === 1 ? 'Trabalhado ontem' : `Trabalhado há ${e.ha} dias`);
  }

  function painelEquipe() {
    const ativos = S.agentes.map(a => (eu() && a.id === eu().id ? meuResumo() : a)).filter(a => a.hoje || a.quarteiroes_hoje);
    if (eu() && !ativos.some(a => a.id === eu().id)) { const meu = Object.assign({ id: eu().id, nome: eu().nome }, meuResumo()); if (meu.hoje) ativos.push(meu); }
    ativos.sort((a, b) => b.hoje - a.hoje);
    const maior = Math.max(1, ...ativos.map(a => a.hoje));
    return [h('section', { class: 'cac-cartao' }, h('h2', {}, 'Equipe hoje'),
      ativos.length ? ativos.map((a, posicao) => h('div', { class: 'cac-placar' + (eu() && a.id === eu().id ? ' eu' : '') },
        h('span', { class: 'cac-posicao' }, ['🥇', '🥈', '🥉'][posicao] || String(posicao + 1)),
        h('div', { class: 'cac-linha-meio' }, h('strong', {}, a.nome || (eu() && eu().nome) || 'Sem nome'), barra(Math.round(100 * a.hoje / maior))),
        h('span', { class: 'cac-linha-fim' }, plural(a.hoje, 'imóvel', 'imóveis'), a.quarteiroes_hoje ? h('small', {}, ` · ${a.quarteiroes_hoje} 🏁`) : null)))
        : h('p', { class: 'cac-vazio' }, 'Ninguém registrou imóvel hoje ainda. A primeira casa abre o placar!'))];
  }

  function painelPlano() { return planejamento.painel(); }

  function painelAoVivo() {
    const visitas = Array.from(S.doDia.values()).concat(S.fila.filter(v => v.data === S.hoje).map(v => M.comoRegistro(v, eu())));
    const doDia = M.resumoDoDia(visitas, S.hoje);
    const abertos = S.blocos.filter(b => b.estado.tipo === 'planejado' || b.estado.tipo === 'andamento');
    const concluidos = S.blocos.filter(b => b.estado.tipo === 'concluido');
    const numero = (valor, rotulo, cor) => h('div', { class: 'cac-kpi' }, h('strong', { style: cor ? 'color:' + cor : null }, String(valor)), h('span', {}, rotulo));
    const feed = visitas.sort((a, b) => Date.parse(b.h || '') - Date.parse(a.h || '')).slice(0, 14);
    return [
      h('section', { class: 'cac-cartao' }, h('h2', {}, S.aoVivo ? 'Ao vivo' : 'Última atualização recebida'),
        h('div', { class: 'cac-kpis' }, numero(doDia.total, 'imóveis hoje'), numero(doDia.porSituacao.TRABALHADO || 0, 'trabalhados', '#2f9e44'),
          numero(doDia.pendencias, 'pendências', '#e8590c'), numero(doDia.larvas, 'com larva', M.LARVA.cor),
          numero(concluidos.length, 'quarteirões concluídos', '#2f9e44'), numero(abertos.length, 'em aberto', '#1c7ed6'))),
      abertos.length ? h('section', { class: 'cac-cartao' }, h('h3', {}, 'Em aberto'), abertos.sort((a, b) => b.estado.prog.pct - a.estado.prog.pct).map(b => linhaDeBloco(b, b.estado.plano && b.estado.plano.r ? primeiroNome(b.estado.plano.r) : ''))) : null,
      painelEquipe(),
      h('section', { class: 'cac-cartao' }, h('h3', {}, 'Últimos registros'),
        feed.length ? feed.map(v => { const s = M.POR_ID[v.s], bloco = S.porId.get(v.b); return h('button', { type: 'button', class: 'cac-feed', onclick: () => { if (bloco) { S.blocoAtivo = bloco; S.aba = 'quarteirao'; desenhar(); irParaBloco(bloco); } } },
          h('time', {}, horaBr(v.h)), h('span', {}, `${s.icone} ${v.lg || 'Imóvel'}, ${v.n || 's/n'}${v.l ? ' · 🟣 larva' : ''}`), h('small', {}, `${primeiroNome(v.a)} · Q ${bloco ? bloco.n : '?'}`)); })
          : h('p', { class: 'cac-vazio' }, 'Os registros da equipe aparecem aqui assim que chegarem.')),
    ];
  }

  function desenharPainel() {
    const foco = document.activeElement;
    const rotuloFoco = $('cac-conteudo').contains(foco) && ['INPUT', 'SELECT'].includes(foco.tagName) ? foco.getAttribute('aria-label') : null;
    const cursor = rotuloFoco && foco.type === 'search' ? foco.selectionStart : null;
    const rolagemCatalogo = $('cac-conteudo').querySelector('.cac-catalogo')?.scrollTop || 0;
    const abas = ABAS[S.prefs.modo];
    if (!abas.some(([id]) => id === S.aba)) S.aba = abas[0][0];
    $('cac-abas').replaceChildren(...abas.map(([id, rotulo]) => h('button', { type: 'button', role: 'tab', 'aria-selected': String(id === S.aba), onclick: () => { S.aba = id; abrirPainel(true); desenharPainel(); } }, rotulo)));
    const conteudo = { missao: painelMissao, quarteirao: painelQuarteirao, equipe: painelEquipe, plano: painelPlano, aovivo: painelAoVivo }[S.aba]();
    const rolagem = $('cac-conteudo').scrollTop;
    $('cac-conteudo').replaceChildren(...[conteudo].flat(3).filter(Boolean));
    $('cac-conteudo').scrollTop = S.abaDesenhada === S.aba + (S.blocoAtivo ? S.blocoAtivo.id : '') ? rolagem : 0;
    S.abaDesenhada = S.aba + (S.blocoAtivo ? S.blocoAtivo.id : '');
    const catalogo = $('cac-conteudo').querySelector('.cac-catalogo');
    if (catalogo) catalogo.scrollTop = rolagemCatalogo;
    if (rotuloFoco) {
      const campo = Array.from($('cac-conteudo').querySelectorAll('input,select')).find(el => el.getAttribute('aria-label') === rotuloFoco);
      if (campo) { campo.focus({ preventScroll: true }); if (cursor !== null) campo.setSelectionRange(cursor, cursor); }
    }
  }

  function desenharConexao() {
    const botao = $('cac-conexao'), pendentes = S.fila.length + S.acoes.length;
    let texto, classe;
    if (S.precisaEntrar) { texto = '🔑 Entrar de novo'; classe = 'alerta'; }
    else if (S.enviando) { texto = '⬆️ Enviando…'; classe = 'envio'; }
    else if (!navigator.onLine || !S.aoVivo) { texto = `🟠 Sem internet${pendentes ? ' · ' + pendentes + ' guardada' + (pendentes === 1 ? '' : 's') : ''}`; classe = 'fora'; }
    else if (pendentes) { texto = `⬆️ ${pendentes} a enviar`; classe = 'envio'; }
    else { texto = '🟢 Ao vivo'; classe = 'vivo'; }
    botao.textContent = texto;
    botao.className = 'cac-conexao ' + classe;
    const faixa = $('cac-faixa');
    const avisos = [];
    if (S.precisaEntrar) avisos.push(h('p', {}, `Sua sessão terminou. ${pendentes ? plural(pendentes, 'registro continua guardado', 'registros continuam guardados') + ' neste aparelho. ' : ''}`, cfg.urls.entrar ? h('a', { href: cfg.urls.entrar }, 'Entrar de novo') : null));
    if (S.recusadas.length) avisos.push(h('p', {}, `${plural(S.recusadas.length, 'registro não foi aceito', 'registros não foram aceitos')} pelo servidor (${S.recusadas[0].motivo}). `, h('button', { type: 'button', onclick: () => { S.recusadas = []; salvarLocal(RECUSADAS, []); desenharConexao(); } }, 'Entendi')));
    faixa.replaceChildren(...avisos);
    faixa.hidden = !avisos.length;
  }

  function desenharLegenda() {
    if (S.prefs.modo === 'escritorio') {
      $('cac-legenda-itens').replaceChildren(h('h4', {}, 'Plano de ' + dataBr(S.diaPlano || S.hoje)),
        ...(cfg.equipe || []).map(p => h('span', {}, h('i', { style: `background:${corDoAgente(p.id)};border-color:${corDoAgente(p.id)}` }), p.nome)),
        h('span', {}, h('i', { style: 'background:#495057;border-color:#495057' }), 'Sem responsável'),
        h('span', {}, h('i', { style: 'background:#fff;border-color:#adb5bd' }), 'Livre nesta data'),
        h('span', {}, h('i', { style: 'background:#b2f2e5;border-color:#0b6568;border-style:dashed' }), 'Selecionado · ainda não salvo'));
      return;
    }
    const itens = Object.entries(M.BLOCOS).map(([, c]) => h('span', {}, h('i', { style: `background:${c.fundo};border-color:${c.borda}` }), c.nome));
    const casas = M.SITUACOES.map(s => h('span', {}, h('i', { class: 'redondo', style: `background:${s.cor};border-color:${s.cor}` }), s.nome));
    casas.push(h('span', {}, h('i', { class: 'redondo', style: `background:${M.LARVA.cor};border-color:${M.LARVA.cor}` }), 'Com larva'));
    $('cac-legenda-itens').replaceChildren(h('h4', {}, 'Quarteirões'), ...itens, h('h4', {}, 'Casas'), ...casas);
  }

  function desenhar() {
    if (!document.getElementById('cac-print-preview').open) $('cac-impressao').replaceChildren();
    document.body.dataset.modo = S.prefs.modo;
    document.querySelectorAll('.cac-modos button').forEach(botao => botao.setAttribute('aria-pressed', String(botao.dataset.modo === S.prefs.modo)));
    desenharMapa();
    desenharPainel();
    desenharConexao();
    desenharLegenda();
    $('cac-conferir').hidden = S.prefs.modo !== 'escritorio' || !S.selecionados.size;
    $('cac-conferir').textContent = `${S.selecionados.size} selecionado${S.selecionados.size === 1 ? '' : 's'} · Conferir e salvar`;
  }

  // ---------------------------------------------------------------- menu, impressão, sem internet
  // Tudo o que a página carrega do próprio site: sem isso guardado, ela não abre sem internet.
  const arquivosDaTela = () => Array.from(document.querySelectorAll('script[src], link[rel="stylesheet"]'))
    .map(no => no.src || no.href).filter(url => url.startsWith(location.origin));

  async function prontoParaOffline() {
    try {
      if (!('caches' in window) || !navigator.serviceWorker) return false;
      const registro = await navigator.serviceWorker.getRegistration();
      if (!registro || !registro.active) return false;
      const cache = await caches.open(CACHE_APP);
      for (const url of arquivosDaTela()) if (!(await cache.match(url))) return false;
      return Boolean(await cache.match(location.pathname, { ignoreSearch: true, ignoreVary: true })) && Boolean(await lerCache('base'));
    } catch (e) { return false; }
  }

  async function prepararOffline(avisarResultado) {
    if (!('caches' in window) || !cfg.registra || location.search.includes('token=')) return false;
    try {
      const cache = await caches.open(CACHE_APP);
      const arquivos = arquivosDaTela();
      await Promise.all(arquivos.map(async url => { if (!(await cache.match(url))) await cache.add(url); }));
      // Versões antigas dos arquivos saem, para o aparelho não acumular a cada atualização do site.
      for (const guardado of await cache.keys()) {
        if (new URL(guardado.url).pathname.startsWith('/static/') && !arquivos.includes(guardado.url)) await cache.delete(guardado);
      }
      const pagina = await fetch(location.pathname, { credentials: 'same-origin' });
      if (pagina.ok && !pagina.redirected) await cache.put(location.pathname, pagina);
      S.pronto = await prontoParaOffline();
      if (avisarResultado) avisar(S.pronto ? 'Pronto: este aparelho abre o Casa a Casa mesmo sem internet ✔' : 'Quase lá: recarregue a página uma vez com internet para terminar.', S.pronto ? 'bom' : null);
      return S.pronto;
    } catch (e) {
      if (avisarResultado) avisar('Não deu para guardar agora. Tente de novo com internet.', 'ruim');
      return false;
    }
  }

  function abrirMenu() {
    const menu = $('cac-menu'), pendentes = S.fila.length + S.acoes.length;
    const item = (rotulo, acao, desligado) => h('button', { type: 'button', role: 'menuitem', disabled: desligado, onclick: () => { fecharMenu(); acao(); } }, rotulo);
    const baixar = (url, inicio) => () => { location.href = url + (url.includes('?') ? '&' : '?') + 'inicio=' + inicio + '&fim=' + S.hoje; };
    menu.replaceChildren(
      h('p', { class: 'cac-menu-nota' }, cfg.usuario ? cfg.usuario.nome : 'Somente leitura'),
      h('p', { class: 'cac-menu-nota' }, S.pronto ? '✅ Pronto para funcionar sem internet' : '⚠️ Ainda não preparado para funcionar sem internet'),
      cfg.registra ? item(S.pronto ? '🔄 Atualizar o que fica guardado no aparelho' : '📥 Preparar para usar sem internet', () => prepararOffline(true)) : null,
      cfg.registra ? item(`⬆️ Enviar agora${pendentes ? ' (' + pendentes + ')' : ''}`, () => { if (!navigator.onLine) avisar('Sem internet agora. Os registros continuam guardados.'); ciclo(); }, !pendentes) : null,
      item('🖨️ Imprimir mapa e plano', imprimir),
      item('📄 Boletim de hoje (CSV)', baixar(cfg.urls.boletim_csv, S.hoje)),
      item('📄 Boletim dos últimos 30 dias (CSV)', baixar(cfg.urls.boletim_csv, somarDias(S.hoje, -30))),
      item('📄 Visitas dos últimos 30 dias (CSV)', baixar(cfg.urls.visitas_csv, somarDias(S.hoje, -30))),
      cfg.urls.recipientes_csv ? item('📄 Recipientes por tipo, últimos 30 dias (CSV)', baixar(cfg.urls.recipientes_csv, somarDias(S.hoje, -30))) : null,
      item('↩ Painel do território', () => { location.href = cfg.urls.painel; }),
      cfg.registra ? item('🧹 Limpar o que está guardado neste aparelho', limparAparelho, pendentes > 0) : null);
    menu.hidden = false;
    $('cac-menu-abrir').setAttribute('aria-expanded', 'true');
  }
  function fecharMenu() { $('cac-menu').hidden = true; $('cac-menu-abrir').setAttribute('aria-expanded', 'false'); }

  async function limparAparelho() {
    if (!window.confirm('Apagar os dados do Casa a Casa guardados neste aparelho? Nada é apagado do servidor.')) return;
    try { await caches.delete(CACHE_DADOS); await caches.delete(CACHE_APP); } catch (e) { /* sem Cache Storage */ }
    [FILA, ACOES, RECUSADAS, PREFS].forEach(chave => localStorage.removeItem(chave));
    location.reload();
  }

  function imprimir(opcoes = {}) { impressao.abrir(opcoes); }

  // ---------------------------------------------------------------- início
  function ligarTela() {
    document.querySelectorAll('.cac-modos button').forEach(botao => botao.addEventListener('click', () => {
      if (botao.dataset.modo === 'rua' && !cfg.registra) { avisar('O modo Rua é para contas da equipe.'); return; }
      S.prefs.modo = botao.dataset.modo;
      S.aba = null;
      salvarLocal(PREFS, S.prefs);
      desenhar();
    }));
    $('cac-puxador').addEventListener('click', () => abrirPainel(!S.prefs.painel));
    $('cac-conexao').addEventListener('click', () => { if (S.precisaEntrar && cfg.urls.entrar) location.href = cfg.urls.entrar; else ciclo(); });
    $('cac-menu-abrir').addEventListener('click', evento => { evento.stopPropagation(); if ($('cac-menu').hidden) abrirMenu(); else fecharMenu(); });
    document.addEventListener('click', evento => { if (!$('cac-menu').hidden && !$('cac-menu').contains(evento.target)) fecharMenu(); });
    $('cac-ficha-fechar').addEventListener('click', fecharFicha);
    $('cac-ficha-corpo').addEventListener('input', () => { S.fichaSuja = true; });
    $('cac-ficha-corpo').addEventListener('change', () => { S.fichaSuja = true; });
    $('cac-ficha-corpo').addEventListener('click', evento => { if (evento.target.closest('.cac-situacoes button, .cac-contador button, .cac-tipo-tirar')) S.fichaSuja = true; });
    $('cac-ficha').addEventListener('click', evento => { if (evento.target === $('cac-ficha')) fecharFicha(); });
    document.addEventListener('keydown', evento => {
      if (evento.key === 'Escape' && !$('cac-ficha').hidden) { evento.preventDefault(); fecharFicha(); }
      if (evento.key === 'Escape') fecharMenu();
      if (evento.key === 'Tab' && !$('cac-ficha').hidden) {
        const alvos = Array.from($('cac-ficha').querySelectorAll('button, input, select, textarea')).filter(el => !el.disabled && el.offsetParent !== null);
        const primeiro = alvos[0], ultimo = alvos.at(-1);
        if (evento.shiftKey && document.activeElement === primeiro) { evento.preventDefault(); ultimo?.focus(); }
        else if (!evento.shiftKey && document.activeElement === ultimo) { evento.preventDefault(); primeiro?.focus(); }
      }
    });
    $('cac-onde').addEventListener('click', ondeEstou);
    $('cac-ruas').addEventListener('click', alternarRuas);
    $('cac-cidade').addEventListener('click', verCidade);
    $('cac-conferir').addEventListener('click', () => { S.aba = 'plano'; abrirPainel(true); desenharPainel(); $('cac-conteudo').querySelector('.cac-revisao')?.scrollIntoView({ block: 'start', behavior: 'smooth' }); });
    window.addEventListener('online', ciclo);
    window.addEventListener('offline', () => { S.aoVivo = false; desenharConexao(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) ciclo(); });
    window.addEventListener('resize', () => S.mapa && S.mapa.invalidateSize());
    window.addEventListener('beforeprint', () => impressao.preparar());
  }

  async function iniciar() {
    ligarTela();
    iniciarMapa();
    desenharLegenda();
    abrirPainel(S.prefs.painel !== false);
    $('cac-conteudo').replaceChildren(h('section', { class: 'cac-cartao cac-vazio' }, h('p', {}, 'Abrindo o mapa…')));
    const [base, guardado] = await Promise.all([carregarBase(), lerCache('estado')]);
    if (!base) {
      $('cac-conteudo').replaceChildren(h('section', { class: 'cac-cartao cac-vazio' }, h('p', {}, 'Para abrir pela primeira vez neste aparelho é preciso internet. Conecte e recarregue a página.')));
      desenharConexao();
      S.relogio = setTimeout(() => location.reload(), 20000);
      return;
    }
    prepararBase(base);
    if (guardado) aplicarEstado(Object.assign({ parcial: false }, guardado, { hoje: guardado.hoje === S.hoje ? guardado.hoje : S.hoje, csrf: null }));
    S.completo = false;      // o que veio do aparelho serve para abrir; a primeira resposta do servidor traz tudo
    montarQuarteiroes();
    recalcular();
    if (S.prefs.vista) S.mapa.setView([S.prefs.vista[0], S.prefs.vista[1]], S.prefs.vista[2]); else verCidade();
    aplicarRuas();
    desenhar();
    await ciclo();
    if (navigator.serviceWorker && cfg.urls.sw) {
      try { await navigator.serviceWorker.register(cfg.urls.sw); } catch (e) { /* sem service worker: funciona, mas só com internet */ }
    }
    if (navigator.onLine) await prepararOffline(false);
    S.pronto = await prontoParaOffline();
  }

  const planejamento = window.CasaACasaPlanejamento({ S, cfg, h, casasDe, dataBr, somarDias, corDoAgente,
    desenhar, desenharPainel, selecionarBloco, aplicarSelecao, reagendarBloco, removerDoPlano, irParaBloco, imprimir });
  const impressao = window.CasaACasaImpressao({ S, h, casasDe, dataBr });
  window.CasaACasa = { estado: S };
  iniciar();
})();
