// Navegação de campo: manobras, progresso, desvio e instruções. Uso: node tests/test_atlas_nav_model.js [fixture-real.json]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Route = require('../static/js/sfa_atlas_route_model.js');
const Nav = require('../static/js/sfa_atlas_nav_model.js');

const MICRO = 1e6, X0 = -47.9, Y0 = -20.7;
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, (msg || '') + ' ' + a + ' ≉ ' + b);

// ---- Ruas desenhadas em metros (leste, norte) a partir de uma origem ----
const lng = e => X0 + e / (111320 * Math.cos(Y0 * Math.PI / 180)), lat = n => Y0 + n / 110574;
const where = ([e, n]) => ({lat: lat(n), lng: lng(e)});
function street(name, ...points) {            // vértices a cada ≤ 25 m
  const dense = [];
  for (let k = 0; k + 1 < points.length; k++) {
    const [a, b] = [points[k], points[k + 1]], steps = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 25));
    for (let s = 0; s < steps; s++) dense.push([a[0] + (b[0] - a[0]) * s / steps, a[1] + (b[1] - a[1]) * s / steps]);
  }
  dense.push(points[points.length - 1]);
  return {name, points: dense};
}
function network(...streets) {
  const nodes = [], index = new Map(), edges = [], names = [], en = [];
  const node = ([e, n]) => {
    const key = Math.round(lng(e) * MICRO) + ',' + Math.round(lat(n) * MICRO);
    if (!index.has(key)) { index.set(key, index.size); nodes.push(Math.round(lng(e) * MICRO), Math.round(lat(n) * MICRO)); }
    return index.get(key);
  };
  streets.forEach(s => {
    names.push(s.name);
    for (let k = 0; k + 1 < s.points.length; k++) { edges.push(node(s.points[k]), node(s.points[k + 1])); en.push(names.length - 1); }
  });
  return Route.createGraph({v: 2, nodes, edges, names, en});
}
function drive(graph, ...stops) {
  const places = stops.map(where), plan = Route.plan(graph, places);
  assert.ok(plan.connected, 'a rota de teste precisa seguir as ruas');
  return Nav.buildRoute(graph, plan.legs, places.map((p, k) => ({...p, name: 'Parada ' + (k + 1)})));
}
const turnsOf = r => r.maneuvers.filter(m => !['depart', 'arrive'].includes(m.type));
const dir = (deg, meters) => [Math.sin(deg * Math.PI / 180) * meters, Math.cos(deg * Math.PI / 180) * meters];   // rumo (0=norte, 90=leste)
const plus = (p, q) => [p[0] + q[0], p[1] + q[1]];

// 1. Ângulos: o giro é sempre pelo caminho curto; positivo = direita.
assert.equal(Nav.diff(350, 10), 20); assert.equal(Nav.diff(10, 350), -20);
assert.equal(Nav.diff(90, 0), -90); assert.equal(Nav.diff(0, 90), 90);
near(Nav.bearing(-20.7, -47.9, -20.69, -47.9), 0, 0.01); near(Nav.bearing(-20.7, -47.9, -20.7, -47.89), 90, 0.05);
near(Nav.bearing(-20.7, -47.9, -20.71, -47.9), 180, 0.01);
const moved = Nav.offset(-20.7, -47.9, 90, 500);
near(Route.distance(-20.7, -47.9, moved.lat, moved.lng), 500, 0.5);
near(Nav.smoothAngle(350, 10, 0.5), 0, 1e-9, 'passa por 0°, não por 180°');
near(Nav.unwrap(359, 2), 362, 1e-9); near(Nav.unwrap(Nav.unwrap(10, 350), 20), 20, 1e-9);
near(Nav.headingFromFixes({lat: -20.7, lng: -47.9}, {lat: -20.7, lng: -47.9001}), 270, 0.01);
assert.equal(Nav.headingFromFixes({lat: -20.7, lng: -47.9}, {lat: -20.7, lng: -47.900005}), null, '< 4 m: não é confiável');
assert.equal(Nav.headingFromFixes(null, {lat: 0, lng: 0}), null);

