const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.join(__dirname, '..', 'templates/partials/prescricao_form.html'), 'utf8');

function environment() {
  const state = { pending: [], rendered: [] };
  const input = new EventTarget();
  input.value = '';
  const sugestoes = { style: { display: 'none' }, children: [], innerHTML: '' };
  const context = vm.createContext({
    input, sugestoes, AbortController, console,
    sugestaoDoseAtual: null, fecharSugestaoDose() {},
    _medicationSearchController: null, _medicationSearchSeq: 0, _activeMedItemIndex: -1,
    _medicationCatalogPool: new Map(), _medicationSearchCache: new Map(),
    _cacheGet: (map, key) => map.get(key), _medicationSearchCacheKey: q => q,
    debounce: callback => callback,
    _renderizarSugestoesPrescricao(data) {
      state.rendered = Array.from(data);
      sugestoes.innerHTML = data.map(item => item.nome).join('|');
      sugestoes.style.display = 'block';
      sugestoes.children = data;
    },
    _buscarMedicamentosAutocomplete(q) {
      return new Promise(resolve => state.pending.push({ q, resolve }));
    },
  });
  const poolCode = template.slice(template.indexOf('    function _armazenarNoPoolMedicamentos'), template.indexOf('  // === MEDICAMENTOS FREQUENTES'));
  const eventCode = template.slice(template.indexOf('    // Busca no servidor com debounce'), template.indexOf('    // Navegação via teclado'));
  vm.runInContext(poolCode + eventCode, context);
  function type(value) { input.value = value; input.dispatchEvent(new Event('input')); }
  return { context, state, input, sugestoes, type };
}

const target = { id: 1, nome: 'Shampoo Clorexidina 2%', principio_ativo: 'Clorexidina' };
const neutral = { id: 2, nome: 'Shampoo Neutro', principio_ativo: 'Aloe vera' };
test('pool local ignora preposição e exige forma e princípio ativo juntos', () => {
  const { context } = environment();
  context._armazenarNoPoolMedicamentos([target, neutral]);
  for (const q of ['shampoo de clorexidina', 'clorexidina shampoo', 'SHAMPOO COM CLOREXIDINA', 'shampoo clorexid']) {
    assert.deepEqual(Array.from(context._filtrarMedicamentosDoPool(q), item => item.id), [1]);
  }
});

test('local e servidor mantêm o shampoo encontrado e ignoram resposta antiga', async () => {
  const { context, state, type } = environment();
  context._armazenarNoPoolMedicamentos([target, neutral]);
  type('shampoo');
  type('shampoo de clorexidina');
  assert.deepEqual(state.rendered.map(item => item.id), [1]);
  state.pending[1].resolve([target]);
  await Promise.resolve();
  assert.deepEqual(state.rendered.map(item => item.id), [1]);
  state.pending[0].resolve([neutral]);
  await Promise.resolve();
  assert.deepEqual(state.rendered.map(item => item.id), [1]);
});

test('nova consulta sem cache remove opções da consulta anterior enquanto carrega', () => {
  const { context, type, sugestoes } = environment();
  context._armazenarNoPoolMedicamentos([neutral]);
  type('shampoo');
  assert.match(sugestoes.innerHTML, /Neutro/);
  type('shampoo de clorexidina');
  assert.match(sugestoes.innerHTML, /Buscando/);
  assert.doesNotMatch(sugestoes.innerHTML, /Neutro/);
});

test('limpar consulta impede que resposta pendente reabra a lista', async () => {
  const { state, type, sugestoes } = environment();
  type('clorexidina'); type('');
  state.pending[0].resolve([target]);
  await Promise.resolve();
  assert.equal(sugestoes.style.display, 'none');
});
