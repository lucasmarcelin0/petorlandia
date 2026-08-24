const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const scriptPath = path.join(__dirname, '..', 'static', 'js', 'sfa_instrument_lab.js');
let source = fs.readFileSync(scriptPath, 'utf8');
source = source.replace(
  "  const root = document.getElementById('sfa-instrument-lab');\n  if (!root) return;",
  "  const root = {};"
);
source = source.replace(
  '  const labTabs = Array.from(root.querySelectorAll(\'[data-lab-view]\'));',
  `  globalThis.__sfaLabModel = {
    buildSyntheticCohort,
    buildSignals,
    registeredDecisions,
    scenarioDefinitions,
    wilsonInterval
  };
  return;
  const labTabs = Array.from(root.querySelectorAll('[data-lab-view]'));`
);
vm.runInThisContext(source, { filename: scriptPath });

const model = globalThis.__sfaLabModel;
assert(model, 'O modelo puro do laboratorio nao foi exposto ao teste.');

const cohort = model.buildSyntheticCohort('detectable');
assert.strictEqual(cohort.length, 50);
assert.strictEqual(cohort.filter((record) => record.t10Responded).length, 43);
assert.strictEqual(cohort.filter((record) => record.t30Responded).length, 38);
assert(cohort.every((record) => !record.t30Responded || record.t10Responded), 'T30 deve ser subconjunto de T10.');

const signals = model.buildSignals(cohort);
assert.strictEqual(signals.length, 3);
const school = signals.find((signal) => signal.key === 'event:escola-aurora');
assert(school);
assert.strictEqual(school.stage, 'T10');
assert.strictEqual(school.directCases, 3, 'O sinal T10 deve usar apenas quem respondeu T10.');
assert.strictEqual(school.stageCoverage, '3/4');

const cheese = signals.find((signal) => signal.key === 'food:queijo-feira-central');
assert.strictEqual(cheese.finalSourceState, 'Aparentemente interrompida');
assert.strictEqual(cheese.statusClass, 'is-closed');
assert(cheese.status.includes('sem novos casos conhecidos'));

function record(overrides) {
  return Object.assign({
    exposureKey: 'test:shared',
    exposureLabel: 'Exposicao teste',
    exposureDomain: 'Ambiente/água',
    specificity: 'specific',
    exposurePlace: 'Local teste',
    exposureDateKnown: true,
    onsetDay: 1,
    reportedOthers: 0,
    t10Responded: false,
    t30Responded: false,
    sourceActiveT10: null,
    sourceStateT30: null,
    actionObservedT30: false,
    postActionCases: null,
    discoverAt: 'T0',
    windowDays: 7,
    sinanVisible: false,
    potentialExposed: 0,
    decisions: []
  }, overrides || {});
}

assert.strictEqual(
  model.buildSignals([record({ reportedOthers: 1 })]).length,
  1,
  'Um caso indice mais um coadoecido relatado deve gerar candidato.'
);
assert.strictEqual(
  model.buildSignals([record({ onsetDay: 1 }), record({ onsetDay: 8 })]).length,
  1,
  'A fronteira inclusiva de sete dias deve ser aceita.'
);
assert.strictEqual(
  model.buildSignals([record({ onsetDay: 1 }), record({ onsetDay: 9 })]).length,
  0,
  'Oito dias de diferenca devem exceder a janela de sete dias.'
);

const eventWithoutFollowup = cohort.map((item) => Object.assign({}, item, {
  t10Responded: false,
  t30Responded: false
}));
assert(!model.buildSignals(eventWithoutFollowup).some((signal) => signal.key === 'event:escola-aurora'));

const [zeroLow, zeroHigh] = model.wilsonInterval(0, 50, 1.96);
const [halfLow, halfHigh] = model.wilsonInterval(25, 50, 1.96);
const [allLow, allHigh] = model.wilsonInterval(50, 50, 1.96);
assert(Math.abs(zeroLow - 0) < 1e-9 && Math.abs(zeroHigh - 0.07135) < 0.001);
assert(Math.abs(halfLow - 0.3664) < 0.001 && Math.abs(halfHigh - 0.6336) < 0.001);
assert(Math.abs(allLow - 0.92865) < 0.001 && Math.abs(allHigh - 1) < 1e-9);

const decisions = model.registeredDecisions(signals);
assert.strictEqual(decisions.length, 6);
assert(decisions.every((decision) => decision.id && decision.status && decision.owner && decision.reportContribution));

console.log('SFA instrument lab model checks passed');
