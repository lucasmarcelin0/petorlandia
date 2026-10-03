/*
 * Navegação de campo (estilo Waze/Google Maps): funções puras, sem DOM e sem Leaflet.
 * Parte de uma rota já calculada por sfa_atlas_route_model.js e responde: quais são as manobras,
 * onde o aparelho está sobre a rota, se saiu dela, para que lado o mapa deve girar e quando
 * falar cada instrução. Tudo local: nada é enviado a serviço externo.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./sfa_atlas_route_model.js'));
  else root.SfaAtlasNavModel = factory(root.SfaAtlasRouteModel);
})(typeof self !== 'undefined' ? self : this, function (Route) {
  'use strict';
  const RAD = Math.PI / 180, EARTH = 6371008.8;
  const LOOK = 18;            // m: janela para medir a direção antes/depois de um cruzamento (alisa as curvas)
  const EDGE_MARGIN = 20;     // m: ignora "curvas" coladas na partida ou na chegada (são o acesso à rua)
  const MERGE = 15;           // m: duas curvas mais próximas que isso viram uma só
  const ARRIVE_METERS = 25;   // m: chegou à parada
  const OFF_METERS = 40;      // m: além disso o aparelho está fora da rota
  const OFF_SECONDS = 4;      // s fora da rota antes de recalcular
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  // ---- Ângulos e geografia --------------------------------------------------------
  const norm360 = a => ((a % 360) + 360) % 360;
  /** Menor giro de `from` até `to`, em (-180, 180]; positivo = para a direita (sentido horário). */
  function diff(from, to) { const d = norm360(to - from); return d > 180 ? d - 360 : d; }
  function bearing(lat1, lng1, lat2, lng2) {
    const dLng = (lng2 - lng1) * RAD, p1 = lat1 * RAD, p2 = lat2 * RAD;
    return norm360(Math.atan2(Math.sin(dLng) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dLng)) / RAD);
  }
  function offset(lat, lng, brg, meters) {
    const d = meters / EARTH, b = brg * RAD, p1 = lat * RAD, l1 = lng * RAD;
    const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
    const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
    return {lat: p2 / RAD, lng: ((l2 / RAD + 540) % 360) - 180};
  }
  /** Suaviza o rumo em círculo: o giro sempre pelo caminho mais curto (359° → 1° não dá a volta). */
  const smoothAngle = (prev, next, alpha) => norm360(prev + alpha * diff(prev, next));
  /** Ângulo contínuo (sem salto de 360°) para a animação de rotação do mapa não girar ao contrário. */
  const unwrap = (previous, target) => previous + diff(norm360(previous), target);
  /** Rumo do movimento entre duas posições (null se andou muito pouco para ser confiável). */
  function headingFromFixes(a, b, minMeters) {
    if (!a || !b) return null;
    return Route.distance(a.lat, a.lng, b.lat, b.lng) >= (minMeters || 4) ? bearing(a.lat, a.lng, b.lat, b.lng) : null;
  }

  // ---- Rota contínua -----------------------------------------------------------------
  /**
   * Junta os trechos calculados em uma linha só, com a distância acumulada e o ponto da malha
   * (nó) de cada vértice. stops: [{name, lat, lng}]; legs: resultado de Route.plan(...).legs.
   */
  function buildRoute(graph, legs, stops) {
    const points = [], nodeAt = [], stopIndex = [];
    legs.forEach((leg, k) => {
      const nodes = leg.connected && leg.nodes ? leg.nodes : [];
      leg.path.forEach((p, j) => {
        if (k > 0 && j === 0) return;                 // o início do trecho é o fim do anterior
        points.push(p);
        nodeAt.push(j >= 1 && j <= nodes.length ? nodes[j - 1] : -1);
      });
      if (k === 0) stopIndex.push(0);
      stopIndex.push(points.length - 1);
    });
    const cum = [0];
    for (let i = 1; i < points.length; i++) cum.push(cum[i - 1] + Route.distance(points[i - 1][0], points[i - 1][1], points[i][0], points[i][1]));
    const route = {points, nodeAt, stopIndex, cum, total: cum[cum.length - 1] || 0, stops, graph};
    route.stopAlong = stopIndex.map(i => cum[i]);
    route.maneuvers = maneuvers(route);
    return route;
  }

  function indexAt(cum, along) {                      // maior i com cum[i] <= along
    let lo = 0, hi = cum.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (cum[mid] <= along) lo = mid; else hi = mid - 1; }
    return lo;
  }
  function pointAt(route, along) {
    const a = clamp(along, 0, route.total), i = Math.min(indexAt(route.cum, a), route.points.length - 2);
    if (i < 0) return {lat: route.points[0][0], lng: route.points[0][1], heading: 0, index: 0};
    const span = route.cum[i + 1] - route.cum[i], t = span > 0 ? (a - route.cum[i]) / span : 0;
    const p = route.points[i], q = route.points[i + 1];
    return {lat: p[0] + (q[0] - p[0]) * t, lng: p[1] + (q[1] - p[1]) * t, heading: bearing(p[0], p[1], q[0], q[1]), index: i};
  }
  /** Posição e rumo em `along` metros do início: serve à simulação e aos testes. */
  const walkAlong = pointAt;

  // ---- Manobras ----------------------------------------------------------------------
  function backIndex(route, i) {
    let j = i;
    while (j > 0 && route.cum[i] - route.cum[j] < LOOK) j--;
    return j;
  }
  function aheadIndex(route, i) {
    let j = i;
    while (j < route.points.length - 1 && route.cum[j] - route.cum[i] < LOOK) j++;
    return j;
  }
  function nameAhead(route, i) {                      // nome da rua logo depois do ponto i
    for (let j = i; j < Math.min(route.points.length - 1, i + 6); j++) {
      const u = route.nodeAt[j], v = route.nodeAt[j + 1];
      if (u >= 0 && v >= 0) { const name = Route.edgeName(route.graph, u, v); if (name) return name; }
    }
    return '';
  }
  function nameBefore(route, i) {
    for (let j = i; j > Math.max(0, i - 6); j--) {
      const u = route.nodeAt[j - 1], v = route.nodeAt[j];
      if (u >= 0 && v >= 0) { const name = Route.edgeName(route.graph, u, v); if (name) return name; }
    }
    return '';
  }
  function classify(angle) {
    const a = Math.abs(angle), side = angle > 0 ? 'right' : 'left';
    if (a >= 160) return 'uturn';
    if (a >= 120) return 'sharp-' + side;
    if (a >= 45) return side;
    return 'slight-' + side;
  }

  function maneuvers(route) {
    const out = [], n = route.points.length, g = route.graph;
    const start = route.points[0];
    if (n >= 2) {
      const first = route.points[Math.min(n - 1, aheadIndex(route, 0))];
      out.push({type: 'depart', along: 0, lat: start[0], lng: start[1], heading: bearing(start[0], start[1], first[0], first[1]), street: nameAhead(route, 0), angle: 0});
    }
    const turns = [];
    for (let i = 1; i < n - 1; i++) {
      const u = route.nodeAt[i];
      if (u < 0) continue;
      const along = route.cum[i];
      if (along < EDGE_MARGIN || route.total - along < EDGE_MARGIN) continue;
      if (route.stopAlong.some(s => Math.abs(s - along) < EDGE_MARGIN)) continue;
      const b = route.points[backIndex(route, i)], p = route.points[i], f = route.points[aheadIndex(route, i)];
      const angle = diff(bearing(b[0], b[1], p[0], p[1]), bearing(p[0], p[1], f[0], f[1]));
      const junction = Route.degree(g, u) >= 3;
      if (Math.abs(angle) < (junction ? 28 : 55)) continue;
      turns.push({type: classify(angle), along, lat: p[0], lng: p[1], angle, junction, street: nameAhead(route, i), from: nameBefore(route, i), index: i});
    }
    // Vértices seguidos de uma mesma curva ou cruzamento deslocado: fica o de maior giro.
    const kept = [];
    for (const t of turns) {
      const last = kept[kept.length - 1];
      if (last && t.along - last.along < MERGE) { if (Math.abs(t.angle) > Math.abs(last.angle)) kept[kept.length - 1] = t; }
      else kept.push(t);
    }
    // Curvas de estrada sem cruzamento a menos de 25 m uma da outra são a mesma curva.
    const filtered = kept.filter((t, i) => t.junction || !kept[i - 1] || t.along - kept[i - 1].along > 25);
    out.push(...filtered);
    route.stopAlong.forEach((along, k) => {
      if (k === 0) return;
      const i = route.stopIndex[k], stop = route.stops[k] || {};
      out.push({type: 'arrive', along, lat: route.points[i][0], lng: route.points[i][1], stop: k, name: stop.name || '', final: k === route.stopAlong.length - 1, angle: 0});
    });
    return out.sort((a, b) => a.along - b.along);
  }

  // ---- Onde o aparelho está sobre a rota -------------------------------------------------
  function projectOnSegment(lat0, lng0, a, b) {
    const kx = 111320 * Math.cos(lat0 * RAD), ky = 110574;
    const ax = (a[1] - lng0) * kx, ay = (a[0] - lat0) * ky, bx = (b[1] - lng0) * kx, by = (b[0] - lat0) * ky;
    const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
    const t = len2 ? clamp(-(ax * dx + ay * dy) / len2, 0, 1) : 0;
    return {t, distance: Math.hypot(ax + t * dx, ay + t * dy)};
  }
  // Custo de um candidato = distância até o traçado + penalidades que desempatam trechos que se
  // sobrepõem (rota que volta pela mesma rua, comum numa visita a um beco sem saída):
  //  - saltar à frente do progresso esperado (andando, o avanço entre leituras é pequeno);
  //  - voltar atrás do progresso;
  //  - seguir no sentido oposto ao do movimento (rumo do GPS, quando confiável);
  //  - ficar antes da última parada já alcançada (`minAlong`): proibido.
  const JUMP_FREE = 60, JUMP_COST = 0.05, BACK_FREE = 20, BACK_COST = 0.5, HEADING_FREE = 60, HEADING_COST = 30;
  function bestSegment(route, lat, lng, from, to, hint, opts) {
    const minAlong = opts && opts.minAlong, heading = opts && Number.isFinite(opts.heading) ? opts.heading : null;
    let best = null;
    for (let i = from; i <= to; i++) {
      const hit = projectOnSegment(lat, lng, route.points[i], route.points[i + 1]);
      const along = route.cum[i] + hit.t * (route.cum[i + 1] - route.cum[i]);
      if (minAlong !== undefined && minAlong !== null && along < minAlong - 10) continue;
      let cost = hit.distance;
      if (hint !== undefined && hint !== null) {
        cost += along > hint ? JUMP_COST * Math.max(0, along - hint - JUMP_FREE) : BACK_COST * Math.max(0, hint - along - BACK_FREE);
      }
      if (heading !== null) {
        const a = route.points[i], b = route.points[i + 1];
        const off = Math.abs(diff(heading, bearing(a[0], a[1], b[0], b[1])));
        if (off > HEADING_FREE) cost += HEADING_COST * (off - HEADING_FREE) / (180 - HEADING_FREE);
      }
      if (!best || cost < best.cost) best = {...hit, segment: i, cost};
    }
    return best;
  }
  /**
   * Projeta a posição (lat, lng) na rota. `hintAlong` (onde estava antes) limita a busca à
   * vizinhança do progresso e favorece a continuidade. `opts`: {minAlong, heading}: `minAlong`
   * é onde está a última parada já alcançada (não se volta para antes dela) e `heading` o rumo do
   * movimento em graus (null/ausente quando parado). Devolve {along, offRoute, segment}.
   */
  function locate(route, lat, lng, hintAlong, opts) {
    const last = route.points.length - 2;
    if (last < 0) return {along: 0, offRoute: 0, segment: 0};
    let best = null;
    if (hintAlong !== undefined && hintAlong !== null) {
      const from = indexAt(route.cum, Math.max(0, hintAlong - 40)), to = Math.min(last, indexAt(route.cum, hintAlong + 600) + 1);
      best = bestSegment(route, lat, lng, Math.min(from, last), to, hintAlong, opts);
      if (!best || best.distance > OFF_METERS) {
        const wide = bestSegment(route, lat, lng, 0, last, hintAlong, opts);   // perdeu o fio: procura na rota inteira
        if (wide && (!best || wide.distance < best.distance - 10)) best = wide;
      }
    } else best = bestSegment(route, lat, lng, 0, last, null, opts);
    if (!best) best = bestSegment(route, lat, lng, 0, last, null, null);       // nada satisfaz as regras: sem elas
    const i = best.segment;
    return {along: route.cum[i] + best.t * (route.cum[i + 1] - route.cum[i]), offRoute: best.distance, segment: i};
  }

  /** Estado do progresso: próxima manobra, distâncias restantes e a parada atual. */
  function progress(route, along) {
    const upcoming = route.maneuvers.findIndex(m => m.type !== 'depart' && m.along > along + 1);
    const next = upcoming >= 0 ? route.maneuvers[upcoming] : null;
    const stopK = route.stopAlong.findIndex((s, k) => k > 0 && s > along + 1);
    return {
      next, nextIndex: upcoming,
      nextDistance: next ? Math.max(0, next.along - along) : 0,
      remaining: Math.max(0, route.total - along),
      stop: stopK >= 0 ? stopK : route.stopAlong.length - 1,
      toStop: stopK >= 0 ? Math.max(0, route.stopAlong[stopK] - along) : 0,
    };
  }

  /**
   * Percurso adiantado: o que vem pela frente, rua por rua. Cada item é uma manobra e o trecho que ela abre
   * (até a manobra seguinte): {index, type, street, text, from, to, length, distance, current, lat, lng, stop}.
   * O primeiro é o trecho em que a pessoa está agora (`current`); `distance` é quanto falta para o item começar.
   */
  function itinerary(route, along, max) {
    const ms = route.maneuvers, out = [];
    for (let i = 0; i < ms.length; i++) {
      const m = ms[i], next = ms[i + 1];
      const from = m.along, to = next ? next.along : route.total;
      if (m.type === 'arrive') { if (m.along <= along + 1) continue; }
      else if (to <= along + 1) continue;                                   // trecho já percorrido
      const current = m.type !== 'arrive' && from <= along + 1 && to > along + 1;
      out.push({
        index: i, type: m.type, street: m.street || '', text: describe(m), from, to,
        length: m.type === 'arrive' ? 0 : Math.max(0, to - Math.max(from, current ? along : from)),
        distance: current ? 0 : Math.max(0, from - along), current, lat: m.lat, lng: m.lng,
        stop: m.type === 'arrive' ? m.stop : undefined, final: !!m.final, name: m.name || '',
      });
      if (max && out.length >= max) break;
    }
    return out;
  }
  /** Pontos do traçado entre duas distâncias (para destacar um trecho no mapa). */
  function segment(route, from, to) {
    const a = clamp(Math.min(from, to), 0, route.total), b = clamp(Math.max(from, to), 0, route.total);
    const first = pointAt(route, a), last = pointAt(route, b), pts = [[first.lat, first.lng]];
    for (let i = 0; i < route.points.length; i++) if (route.cum[i] > a && route.cum[i] < b) pts.push(route.points[i]);
    pts.push([last.lat, last.lng]);
    return pts;
  }

  /**
   * Controle de desvio. state: {since: ms|null}. Devolve {state, off, reroute}:
   * `off` assim que passa de OFF_METERS; `reroute` só depois de OFF_SECONDS fora (evita recalcular
   * por um tropeço do GPS). Voltar para perto da rota zera tudo.
   */
  function trackDeviation(state, offRoute, now) {
    if (offRoute <= OFF_METERS * 0.6) return {state: {since: null}, off: false, reroute: false};
    if (offRoute <= OFF_METERS && state.since === null) return {state, off: false, reroute: false};
    const since = state.since === null ? now : state.since;
    return {state: {since}, off: true, reroute: now - since >= OFF_SECONDS * 1000};
  }

  // ---- Texto das instruções (pt-BR) ----------------------------------------------------
  const STREET_WORDS = /^(rua|avenida|alameda|travessa|rodovia|estrada|pra[cç]a|via|viela|marginal|largo|beco|r\.|av\.)\b/i;
  function inStreet(name) {
    if (!name) return '';
    return (STREET_WORDS.test(name) ? 'na ' : 'em ') + name;
  }
  function describe(m) {
    const street = m.street ? ' ' + inStreet(m.street) : '';
    switch (m.type) {
      case 'depart': return m.street ? 'Siga em frente ' + (STREET_WORDS.test(m.street) ? 'pela ' : 'por ') + m.street : 'Siga em frente';
      case 'arrive': return m.final ? 'Você chegou ao destino' + (m.name ? ': ' + m.name : '') : 'Você chegou' + (m.name ? ': ' + m.name : '');
      case 'left': return 'Vire à esquerda' + street;
      case 'right': return 'Vire à direita' + street;
      case 'slight-left': return 'Faça uma curva suave à esquerda' + street;
      case 'slight-right': return 'Faça uma curva suave à direita' + street;
      case 'sharp-left': return 'Faça uma curva fechada à esquerda' + street;
      case 'sharp-right': return 'Faça uma curva fechada à direita' + street;
      case 'uturn': return 'Faça o retorno' + street;
      default: return 'Siga em frente';
    }
  }
  /** "200 metros", "1,2 quilômetro": a forma falada, sem abreviações que a voz leria errado. */
  function spokenDistance(meters) {
    if (meters >= 950) {
      const km = Math.round(meters / 100) / 10;
      return String(km).replace('.', ',') + (km === 1 ? ' quilômetro' : ' quilômetros');
    }
    const rounded = meters >= 200 ? Math.round(meters / 50) * 50 : Math.max(10, Math.round(meters / 10) * 10);
    return rounded + ' metros';
  }
  /** Frase para a voz; `phase` 'far' anuncia a distância, 'near' diz a manobra agora. */
  function spoken(m, meters, phase) {
    const text = describe(m);
    if (m.type === 'arrive' || m.type === 'depart') return text + '.';
    return phase === 'far' ? 'Em ' + spokenDistance(meters) + ', ' + text.charAt(0).toLowerCase() + text.slice(1) + '.' : text + '.';
  }
  /** Distâncias de aviso conforme a velocidade (m/s): a pé avisa perto, de carro, longe. */
  function thresholds(speed) {
    return {far: Math.round(clamp(speed * 10, 60, 250) / 10) * 10, near: Math.round(clamp(speed * 3.5, 15, 50))};
  }
  /** Decide se deve falar agora. `said` guarda o que já foi dito: {key: 'far'|'near'}. */
  function shouldSpeak(said, key, distance, speed) {
    const t = thresholds(speed);
    if (distance <= t.near && said[key] !== 'near') { said[key] = 'near'; return 'near'; }
    if (distance <= t.far && distance > t.near && !said[key]) { said[key] = 'far'; return 'far'; }
    return null;
  }

  const eta = (meters, mode) => Route.minutes(meters, mode);

  return {
    norm360, diff, bearing, offset, smoothAngle, unwrap, headingFromFixes,
    buildRoute, walkAlong, pointAt, maneuvers, locate, progress, itinerary, segment, trackDeviation,
    describe, spoken, spokenDistance, inStreet, thresholds, shouldSpeak, eta,
    ARRIVE_METERS, OFF_METERS, OFF_SECONDS,
  };
});
