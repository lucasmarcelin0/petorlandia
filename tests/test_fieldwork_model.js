const assert = require('assert');

// Mock localStorage
const store = {};
global.localStorage = {
  getItem: k => store[k] || null,
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
  clear: () => { Object.keys(store).forEach(k => delete store[k]); },
};

const M = require('../static/js/sfa_fieldwork_model.js');

assert(M, 'SfaFieldworkModel deve ser exposto globalmente');

// 1. Testa salvar e recuperar quarteirões
const block = M.saveBlock('028', '524', { cor: '#bbf7d0', responsavel: 'Lucas' });
assert.strictEqual(block.setor, '028');
assert.strictEqual(block.quarteirao, '524');
assert.strictEqual(block.cor, '#bbf7d0');

const allBlocks = M.getBlocks();
assert.strictEqual(allBlocks['028-524'].responsavel, 'Lucas');

// 2. Testa salvar visitas
const v1 = M.saveVisit({
  setor: '028',
  quarteirao: '524',
  logradouro: 'Rua 12',
  numero: '450',
  situacao: 'ABERTA',
  criadouros: ['A1', 'B'],
  larvas: false,
});
assert(v1.uuid_local);
assert.strictEqual(M.getVisits().length, 1);
assert.strictEqual(M.getPendingQueue().length, 1);

// 3. Testa resumo de quadra
const summary = M.summarizeBlock('028', '524', 10);
assert.strictEqual(summary.totalVisits, 1);
assert.strictEqual(summary.abertas, 1);
assert.strictEqual(summary.pct, 10);

// 4. Testa gamificação
const game = M.computeGamification(M.getVisits(), allBlocks);
assert(game.pontos >= 60, 'Pontos devem somar visita e criadouros');
assert(game.badges.some(b => b.id === 'primeiro_passo'));

// 5. Testa marcação de sincronização
M.markSynced([v1.uuid_local]);
assert.strictEqual(M.getPendingQueue().length, 0);

// 6. Testa exportação para CSV
const csv = M.toCSV(M.getVisits());
assert(csv.includes('Rua 12'));
assert(csv.includes('450'));
assert(csv.includes('ABERTA'));

console.log('✅ Todos os testes de unidade de SfaFieldworkModel passaram com sucesso!');
