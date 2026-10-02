/*
 * Rotas de campo no navegador, sobre a malha de ruas do OpenStreetMap que o atlas já tem.
 * Nada é enviado a serviço externo de rotas: pontos de pacientes e endereços ficam no aparelho.
 *
 * Funções puras (sem DOM, sem Leaflet), para testar em Node.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SfaAtlasRouteModel = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const MICRO = 1e6, EARTH = 6371008.8, RAD = Math.PI / 180;
  const CELL = 0.0015;               // ~165 m: tamanho da grade usada para achar a rua mais próxima
  const USABLE_MIN = 200;            // ilhas de ruas menores que isso não servem de destino de rota
  const SPEEDS = {foot: 4.5, motor: 22};   // km/h médios no tráfego urbano de uma cidade pequena
  const EXACT_LIMIT = 12;            // até aqui a melhor ordem é calculada de forma exata

  function distance(lat1, lng1, lat2, lng2) {
    const dLat = (lat2 - lat1) * RAD, dLng = (lng2 - lng1) * RAD;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(dLng / 2) ** 2;
    return 2 * EARTH * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  // ---- Grafo ---------------------------------------------------------------
  function createGraph(payload) {
    const n = payload.nodes.length / 2, m = payload.edges.length / 2;
    const lng = new Float64Array(n), lat = new Float64Array(n);
    for (let i = 0; i < n; i++) { lng[i] = payload.nodes[2 * i] / MICRO; lat[i] = payload.nodes[2 * i + 1] / MICRO; }
    const start = new Uint32Array(n + 1);
    for (let e = 0; e < m; e++) { start[payload.edges[2 * e] + 1]++; start[payload.edges[2 * e + 1] + 1]++; }
    for (let i = 0; i < n; i++) start[i + 1] += start[i];
    const to = new Uint32Array(2 * m), w = new Float32Array(2 * m), fill = start.slice(0, n);
    const named = payload.names || [], label = new Int32Array(2 * m).fill(-1);   // nome da rua de cada trecho
    for (let e = 0; e < m; e++) {
      const a = payload.edges[2 * e], b = payload.edges[2 * e + 1];
      const d = distance(lat[a], lng[a], lat[b], lng[b]);
      const nameId = payload.en && payload.en[e] !== undefined ? payload.en[e] : -1;
      to[fill[a]] = b; label[fill[a]] = nameId; w[fill[a]++] = d;
      to[fill[b]] = a; label[fill[b]] = nameId; w[fill[b]++] = d;
    }
    // Componentes conexos: ruas que não se ligam à malha principal não podem ser destino de rota.
    const comp = new Int32Array(n).fill(-1), sizes = [], stack = [];
    for (let s = 0; s < n; s++) {
      if (comp[s] >= 0) continue;
      const id = sizes.length;
      let size = 0;
      comp[s] = id; stack.push(s);
      while (stack.length) {
        const u = stack.pop();
        size++;
        for (let k = start[u]; k < start[u + 1]; k++) {
          if (comp[to[k]] < 0) { comp[to[k]] = id; stack.push(to[k]); }
        }
      }
      sizes.push(size);
    }
    const grid = new Map();
    for (let i = 0; i < n; i++) {
      const key = cellKey(lng[i], lat[i]);
      const bucket = grid.get(key);
      if (bucket) bucket.push(i); else grid.set(key, [i]);
    }
    const largest = Math.max(0, ...sizes);
    return {n, m, lng, lat, start, to, w, comp, sizes, grid, names: named, label, usable: Math.min(USABLE_MIN, largest)};
  }

  // Nome da rua do trecho entre dois pontos ligados ('' quando não há nome).
  function edgeName(graph, u, v) {
    for (let k = graph.start[u]; k < graph.start[u + 1]; k++) {
      if (graph.to[k] === v) return graph.label[k] >= 0 ? (graph.names[graph.label[k]] || '') : '';
    }
    return '';
  }
  const degree = (graph, u) => graph.start[u + 1] - graph.start[u];

  function cellKey(lng, lat) {
    return Math.floor((lng + 180) / CELL) * 1000003 + Math.floor((lat + 90) / CELL);
  }

  // Ponto da rua mais próximo. Prefere a malha principal; sem ela por perto, aceita qualquer rua.
  function nearest(graph, lng, lat, maxMeters) {
    const limit = maxMeters || 800;
    const minCell = CELL * 111320 * Math.min(1, Math.cos(lat * RAD));
    const rings = Math.ceil(limit / minCell) + 1;
    const cx = Math.floor((lng + 180) / CELL), cy = Math.floor((lat + 90) / CELL);
    let best = null, fallback = null;
    for (let r = 0; r <= rings; r++) {
      for (let dx = -r; dx <= r; dx++) {
        for (let dy = -r; dy <= r; dy++) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
          const bucket = graph.grid.get((cx + dx) * 1000003 + (cy + dy));
          if (!bucket) continue;
          for (const i of bucket) {
            const d = distance(lat, lng, graph.lat[i], graph.lng[i]);
            if (graph.sizes[graph.comp[i]] >= graph.usable) { if (!best || d < best.distance) best = {node: i, distance: d}; }
            else if (!fallback || d < fallback.distance) fallback = {node: i, distance: d};
          }
        }
      }
      // Os anéis seguintes estão pelo menos a r células de distância.
      if (best && best.distance <= r * minCell) break;
    }
    if (best && best.distance <= limit) return best;
    return fallback && fallback.distance <= limit ? fallback : (best && best.distance <= limit * 3 ? best : null);
  }

  // ---- Caminho mais curto (Dijkstra com heap binário) -------------------------------
  function shortest(graph, source, targets) {
    const dist = new Float64Array(graph.n).fill(Infinity), prev = new Int32Array(graph.n).fill(-1);
    const heapNode = [], heapCost = [];
    const push = (node, cost) => {
      let i = heapNode.length;
      heapNode.push(node); heapCost.push(cost);
      while (i > 0) {
        const p = (i - 1) >> 1;
        if (heapCost[p] <= cost) break;
        heapNode[i] = heapNode[p]; heapCost[i] = heapCost[p]; i = p;
      }
      heapNode[i] = node; heapCost[i] = cost;
    };
    const pop = () => {
      const node = heapNode[0], last = heapNode.pop(), lastCost = heapCost.pop();
      if (heapNode.length) {
        let i = 0;
        for (;;) {
          let c = 2 * i + 1;
          if (c >= heapNode.length) break;
          if (c + 1 < heapNode.length && heapCost[c + 1] < heapCost[c]) c++;
          if (heapCost[c] >= lastCost) break;
          heapNode[i] = heapNode[c]; heapCost[i] = heapCost[c]; i = c;
        }
        heapNode[i] = last; heapCost[i] = lastCost;
      }
      return node;
    };
    const pending = targets ? new Set(targets) : null;
    dist[source] = 0; push(source, 0);
    const done = new Uint8Array(graph.n);
    while (heapNode.length) {
      const u = pop();
      if (done[u]) continue;
      done[u] = 1;
      if (pending) { pending.delete(u); if (!pending.size) break; }
      for (let k = graph.start[u]; k < graph.start[u + 1]; k++) {
        const v = graph.to[k], nd = dist[u] + graph.w[k];
        if (nd < dist[v]) { dist[v] = nd; prev[v] = u; push(v, nd); }
      }
    }
    return {dist, prev};
  }

  function pathNodes(prev, source, target) {
    const out = [];
    for (let at = target; at !== -1; at = prev[at]) { out.push(at); if (at === source) break; }
    return out.reverse();
  }

  // ---- Rota entre paradas --------------------------------------------------------
  /* stops: [{lng, lat}, ...]. Devolve trechos com distância (m), caminho [[lat,lng]...] e se
   * seguiram ruas (connected) ou ficaram em linha reta por falta de ligação na malha. */
  function plan(graph, stops) {
    const snaps = stops.map(s => nearest(graph, s.lng, s.lat));
    const legs = [];
    for (let i = 0; i + 1 < stops.length; i++) {
      const a = stops[i], b = stops[i + 1], sa = snaps[i], sb = snaps[i + 1];
      let leg = null;
      if (sa && sb) {
        const result = shortest(graph, sa.node, [sb.node]);
        if (Number.isFinite(result.dist[sb.node])) {
          const nodes = pathNodes(result.prev, sa.node, sb.node);
          const path = [[a.lat, a.lng], ...nodes.map(k => [graph.lat[k], graph.lng[k]]), [b.lat, b.lng]];
          leg = {distance: sa.distance + result.dist[sb.node] + sb.distance, path, nodes, connected: true};
        }
      }
      if (!leg) {
        leg = {distance: distance(a.lat, a.lng, b.lat, b.lng), path: [[a.lat, a.lng], [b.lat, b.lng]], connected: false};
      }
      legs.push({from: i, to: i + 1, ...leg});
    }
    return {legs, total: legs.reduce((s, l) => s + l.distance, 0), connected: legs.every(l => l.connected)};
  }

  // ---- Melhor ordem das paradas ------------------------------------------------
  function matrix(graph, stops) {
    const snaps = stops.map(s => nearest(graph, s.lng, s.lat));
    const n = stops.length, D = Array.from({length: n}, () => new Float64Array(n));
    for (let i = 0; i < n; i++) {
      const targets = snaps.filter((s, j) => j !== i && s).map(s => s.node);
      const result = snaps[i] && targets.length ? shortest(graph, snaps[i].node, targets) : null;
      for (let j = 0; j < n; j++) {
        if (i === j) continue;
        const straight = distance(stops[i].lat, stops[i].lng, stops[j].lat, stops[j].lng);
        const through = result && snaps[j] ? result.dist[snaps[j].node] : Infinity;
        // Sem ligação na malha, a linha reta com folga: continua comparável, mas é evitada.
        D[i][j] = Number.isFinite(through) ? snaps[i].distance + through + snaps[j].distance : straight * 3;
      }
    }
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) { const d = Math.min(D[i][j], D[j][i]); D[i][j] = D[j][i] = d; }
    return D;
  }

  const pathCost = (D, order) => order.slice(1).reduce((s, v, i) => s + D[order[i]][v], 0);

  function exactOrder(D) {
    const k = D.length - 1;                      // paradas livres: 1..k (a 0 é a partida)
    const full = 1 << k, cost = Array.from({length: full}, () => new Float64Array(k).fill(Infinity));
    const from = Array.from({length: full}, () => new Int8Array(k).fill(-1));
    for (let j = 0; j < k; j++) cost[1 << j][j] = D[0][j + 1];
    for (let mask = 1; mask < full; mask++) {
      for (let j = 0; j < k; j++) {
        if (!(mask & (1 << j)) || !Number.isFinite(cost[mask][j])) continue;
        for (let t = 0; t < k; t++) {
          if (mask & (1 << t)) continue;
          const next = mask | (1 << t), c = cost[mask][j] + D[j + 1][t + 1];
          if (c < cost[next][t]) { cost[next][t] = c; from[next][t] = j; }
        }
      }
    }
    let last = 0;
    for (let j = 1; j < k; j++) if (cost[full - 1][j] < cost[full - 1][last]) last = j;
    const order = [];
    for (let mask = full - 1, j = last; j !== -1;) { order.push(j + 1); const p = from[mask][j]; mask ^= 1 << j; j = p; }
    return [0, ...order.reverse()];
  }

  function heuristicOrder(D) {
    const n = D.length, order = [0], left = new Set(Array.from({length: n - 1}, (_, i) => i + 1));
    while (left.size) {
      const at = order[order.length - 1];
      let pick = -1;
      for (const j of left) if (pick < 0 || D[at][j] < D[at][pick]) pick = j;
      order.push(pick); left.delete(pick);
    }
    for (let improved = true; improved;) {       // 2-opt para caminho aberto com partida fixa
      improved = false;
      for (let i = 1; i < n - 1; i++) {
        for (let j = i + 1; j < n; j++) {
          const before = D[order[i - 1]][order[i]] + (j + 1 < n ? D[order[j]][order[j + 1]] : 0);
          const after = D[order[i - 1]][order[j]] + (j + 1 < n ? D[order[i]][order[j + 1]] : 0);
          if (after + 1e-6 < before) { order.splice(i, j - i + 1, ...order.slice(i, j + 1).reverse()); improved = true; }
        }
      }
    }
    return order;
  }

  /* Reordena as paradas a partir da primeira (partida fixa) para o menor percurso pelas ruas.
   * Devolve {order, before, after}: `order` são os índices originais na nova sequência. */
  function optimizeOrder(graph, stops) {
    const n = stops.length;
    if (n < 3) return {order: stops.map((_, i) => i), before: 0, after: 0, exact: true};
    const D = matrix(graph, stops), identity = stops.map((_, i) => i);
    const exact = n - 1 <= EXACT_LIMIT, order = exact ? exactOrder(D) : heuristicOrder(D);
    const before = pathCost(D, identity), after = pathCost(D, order);
    return after <= before ? {order, before, after, exact} : {order: identity, before, after: before, exact};
  }

  // ---- Apresentação -----------------------------------------------------------
  const minutes = (meters, mode) => meters / 1000 / (SPEEDS[mode] || SPEEDS.foot) * 60;
  function formatDistance(meters) {
    return meters < 950 ? Math.round(meters / 10) * 10 + ' m' : (meters / 1000).toFixed(1).replace('.', ',') + ' km';
  }
  function formatDuration(min) {
    const total = Math.max(1, Math.round(min));
    return total < 60 ? total + ' min' : Math.floor(total / 60) + ' h ' + String(total % 60).padStart(2, '0');
  }

  /* Links de navegação no Google Maps (o aparelho abre o app). Só coordenadas, e só quando a
   * pessoa toca: nada sai da página antes disso. Até 10 pontos por link, em blocos encadeados. */
  function googleMapsLinks(stops, mode) {
    const travel = mode === 'motor' ? 'driving' : 'walking', size = 10, links = [];
    for (let at = 0; at + 1 < stops.length; at += size - 1) {
      const part = stops.slice(at, at + size), pt = s => s.lat.toFixed(6) + ',' + s.lng.toFixed(6);
      const params = new URLSearchParams({api: '1', origin: pt(part[0]), destination: pt(part[part.length - 1]), travelmode: travel});
      if (part.length > 2) params.set('waypoints', part.slice(1, -1).map(pt).join('|'));
      links.push({from: at + 1, to: at + part.length, url: 'https://www.google.com/maps/dir/?' + params});
    }
    return links;
  }

  return {distance, createGraph, nearest, shortest, plan, optimizeOrder, matrix, minutes, formatDistance,
          formatDuration, googleMapsLinks, edgeName, degree, SPEEDS, EXACT_LIMIT};
});