// 2. Curva à esquerda num cruzamento (leste → norte), com a rua transversal de apoio.
const L = network(street('Rua A', [0, 0], [300, 0]), street('Avenida B', [300, 0], [300, 250]), street('Rua C', [300, 0], [300, -100]));
let r = drive(L, [0, 0], [300, 250]);
assert.deepEqual(r.maneuvers.map(m => m.type), ['depart', 'left', 'arrive']);
near(r.maneuvers[0].heading, 90, 1); assert.equal(r.maneuvers[0].street, 'Rua A');
assert.equal(r.maneuvers[1].street, 'Avenida B'); assert.equal(r.maneuvers[1].from, 'Rua A');
near(r.maneuvers[1].along, 300, 4); assert.ok(r.maneuvers[2].final); near(r.total, 550, 5);
assert.equal(Nav.describe(r.maneuvers[1]), 'Vire à esquerda na Avenida B');
assert.equal(Nav.describe(r.maneuvers[0]), 'Siga em frente pela Rua A');
assert.equal(Nav.describe(r.maneuvers[2]), 'Você chegou ao destino: Parada 2');

// 3. À direita (leste → sul) e sem rua transversal (esquina simples, 90°).
const R = network(street('Rua A', [0, 0], [300, 0]), street('Avenida B', [300, 0], [300, -250]));
r = drive(R, [0, 0], [300, -250]);
assert.deepEqual(r.maneuvers.map(m => m.type), ['depart', 'right', 'arrive']);
assert.equal(Nav.describe(r.maneuvers[1]), 'Vire à direita na Avenida B');

// 4. Intensidades: suave (35°), fechada (140°) e retorno (170°) em cruzamento; 20° não é manobra.
function junction(angle) {
  const heading = 90 + angle, corner = [300, 0], end = plus(corner, dir(heading, 250));
  // Rua E sai do cruzamento para trás: o ponto tem 3 ruas e passa a contar como cruzamento.
  const g = network(street('Rua A', [0, 0], corner), street('Rua D', corner, end), street('Rua E', corner, plus(corner, dir(heading + 180, 120))));
  return [g, end];
}
const kind = angle => { const [g, end] = junction(angle); return turnsOf(drive(g, [0, 0], end)).map(m => m.type); };
assert.deepEqual(kind(20), [], '20° em cruzamento: segue em frente');
assert.deepEqual(kind(35), ['slight-right']);
assert.deepEqual(kind(-35), ['slight-left']);
assert.deepEqual(kind(70), ['right']);
assert.deepEqual(kind(-70), ['left']);
assert.deepEqual(kind(140), ['sharp-right']);
assert.deepEqual(kind(172), ['uturn']);

// 5. Sem cruzamento (só dois trechos ligados): 35° é curva da rua, 70° é esquina de verdade.
const bend = angle => { const corner = [300, 0], end = plus(corner, dir(90 + angle, 250)); return turnsOf(drive(network(street('Rua A', [0, 0], corner), street('Rua B', corner, end)), [0, 0], end)).map(m => m.type); };
assert.deepEqual(bend(35), [], 'curva suave sem cruzamento não é manobra');
assert.deepEqual(bend(70), ['right']);

// 6. Curva longa e arredondada (90° em 8 vértices): não vira "vire à direita" a cada vértice.
// Segue ao leste e faz uma curva de raio 60 m para o sul (centro em [150,-60]), em 8 vértices.
const arc = [[0, 0], [150, 0]];
for (let k = 1; k <= 8; k++) { const t = (k / 8) * Math.PI / 2; arc.push([150 + 60 * Math.sin(t), -60 + 60 * Math.cos(t)]); }
const curved = network(street('Rodovia X', ...arc));
r = drive(curved, [0, 0], arc[arc.length - 1]);
assert.ok(turnsOf(r).length <= 1, 'curva arredondada: no máximo uma manobra, veio ' + turnsOf(r).length);

// 7. Duas esquinas coladas (12 m) viram uma só, a de maior giro; e esquina colada na chegada é ignorada.
const zig = network(street('Rua A', [0, 0], [200, 0]), street('Rua B', [200, 0], [200, 12]), street('Rua C', [200, 12], [400, 12]), street('Rua S', [200, 0], [200, -80]), street('Rua T', [200, 12], [200, 90]));
r = drive(zig, [0, 0], [400, 12]);
assert.ok(turnsOf(r).length <= 1, 'cruzamento deslocado vira uma manobra no máximo');
const tail = network(street('Rua A', [0, 0], [300, 0]), street('Rua B', [300, 0], [300, 10]), street('Rua S', [300, 0], [300, -50]));
assert.deepEqual(turnsOf(drive(tail, [0, 0], [300, 10])), [], 'esquina a 10 m da chegada não é manobra');

