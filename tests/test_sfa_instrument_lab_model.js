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
  `  return;
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
assert(cohort.every((record) => !record.ialSampleCollected || record.ialEligible));
assert(cohort.every((record) => !record.ialValidResult || record.ialSampleCollected));
assert(cohort.every((record) => !record.ialEtiologyPositive || record.ialValidResult));

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
    linkComplete: true,
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
    defaultReviewStatus: 'pending',
    matchReason: 'Mesma fonte e janela temporal.',
    matchConfidence: 0.8,
    decisions: []
  }, overrides || {});
}

assert.strictEqual(
  model.buildSignals([record({ reportedOthers: 1 })]).length,
  1,
  'Um caso indice mais um coadoecido relatado deve gerar candidato.'
);
const reportedOnly = model.buildSignals([record({ reportedOthers: 3 })])[0];
assert.strictEqual(reportedOnly.directCases, 1, 'Coadoecidos relatados não podem ser somados como participantes únicos.');
assert.strictEqual(reportedOnly.reportedOthers, 3);
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

const expectedScenarios = {
  semantic: { t10: 45, t30: 41 },
  falsefriends: { t10: 44, t30: 39 },
  onehealth: { t10: 46, t30: 42 }
};
Object.entries(expectedScenarios).forEach(([scenarioKey, expected]) => {
  const scenarioCohort = model.buildSyntheticCohort(scenarioKey);
  assert.strictEqual(scenarioCohort.length, 50, `${scenarioKey} deve manter n=50.`);
  assert.strictEqual(scenarioCohort.filter((item) => item.t10Responded).length, expected.t10);
  assert.strictEqual(scenarioCohort.filter((item) => item.t30Responded).length, expected.t30);
  assert(scenarioCohort.every((item) => !item.t30Responded || item.t10Responded), `${scenarioKey}: T30 deve estar contido em T10.`);
});

const semanticCohort = model.buildSyntheticCohort('semantic');
let semanticSignals = model.buildSignals(semanticCohort);
assert.strictEqual(semanticSignals.length, 1, 'Descrições semanticamente equivalentes devem gerar uma sugestão única.');
assert.strictEqual(semanticSignals[0].key, 'food:queijo-minas-banca-primavera');
assert.strictEqual(semanticSignals[0].directCases, 6);
assert.strictEqual(semanticSignals[0].reviewStatus, 'pending');
assert(semanticSignals[0].matchReason && semanticSignals[0].normalizedLabel);
assert(semanticSignals[0].confidence > 0 && semanticSignals[0].confidence <= 1);
assert.strictEqual(model.registeredDecisions(semanticSignals).length, 0, 'Pendente não pode contar como decisão.');

model.acceptSignal(semanticSignals[0].key, 'semantic');
semanticSignals = model.buildSignals(semanticCohort, model.reviewOverridesFor('semantic'));
assert.strictEqual(semanticSignals[0].reviewStatus, 'accepted');
assert.strictEqual(model.registeredDecisions(semanticSignals).length, 1, 'Aceito e acionável pode contar decisão registrada.');
model.rejectSignal(semanticSignals[0].key, 'semantic');
semanticSignals = model.buildSignals(semanticCohort, model.reviewOverridesFor('semantic'));
assert.strictEqual(semanticSignals[0].reviewStatus, 'rejected');
assert.strictEqual(model.registeredDecisions(semanticSignals).length, 0, 'Rejeitado não pode contar como decisão.');

const falseFriendSignals = model.buildSignals(model.buildSyntheticCohort('falsefriends'));
assert.strictEqual(falseFriendSignals.length, 1);
assert.strictEqual(falseFriendSignals[0].sourceConsistent, false);
assert.strictEqual(falseFriendSignals[0].actionable, false, 'Fontes distintas não devem ser acionáveis como um único sinal.');

const oneHealthSignals = model.buildSignals(model.buildSyntheticCohort('onehealth'));
assert.strictEqual(oneHealthSignals.length, 1);
assert.strictEqual(oneHealthSignals[0].domain, 'Animal/rural');
assert.strictEqual(oneHealthSignals[0].active, true);
assert.strictEqual(oneHealthSignals[0].reviewStatus, 'pending');

const funnel = model.buildFunnel(cohort, signals);
assert.deepStrictEqual(funnel.map((step) => step.key), [
  'cohort', 'new-information', 'complete-links', 'candidate-signals',
  'validated-signals', 'actionable-signals', 'decisions'
]);
assert.strictEqual(funnel[0].value, 50);
assert.strictEqual(funnel[funnel.length - 1].value, decisions.length);
assert(funnel.find((step) => step.key === 'complete-links').value <= funnel.find((step) => step.key === 'new-information').value);

const ial = model.buildIalSummary(cohort);
assert.deepStrictEqual(ial.map((step) => step.value), [36, 31, 29, 12]);
assert(ial.every((step) => step.value <= step.denominator));

const utility = model.buildQuestionUtility();
assert(utility.some((row) => row.imported && row.seconds === 0));
assert(utility.some((row) => row.question === 'O que exatamente pode ter sido compartilhado?' && row.roleModifier === 'is-core'));
assert(!model.stages.t10.sections.flatMap((section) => section.questions).some((item) => item.id === 'lost_income'));
assert(!model.stages.t30.sections.flatMap((section) => section.questions).some((item) => item.id === 'lost_income'));
assert(model.stages.t10.sections.flatMap((section) => section.questions).some((item) => item.id === 'lost_income_any'));
assert.strictEqual((source.match(/<div class="sfa-lab__comparison-row">/g) || []).length, 1, 'Cada linha comparativa deve abrir apenas um contêiner.');

console.log('SFA instrument lab model checks passed');
