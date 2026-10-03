// Sessão da navegação: resultado das paradas, progresso na aba, zoom e tema. Uso: node tests/test_atlas_nav_session.js
const assert = require('node:assert/strict');
const S = require('../static/js/sfa_atlas_nav_session.js');

const NOW = Date.UTC(2026, 9, 4, 15, 0, 0);
const stops = [
  {name: 'Rua 1, 10', note: 'Centro', lat: -20.71234, lng: -47.88123},
  {name: 'Rua 2, 20', note: '', lat: -20.71334, lng: -47.88223},
  {name: 'Rua 3, 30', note: 'Jardim', lat: -20.71434, lng: -47.88323},
  {name: 'Rua 4, 40', note: '', lat: -20.71534, lng: -47.88423},
];
const memory = () => { const m = new Map(); return {getItem: k => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)}; };

// ---- chave de parada: igual para a mesma coordenada, mesmo recalculando ----
assert.equal(S.stopKey({lat: -20.712341, lng: -47.881231, name: 'A'}), S.stopKey({lat: -20.712344, lng: -47.881234, name: 'A'}));
// Dois endereços no mesmo ponto (feições diferentes) são duas paradas; a mesma feição é a mesma parada em qualquer ordem.
const twinA = {lat: -20.7, lng: -47.9, name: 'Casa 12', layerId: 'cad', featureId: 'f1'}, twinB = {lat: -20.7, lng: -47.9, name: 'Casa 14', layerId: 'cad', featureId: 'f2'};
assert.notEqual(S.stopKey(twinA), S.stopKey(twinB));
assert.equal(S.stopKey(twinA), S.stopKey({...twinA, lat: -20.70001}), 'a identidade vem da feição, não das coordenadas');
assert.notEqual(S.stopKey({lat: -20.7, lng: -47.9, name: 'Sem camada 1'}), S.stopKey({lat: -20.7, lng: -47.9, name: 'Sem camada 2'}), 'sem camada, o nome separa');
{
  const t = S.create(NOW); S.record(t, S.stopKey(twinA), 'done', NOW);
  assert.equal(S.statusOf(t, twinA), 'done'); assert.equal(S.statusOf(t, twinB), null, 'concluir uma não conclui a outra');
  assert.deepEqual(S.pending([twinA, twinB], t).map(x => x.name), ['Casa 14'], 'a pendente não some ao continuar');
}
assert.notEqual(S.stopKey(stops[0]), S.stopKey(stops[1]));

// ---- registrar, contar e desfazer ----
const s = S.create(NOW);
S.record(s, S.stopKey(stops[0]), 'done', NOW + 1000);
S.record(s, S.stopKey(stops[1]), 'notfound', NOW + 2000);
S.record(s, S.stopKey(stops[2]), 'skipped', NOW + 3000);
assert.deepEqual(S.counts(stops, s), {total: 4, done: 1, notfound: 1, skipped: 1, pending: 1});
assert.equal(S.progressLabel(stops, s), '2 de 4 atendidas');
assert.deepEqual(S.pending(stops, s).map(x => x.name), ['Rua 3, 30', 'Rua 4, 40'], 'pulada volta a ser pendente; concluída e não encontrada não');
const undone = S.undo(s);
assert.equal(undone.status, 'skipped');
assert.equal(S.statusOf(s, stops[2]), null);
S.record(s, S.stopKey(stops[1]), 'done', NOW + 4000);                 // muda de "não encontrada" para "concluída"
assert.equal(S.statusOf(s, stops[1]), 'done');
S.undo(s);
assert.equal(S.statusOf(s, stops[1]), 'notfound', 'desfazer devolve a situação anterior');
assert.throws(() => S.record(s, 'x', 'inventado', NOW));
const empty = S.create(NOW);
assert.equal(S.undo(empty), null);

// ---- guardar na aba e ler de volta ----
const st = memory();
assert.equal(S.save(st, s, NOW + 5000), true);
const back = S.load(st, NOW + 60000);
assert.deepEqual(back.results, s.results);
assert.equal(back.startedAt, NOW);
assert.equal(S.load(st, NOW + S.MAX_AGE + 6000), null, 'passado um turno de campo, não é oferecido');
assert.equal(S.load(memory(), NOW), null);
st.setItem(S.STORE, '{lixo');
assert.equal(S.load(st, NOW), null, 'JSON inválido é ignorado');
st.setItem(S.STORE, JSON.stringify({v: 1, savedAt: NOW, results: {a: 'hackeado', b: 'done'}, log: [{key: 'b', status: 'xx'}]}));
const clean = S.load(st, NOW);
assert.deepEqual(clean.results, {b: 'done'}, 'situações desconhecidas são descartadas');
assert.deepEqual(clean.log, []);
S.clear(st);
assert.equal(S.load(st, NOW), null);
const broken = {getItem() { throw new Error('bloqueado'); }, setItem() { throw new Error('cheio'); }, removeItem() { throw new Error('x'); }};
assert.equal(S.load(broken, NOW), null);
assert.equal(S.save(broken, s, NOW), false);
S.clear(broken);

// ---- quando oferecer "continuar" ----
assert.equal(S.resumable(stops, S.create(NOW)), false, 'nada feito e não pausou');
const paused = S.create(NOW); paused.paused = true;
assert.equal(S.resumable(stops, paused), true, 'saiu pedindo para continuar depois');
assert.equal(S.resumable(stops, s), true);
const all = S.create(NOW); stops.forEach(x => S.record(all, S.stopKey(x), 'done', NOW));
assert.equal(S.resumable(stops, all), false, 'tudo concluído: nada a retomar');
assert.equal(S.resumable([], s), false);
assert.equal(S.resumable(stops, null), false);
// Reordenar ou remover paradas na rota não perde quem já foi atendido.
assert.equal(S.statusOf(s, stops[0]), 'done');
assert.deepEqual(S.pending([stops[3], stops[0]], s).map(x => x.name), ['Rua 4, 40']);