// 8. Onde o aparelho está: projeção na rota, com ruído de GPS e "pista" do progresso.
r = drive(L, [0, 0], [300, 250]);
for (const along of [0, 40, 123, 299, 301, 420, 549]) {
  const p = Nav.walkAlong(r, along), here = Nav.locate(r, p.lat, p.lng);
  near(here.along, along, 0.6, 'locate(walkAlong(' + along + '))'); assert.ok(here.offRoute < 0.5);
}
let hint = 0;
for (let along = 0; along <= 540; along += 10) {                  // andando com ±8 m de erro lateral
  const p = Nav.walkAlong(r, along), side = Nav.offset(p.lat, p.lng, p.heading + 90, (along % 20 ? 8 : -8));
  const here = Nav.locate(r, side.lat, side.lng, hint);
  near(here.along, along, 9, 'progresso com ruído em ' + along); assert.ok(here.offRoute < 9.5);
  assert.ok(here.along >= hint - 9, 'o progresso não volta'); hint = Math.max(hint, here.along);
}
const far = Nav.offset(Nav.walkAlong(r, 100).lat, Nav.walkAlong(r, 100).lng, 0, 90);
near(Nav.locate(r, far.lat, far.lng, 100).offRoute, 90, 2);

// 9. Progresso: próxima manobra, restante e parada.
let p = Nav.progress(r, 100);
assert.equal(p.next.type, 'left'); near(p.nextDistance, 200, 5); near(p.remaining, r.total - 100, 1e-6); assert.equal(p.stop, 1);
p = Nav.progress(r, 320);
assert.equal(p.next.type, 'arrive'); near(p.nextDistance, r.total - 320, 1); near(p.toStop, r.total - 320, 1);
p = Nav.progress(r, r.total);
assert.equal(p.next, null); assert.equal(p.remaining, 0);

// 10. Desvio: só recalcula depois de 4 s fora; voltar para perto zera; histerese entre 24 e 40 m.
let st = {since: null}, out;
out = Nav.trackDeviation(st, 10, 0); assert.deepEqual([out.off, out.reroute], [false, false]);
out = Nav.trackDeviation(out.state, 30, 1000); assert.deepEqual([out.off, out.reroute], [false, false], '30 m ainda não é desvio');
out = Nav.trackDeviation(out.state, 80, 2000); assert.deepEqual([out.off, out.reroute], [true, false]);
out = Nav.trackDeviation(out.state, 80, 5900); assert.equal(out.reroute, false, '3,9 s: ainda não');
out = Nav.trackDeviation(out.state, 85, 6000); assert.equal(out.reroute, true, '4 s fora: recalcula');
out = Nav.trackDeviation({since: 2000}, 30, 7000); assert.equal(out.off, true, 'já estava fora: 30 m não volta ao normal');
out = Nav.trackDeviation(out.state, 12, 7500); assert.deepEqual([out.off, out.reroute, out.state.since], [false, false, null]);

// 11. Voz: avisa uma vez de longe e uma vez de perto, conforme a velocidade.
assert.deepEqual(Nav.thresholds(1.3), {far: 60, near: 15});      // a pé
assert.deepEqual(Nav.thresholds(12), {far: 120, near: 42});      // carro na cidade
assert.deepEqual(Nav.thresholds(30), {far: 250, near: 50});      // estrada
const said = {}, spoken = [];
for (const d of [300, 130, 119, 100, 60, 42, 30, 5]) { const s = Nav.shouldSpeak(said, 'm1', d, 12); if (s) spoken.push([d, s]); }
assert.deepEqual(spoken, [[119, 'far'], [42, 'near']]);
assert.equal(Nav.shouldSpeak(said, 'm2', 500, 12), null);
assert.equal(Nav.shouldSpeak({}, 'x', 10, 1.3), 'near', 'já dentro da distância curta: fala só a manobra');

// 12. Texto em português.
assert.equal(Nav.inStreet('Rua Um'), 'na Rua Um'); assert.equal(Nav.inStreet('Avenida Brasil'), 'na Avenida Brasil');
assert.equal(Nav.inStreet('Rodovia Altino Arantes'), 'na Rodovia Altino Arantes'); assert.equal(Nav.inStreet('Jardim Bandeirantes'), 'em Jardim Bandeirantes');
assert.equal(Nav.inStreet(''), '');
assert.equal(Nav.spokenDistance(40), '40 metros'); assert.equal(Nav.spokenDistance(3), '10 metros');
assert.equal(Nav.spokenDistance(137), '140 metros'); assert.equal(Nav.spokenDistance(230), '250 metros');
assert.equal(Nav.spokenDistance(950), '1 quilômetro'); assert.equal(Nav.spokenDistance(1234), '1,2 quilômetros');
const right = {type: 'right', street: 'Rua Quinze'};
assert.equal(Nav.spoken(right, 200, 'far'), 'Em 200 metros, vire à direita na Rua Quinze.');
assert.equal(Nav.spoken(right, 20, 'near'), 'Vire à direita na Rua Quinze.');
assert.equal(Nav.spoken({type: 'arrive', name: 'UBS Centro', final: false}, 0, 'near'), 'Você chegou: UBS Centro.');
assert.equal(Nav.describe({type: 'uturn', street: ''}), 'Faça o retorno');
assert.equal(Nav.describe({type: 'sharp-left', street: 'Rua B'}), 'Faça uma curva fechada à esquerda na Rua B');
assert.equal(Nav.describe({type: 'slight-right', street: ''}), 'Faça uma curva suave à direita');

