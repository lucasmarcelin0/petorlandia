const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../static/js/sfa_entomologia_model.js');
const data = JSON.parse(fs.readFileSync(path.join(__dirname, '../services/data/entomologia/snapshot.json'), 'utf8'));
const rows = data.records;

// Semanas de domingo a sábado, como na comparação semanal do SFA.
assert.equal(M.weekStart('2026-09-08'), '2026-09-06');
assert.equal(M.weekStart('2026-09-06'), '2026-09-06');
assert.equal(M.weekStart('2026-09-05'), '2026-08-30');
assert.equal(M.weekStart('2026-03-01'), '2026-03-01');

const weeks = M.teamWeeks(rows, '2026-09-08', 8);
assert.equal(weeks.length, 8);
assert.equal(weeks[0].start, '2026-07-19');
assert.equal(weeks[7].start, '2026-09-06');
assert.equal(weeks[7].partial, true);
assert.ok(weeks.slice(0, 7).every(w => !w.partial));
const inRange = rows.filter(r => r.date >= '2026-07-19' && r.date <= '2026-09-08').length;
assert.equal(weeks.reduce((s, w) => s + w.count, 0), inRange);
const lastFull = rows.filter(r => r.date >= '2026-08-30' && r.date <= '2026-09-05');
assert.equal(weeks[6].count, lastFull.length);
assert.equal(weeks[6].blocks, new Set(lastFull.map(r => `${r.area}|${r.sector}|${r.block}`)).size);

// Meta = média das 4 semanas anteriores com registro; a própria semana não entra.
const complete = weeks.slice(0, -1);
const expected = complete.slice(-5, -1).reduce((s, w) => s + w.blocks, 0) / 4;
assert.equal(M.baseline(complete, 'blocks'), expected);
const territory = M.achievements(complete, [], '2026-09-10').find(a => a.id === 'territory');
assert.equal(territory.value, weeks[6].blocks);
assert.equal(territory.earned, weeks[6].blocks >= expected);
assert.equal(M.streak(weeks), 8);

// Fixtures: semanas vazias não entram na meta nem zeram a semana em andamento.
const f = (date, extra = {}) => ({date, area: '1', sector: 'S1', block: extra.block || '1',
  ...Object.fromEntries(M.metrics.map(k => [k, null])), worked: 1, closed: 0, refused: 0, positive: 0, mechanical: 0, ...extra});
const fixture = [
  f('2026-03-02', {block: '1'}), f('2026-03-03', {block: '2'}),
  f('2026-03-16', {block: '1'}), f('2026-03-17', {block: '2'}), f('2026-03-18', {block: '3'}, ),
  f('2026-03-23', {block: '1', closed: 9, refused: 1, positive: null}),
];
const fw = M.teamWeeks(fixture, '2026-03-31', 5);
assert.deepEqual(fw.map(w => w.count), [2, 0, 3, 1, 0]);
assert.equal(fw[4].partial, true);
assert.equal(M.streak(fw), 2); // semana atual vazia e parcial não quebra; semana vazia completa quebra
assert.equal(M.baseline(fw.slice(0, 4), 'blocks'), 2.5); // semana sem registro ignorada
assert.equal(fw[3].coverage, 0);
assert.equal(fw[3].accessLoss, 100 * 10 / 11);
const access = M.achievements(fw.slice(0, 4), [], '2026-03-31').find(a => a.id === 'access');
assert.equal(access.target, 0);
assert.equal(access.earned, false); // menor é melhor: 90,9% não alcança 0%
assert.equal(M.achievements([fw[0]], [], '2026-03-31').find(a => a.id === 'territory').noBase, true);

// Ações: verificadas contam na semana; vencidas ignoram as já executadas.
const actions = [
  {id: 1, sector: 'S1', status: 'VERIFICADA', prazo: '2026-03-20', verificado_em: '2026-03-24'},
  {id: 2, sector: 'S2', status: 'EXECUTADA', prazo: '2026-03-01'},
  {id: 3, sector: 'S3', status: 'ABERTA', prazo: '2026-03-01'},
];
const verified = M.achievements(fw.slice(0, 4), actions, '2026-03-31').find(a => a.id === 'verified');
assert.equal(verified.value, 1);
assert.equal(verified.earned, true);
assert.equal(verified.overdue, 1);

// Ciclo de dois meses: universo = quarteirões já vistos no setor.
const cyc = M.cycle(rows, '2026-09-08');
assert.equal(cyc.number, 5);
assert.equal(cyc.start, '2026-09-01');
const known = new Set(rows.map(r => `${r.sector}|${r.area}|${r.block}`)).size;
assert.equal(cyc.blocksKnown, known);
assert.equal(cyc.blocksVisited, new Set(rows.filter(r => r.date >= '2026-09-01').map(r => `${r.sector}|${r.area}|${r.block}`)).size);
assert.ok(cyc.sectors.every((s, i, all) => i === 0 || all[i - 1].pct <= s.pct));
assert.equal(M.cycle(fixture, '2026-02-10').number, 1);
assert.equal(M.cycle(fixture, '2026-02-10').start, '2026-01-01');
assert.equal(M.cycle(fixture, '2026-12-31').start, '2026-11-01');

// Próximos passos: frescor dos dados e focos sem ação aberta.
const steps = M.nextSteps(rows, [], '2026-09-08', '2026-09-28');
assert.deepEqual(steps.find(s => s.kind === 'data'), {kind: 'data', days: 20});
const focus = steps.find(s => s.kind === 'focus');
assert.ok(focus.total > 0);
const covered = M.nextSteps(rows, focus.sectors.map((sector, id) => ({id, sector, status: 'ABERTA', prazo: '2026-10-01'})), '2026-09-08', '2026-09-09');
assert.equal(covered.find(s => s.kind === 'data'), undefined);
assert.ok(!covered.some(s => s.kind === 'focus' && s.sectors.some(c => focus.sectors.includes(c))));
assert.deepEqual(M.nextSteps(fixture, actions, '2026-03-31', '2026-03-31').map(s => s.kind), ['overdue', 'verify']);

console.log('Equipe: semanas, metas relativas, conquistas, sequência, ciclo e próximos passos passed.');
