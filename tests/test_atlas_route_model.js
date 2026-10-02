// Rotas locais de campo. Uso: node tests/test_atlas_route_model.js [fixture-real.json]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const R = require('../static/js/sfa_atlas_route_model.js');

const MICRO = 1e6, STEP = 0.001;               // ~111 m entre pontos vizinhos
const X0 = -47.9, Y0 = -20.7;

// Malha em grade size×size; devolve payload no formato do servidor.
function lattice(size, x0 = X0, y0 = Y0, base = 0, gaps = []) {
  const nodes = [], edges = [], id = (i, j) => base + i * size + j;
  for (let i = 0; i < size; i++) for (let j = 0; j < size; j++) nodes.push(Math.round((x0 + j * STEP) * MICRO), Math.round((y0 + i * STEP) * MICRO));
  for (let i = 0; i < size; i++) for (let j = 0; j < size; j++) {
    if (j + 1 < size && !gaps.includes(id(i, j) + '-' + id(i, j + 1))) edges.push(id(i, j), id(i, j + 1));
    if (i + 1 < size && !gaps.includes(id(i, j) + '-' + id(i + 1, j))) edges.push(id(i, j), id(i + 1, j));
  }
  return {v: 1, nodes, edges};
}
const merge = (a, b) => ({v: 1, nodes: a.nodes.concat(b.nodes), edges: a.edges.concat(b.edges.map(n => n + a.nodes.length / 2))});
const at = (i, j) => ({lng: X0 + j * STEP, lat: Y0 + i * STEP});
const near = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, a + ' ≉ ' + b);

// 1. Distância: 1° de latitude ≈ 111,2 km.
near(R.distance(0, 0, 1, 0), 111195, 200);
near(R.distance(-20.7, -47.9, -20.7, -47.9), 0, 1e-9);

// 2. Grafo: contagens e componentes (duas grades separadas + uma ilha pequena).
const main = lattice(15);                                     // 225 pontos: malha principal
const graph = R.createGraph(main);
assert.equal(graph.n, 225);
assert.equal(graph.m, 2 * 15 * 14);
assert.equal(graph.sizes.length, 1);
const far = lattice(3, X0 + 0.05, Y0);
const withIsland = R.createGraph(merge(main, far));
assert.equal(withIsland.sizes.length, 2);
assert.deepEqual([...withIsland.sizes].sort((a, b) => b - a), [225, 9]);

// 3. Ponto da rua mais próximo: o da grade; prefere a malha principal à ilha, mesmo se a ilha estiver mais perto.
let s = R.nearest(graph, X0 + 3 * STEP + 0.0001, Y0 + 2 * STEP - 0.0001);
assert.equal(s.node, 2 * 15 + 3);
assert.ok(s.distance < 20);
const mixed = R.createGraph(merge(main, lattice(3, X0 + 15 * STEP + 0.0002, Y0)));   // ilha ao lado da grade principal
s = R.nearest(mixed, X0 + 15 * STEP + 0.0002, Y0);
assert.ok(s.node < 225, 'prefere a malha principal');
assert.equal(R.nearest(graph, X0 + 1, Y0), null, 'longe demais de qualquer rua');

// 4. Menor caminho: de um canto ao oposto são 14 + 14 trechos de ~111 m (Manhattan).
const corner = R.shortest(graph, 0, [224]);
const manhattan = 14 * R.distance(Y0, X0, Y0, X0 + STEP) + 14 * R.distance(Y0, X0, Y0 + STEP, X0);
near(corner.dist[224], manhattan, 5);

// 5. Rota com três paradas: trechos ligados, distâncias coerentes, caminho contínuo.
const stops = [at(0, 0), at(0, 7), at(7, 7)];
const route = R.plan(graph, stops);
assert.equal(route.legs.length, 2);
assert.ok(route.connected);
near(route.total, 7 * R.distance(Y0, X0, Y0, X0 + STEP) + 7 * R.distance(Y0, X0, Y0 + STEP, X0), 8);   // 7 a leste + 7 ao norte
for (const leg of route.legs) {
  assert.deepEqual(leg.path[0], [stops[leg.from].lat, stops[leg.from].lng]);
  assert.deepEqual(leg.path[leg.path.length - 1], [stops[leg.to].lat, stops[leg.to].lng]);
  for (let k = 1; k < leg.path.length; k++) assert.ok(R.distance(...leg.path[k - 1], ...leg.path[k]) < 130, 'passo contínuo');
  assert.ok(leg.distance >= R.distance(stops[leg.from].lat, stops[leg.from].lng, stops[leg.to].lat, stops[leg.to].lng) - 1);
}
assert.deepEqual(R.plan(graph, [stops[0]]).legs, []);
assert.equal(R.plan(graph, []).total, 0);