// 12b. Percurso adiantado: rua por rua, com o trecho de cada uma.
{
  const g = network(street('Rua A', [0, 0], [300, 0]), street('Avenida B', [300, 0], [300, 250]), street('Rua C', [300, 250], [100, 250]));
  const route = drive(g, [0, 0], [100, 250]);
  const all = Nav.itinerary(route, 0);
  assert.deepEqual(all.map(i => i.type), ['depart', 'left', 'left', 'arrive']);
  assert.deepEqual(all.map(i => i.street), ['Rua A', 'Avenida B', 'Rua C', '']);
  assert.equal(all[0].current, true, 'o primeiro item é o trecho em que a pessoa está');
  assert.equal(all[1].current, false);
  near(all[0].length, 300, 6); near(all[1].length, 250, 6); near(all[2].length, 200, 6);
  assert.equal(all[3].length, 0);
  near(all[1].distance, 300, 6, 'a primeira curva está a ~300 m'); near(all[2].distance, 550, 8);
  assert.equal(all[1].text, 'Vire à esquerda na Avenida B');
  assert.equal(all[3].final, true);
  // Os trechos somam o percurso inteiro.
  near(all.reduce((t, i) => t + i.length, 0), route.total, 3);
  // Andando: o trecho já feito some e o corrente encurta.
  const mid = Nav.itinerary(route, 380);
  assert.deepEqual(mid.map(i => i.street), ['Avenida B', 'Rua C', '']);
  assert.equal(mid[0].current, true); near(mid[0].length, 300 + 250 - 380, 6); assert.equal(mid[0].distance, 0);
  near(mid[1].distance, 550 - 380, 8);
  assert.equal(Nav.itinerary(route, 0, 2).length, 2, 'respeita o limite');
  assert.deepEqual(Nav.itinerary(route, route.total).map(i => i.type), [], 'no fim não sobra nada');
  // Trecho destacado no mapa: começa e termina onde dizem.
  const seg = Nav.segment(route, all[1].from, all[1].to);
  near(Route.distance(seg[0][0], seg[0][1], all[1].lat, all[1].lng), 0, 1.5);
  const last = seg[seg.length - 1], endPt = Nav.pointAt(route, all[1].to);
  near(Route.distance(last[0], last[1], endPt.lat, endPt.lng), 0, 0.5);
  let meters = 0; for (let k = 1; k < seg.length; k++) meters += Route.distance(seg[k - 1][0], seg[k - 1][1], seg[k][0], seg[k][1]);
  near(meters, all[1].to - all[1].from, 3);
  assert.equal(Nav.segment(route, 500, 100).length >= 2, true, 'aceita os limites invertidos');
  // Duas paradas: cada chegada vira um item com o número da parada.
  const two = drive(g, [0, 0], [300, 250], [100, 250]);
  const stopsList = Nav.itinerary(two, 0).filter(i => i.type === 'arrive');
  assert.deepEqual(stopsList.map(i => i.stop), [1, 2]); assert.deepEqual(stopsList.map(i => i.final), [false, true]);
}