// ---- resumo para copiar ----
const text = S.summaryText(stops, s, {distance: '4,4 km', duration: '52 min'});
assert.match(text, /1 de 4 concluídas · 1 não encontradas · 2 pendentes/);
assert.match(text, /Percurso: 4,4 km · Tempo: 52 min/);
assert.match(text, /1\. ✓ Rua 1, 10 \(Centro\)/);
assert.match(text, /2\. ✕ Rua 2, 20 — não encontrada/);
assert.match(text, /4\. … Rua 4, 40 — pendente/);

// ---- zoom ----
assert.equal(S.zoomFor(0, undefined, 0), 18.5);
assert.equal(S.zoomFor(5, undefined, 0), 17.75);
assert.equal(S.zoomFor(12, undefined, 0), 17);
assert.equal(S.zoomFor(25, undefined, 0), 16.5);
assert.equal(S.zoomFor(12, 50, 0), 17.5, 'perto da manobra chega mais perto');
assert.equal(S.zoomFor(0, undefined, 1), 19.5);
assert.equal(S.zoomFor(0, undefined, 3), 20, 'nunca passa do limite do mapa');
assert.equal(S.zoomFor(25, undefined, -4), 13, 'nem do mínimo');
assert.equal(S.zoomFor(NaN, undefined, 0), 18.5);
assert.equal(S.stepBias(0, 0.5), 0.5);
assert.equal(S.stepBias(2.9, 0.5), 3, 'limite superior');
assert.equal(S.stepBias(-3.9, -0.5), -4, 'limite inferior');
assert.equal(S.stepBias(0.1, 0.5), 0.5, 'encaixa em passos de 0,25');
assert.ok(Math.abs(S.pinchBias(0, 2) - 1) < 1e-9, 'dedos 2× mais afastados = +1 nível');
assert.ok(Math.abs(S.pinchBias(0, 0.5) + 1) < 1e-9);
assert.equal(S.pinchBias(0, 100), 3);
assert.equal(S.pinchBias(1, 0), 1, 'razão inválida não muda');

// ---- tema ----
const at = (h, m = 0) => new Date(2026, 9, 4, h, m);
assert.equal(S.isNight(at(12), 'auto'), false);
assert.equal(S.isNight(at(17, 59), 'auto'), false);
assert.equal(S.isNight(at(18), 'auto'), true);
assert.equal(S.isNight(at(3), 'auto'), true);
assert.equal(S.isNight(at(5, 29), 'auto'), true);
assert.equal(S.isNight(at(5, 30), 'auto'), false);
assert.equal(S.isNight(at(12), 'night'), true);
assert.equal(S.isNight(at(23), 'day'), false);
assert.deepEqual(['auto', 'night', 'day'].map(S.nextTheme), ['night', 'day', 'auto']);

// ---- barra de aproximação ----
assert.equal(S.approach(0, 10), 1);
assert.equal(S.approach(1000, 10), 0);
assert.ok(S.approach(75, 0) > 0.49 && S.approach(75, 0) < 0.51, 'a pé: faixa de 150 m');
assert.ok(S.approach(200, 25) > S.approach(200, 3), 'em velocidade o aviso começa mais cedo');
assert.equal(S.approach(NaN, 5), 0);

// ---- gestos livres ----
const near = (a, b, m) => assert.ok(Math.abs(a - b) < 1e-9, (m || '') + ' ' + a + ' ≉ ' + b);
near(S.fingerAngle({x: 0, y: 0}, {x: 10, y: 0}), 0); near(S.fingerAngle({x: 0, y: 0}, {x: 0, y: 10}), 90); near(S.fingerAngle({x: 0, y: 0}, {x: -10, y: 0}), 180);
near(S.angleDelta(350, 10), 20, 'atravessa o norte'); near(S.angleDelta(10, 350), -20); near(S.angleDelta(0, 180), 180); near(S.angleDelta(90, 90), 0);
near(S.angleDelta(-170, 170), -20);
// Mapa sem giro: arrastar 10 px à direita desloca 10 px à direita no quadrado.
let v = S.screenToMap(10, 0, 0); near(v[0], 10); near(v[1], 0);
// Mapa girado 90° (quadrado em rotate(-90°)): um arrasto para a direita na tela vira "para baixo" no quadrado.
v = S.screenToMap(10, 0, 90); near(v[0], 0, 'x'); near(v[1], 10, 'y');
// Ida e volta: girar o ponto do quadrado para a tela (anti-horário, rotation) e voltar devolve o vetor.
for (const rot of [0, 33, 90, 180, 271, -45]) {
  const t = rot * Math.PI / 180, p = [7, -3];
  const onScreen = [p[0] * Math.cos(t) + p[1] * Math.sin(t), -p[0] * Math.sin(t) + p[1] * Math.cos(t)];   // rotate(-rot) do CSS
  const back = S.screenToMap(onScreen[0], onScreen[1], rot);
  near(back[0], p[0], 'ida e volta x ' + rot); near(back[1], p[1], 'ida e volta y ' + rot);
}
near(S.gestureZoom(17, 2), 18); near(S.gestureZoom(17, 0.5), 16); assert.equal(S.gestureZoom(19.5, 4), 20); assert.equal(S.gestureZoom(12.5, 0.1), 12); assert.equal(S.gestureZoom(17, 0), 17);
near(S.gestureRotation(40, 15), 25); near(S.gestureRotation(10, -30), 40);
assert.ok(S.FREE_IDLE_MS >= 10000 && S.FREE_IDLE_MS <= 60000);

console.log('sessão da navegação: ok');