// 6. Parada sem ligação com a malha: o trecho vira linha reta e a rota segue sendo devolvida.
const split = R.createGraph(merge(main, lattice(3, X0, Y0 + 0.05)));
const broken = R.plan(split, [at(0, 0), {lng: X0, lat: Y0 + 0.05}]);
assert.equal(broken.connected, false);
assert.equal(broken.legs[0].connected, false);
assert.equal(broken.legs[0].path.length, 2);
near(broken.total, R.distance(Y0, X0, Y0 + 0.05, X0), 1);

// 7. Melhor ordem: partida fixa; confere contra força bruta (N pequeno) e nunca piora.
function permutations(items) {
  if (items.length <= 1) return [items];
  return items.flatMap((x, i) => permutations(items.filter((_, j) => j !== i)).map(p => [x, ...p]));
}
const scattered = [at(0, 0), at(12, 12), at(1, 1), at(11, 2), at(2, 10), at(13, 5), at(5, 13)];
const optimized = R.optimizeOrder(graph, scattered);
assert.equal(optimized.order[0], 0);
assert.deepEqual([...optimized.order].sort((a, b) => a - b), scattered.map((_, i) => i));
assert.ok(optimized.exact && optimized.after <= optimized.before);
const D = R.matrix(graph, scattered), cost = o => o.slice(1).reduce((sum, v, i) => sum + D[o[i]][v], 0);
const brute = Math.min(...permutations(scattered.map((_, i) => i).slice(1)).map(p => cost([0, ...p])));
near(optimized.after, brute, 1e-6);
assert.ok(optimized.after < optimized.before * 0.8, 'a ordem dada em ziguezague deve melhorar bastante');

// 8. Muitas paradas: método aproximado, ainda uma permutação válida com partida fixa e sem piorar.
const many = Array.from({length: 16}, (_, i) => at((i * 7) % 15, (i * 11) % 15));
const big = R.optimizeOrder(graph, many);
assert.equal(big.exact, false);
assert.equal(big.order[0], 0);
assert.deepEqual([...big.order].sort((a, b) => a - b), many.map((_, i) => i));
assert.ok(big.after <= big.before);
assert.deepEqual(R.optimizeOrder(graph, [at(0, 0), at(3, 3)]).order, [0, 1]);

// 9. Tempo e formatação.
assert.equal(R.formatDistance(430), '430 m');
assert.equal(R.formatDistance(2450), '2,5 km');
assert.equal(R.formatDuration(0.2), '1 min');
assert.equal(R.formatDuration(75), '1 h 15');
near(R.minutes(4500, 'foot'), 60, 1e-9);
assert.ok(R.minutes(4500, 'motor') < 15);

// 10. Links do Google Maps: só coordenadas, em blocos encadeados de até 10 pontos.
const pts = Array.from({length: 21}, (_, i) => ({lat: -20.7 + i / 1000, lng: -47.9}));
const links = R.googleMapsLinks(pts, 'foot');
assert.equal(links.length, 3);
assert.equal(links[0].from, 1);
assert.ok(links.every(l => l.url.startsWith('https://www.google.com/maps/dir/?api=1&')));
assert.ok(links[0].url.includes('travelmode=walking') && R.googleMapsLinks(pts, 'motor')[0].url.includes('driving'));
assert.deepEqual(R.googleMapsLinks([pts[0]], 'foot'), []);
const first = new URL(links[0].url).searchParams;
assert.equal(first.get('waypoints').split('|').length, 8);

// 11. Malha real da cidade (se o fixture existir): rota entre ruas conhecidas.
let checked = 'sintéticos';
if (process.argv[2]) {
  const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const real = R.createGraph(fixture.graph);
  assert.ok(real.n > 3000);
  const points = fixture.points;                                   // [{lng,lat,name}, ...]
  const result = R.plan(real, points);
  assert.ok(result.legs.length === points.length - 1);
  const connected = result.legs.filter(l => l.connected).length;
  assert.ok(connected >= result.legs.length - 1, 'quase todos os trechos devem seguir ruas: ' + connected + '/' + result.legs.length);
  for (const leg of result.legs.filter(l => l.connected)) {
    const straight = R.distance(points[leg.from].lat, points[leg.from].lng, points[leg.to].lat, points[leg.to].lng);
    assert.ok(leg.distance >= straight * 0.99, 'rota não pode ser menor que a linha reta');
    assert.ok(leg.distance <= straight * 4 + 300, 'rota absurdamente longa: ' + leg.distance + ' vs ' + straight);
    for (let k = 1; k < leg.path.length - 1; k++) assert.ok(R.distance(...leg.path[k - 1], ...leg.path[k]) < 600 || k === 1);
  }
  const opt = R.optimizeOrder(real, points);
  assert.ok(opt.after <= opt.before);
  checked = 'reais (' + points.length + ' paradas, ' + connected + '/' + result.legs.length + ' trechos por ruas, ' + Math.round(result.total) + ' m)';
}
console.log('ok: roteamento ' + checked);