// 13. Malha real da cidade: manobras plausíveis e progresso coerente ao "andar" a rota inteira.
let checked = 'sintéticos';
if (process.argv[2]) {
  const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const real = Route.createGraph(fixture.graph), stops = fixture.points;
  const planned = Route.plan(real, stops);
  const route = Nav.buildRoute(real, planned.legs, stops.map((s, k) => ({...s, name: s.name || 'Parada ' + (k + 1)})));
  const arrivals = route.maneuvers.filter(m => m.type === 'arrive');
  assert.equal(arrivals.length, stops.length - 1);
  assert.equal(route.maneuvers[0].type, 'depart');
  assert.equal(arrivals.filter(m => m.final).length, 1);
  const turns = turnsOf(route);
  for (let k = 1; k < route.maneuvers.length; k++) assert.ok(route.maneuvers[k].along >= route.maneuvers[k - 1].along, 'manobras em ordem');
  for (let k = 1; k < turns.length; k++) assert.ok(turns[k].along - turns[k - 1].along >= 12, 'manobras não coladas');
  assert.ok(turns.length <= route.total / 30, 'no máximo uma manobra a cada 30 m: ' + turns.length + ' em ' + Math.round(route.total) + ' m');
  const named = turns.filter(m => m.street).length;
  assert.ok(!turns.length || named >= turns.length * 0.8, 'a maioria das manobras tem nome de rua: ' + named + '/' + turns.length);
  // Anda a rota inteira de 8 em 8 m com ruído de ±6 m: progresso sempre para a frente e perto da linha.
  // A rota entra e sai pelo acesso curto de cada parada (ida e volta até a rua): ali a mesma
  // posição aparece duas vezes e o progresso pode diferir pelo comprimento do acesso. Fora
  // isso, o erro tem de ser pequeno, sem saltos grandes e sem voltar.
  // Como no aplicativo: o rumo vem do movimento (com erro) e, ao chegar a uma parada, o progresso
  // não volta para antes dela. A rota de teste volta pela mesma rua em alguns trechos.
  let hintAlong = 0, worst = 0, back = 0, samples = 0, off = 0, reached = 0, nextStop = 1;
  for (let along = 0; along <= route.total; along += 8) {
    const pt = Nav.walkAlong(route, along), noisy = Nav.offset(pt.lat, pt.lng, pt.heading + 90, (Math.round(along / 8) % 2 ? 6 : -6));
    const here = Nav.locate(route, noisy.lat, noisy.lng, hintAlong, {minAlong: reached, heading: pt.heading + (Math.round(along / 8) % 3 - 1) * 15});
    if (nextStop < route.stopAlong.length && Route.distance(noisy.lat, noisy.lng, route.stops[nextStop].lat, route.stops[nextStop].lng) <= Nav.ARRIVE_METERS) {
      reached = route.stopAlong[nextStop] - (Nav.ARRIVE_METERS + 5); nextStop++;   // chegou: não volta para antes da parada (menos o raio de chegada)
    }
    const error = Math.abs(here.along - along);
    worst = Math.max(worst, error); samples++; if (error > 20) off++;
    back = Math.min(back, here.along - hintAlong); hintAlong = here.along;
    assert.ok(here.offRoute < Nav.OFF_METERS * 0.6, 'seria acusado de desvio em ' + Math.round(along) + ' m: ' + here.offRoute);
  }
  assert.ok(worst < 150, 'salto de progresso de ' + Math.round(worst) + ' m');
  assert.ok(off <= samples * 0.03, off + ' de ' + samples + ' amostras com erro > 20 m');
  assert.ok(back > -150, 'o progresso voltou ' + back + ' m');
  assert.ok(hintAlong > route.total - 100, 'terminou longe do fim da rota');
  // Cada instrução descreve uma curva que existe: o giro medido na geometria bate com o tipo.
  // (Perto do acesso de uma parada, que entra e sai da rua, ou de trechos longos, a medição por
  // vértices não representa a curva; ali a conferência não vale.)
  let verified = 0;
  turns.forEach(m => {
    const lo = Math.max(0, m.index - 3), hi = Math.min(route.points.length - 1, m.index + 3);
    let clean = true;
    for (let j = lo; j <= hi; j++) if (route.nodeAt[j] < 0 || (j < hi && route.cum[j + 1] - route.cum[j] > 150)) clean = false;
    if (!clean) return;
    verified++;
    const c = route.points[m.index];
    const measure = k => { const b = route.points[Math.max(0, m.index - k)], f = route.points[Math.min(route.points.length - 1, m.index + k)];
      return Nav.diff(Nav.bearing(b[0], b[1], c[0], c[1]), Nav.bearing(c[0], c[1], f[0], f[1])); };
    // Curva de verdade: o giro medido junto ao vértice (±1) ou em volta dele (±3) tem o mesmo sinal.
    const agrees = [1, 3].some(k => Math.sign(measure(k)) === Math.sign(m.angle) || Math.abs(measure(k)) < 10);
    assert.ok(agrees, 'sinal do giro em ' + m.street + ': ' + m.angle.toFixed(0) + ' vs ' + measure(1).toFixed(0) + '/' + measure(3).toFixed(0));
  });
  assert.ok(verified >= Math.min(5, turns.length), 'poucas curvas conferidas: ' + verified + ' de ' + turns.length);
  checked = 'reais (' + stops.length + ' paradas, ' + Math.round(route.total) + ' m, ' + turns.length + ' manobras, ' + named + ' com nome de rua)';
}
console.log('ok: navegação ' + checked);
