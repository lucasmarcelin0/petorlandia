// Confere a busca do navegador contra o que o servidor devolveu para as mesmas consultas.
// Uso: node tests/test_atlas_search_model.js <fixture.json>  (gerado por test_entomologia_atlas_search.py)
const assert = require('node:assert/strict');
const fs = require('node:fs');
const model = require('../static/js/sfa_atlas_search_model.js');

const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const keys = (index, rows) => rows.map(e => [index.layers[e[0]].id, e[1]]);

for (const [text, expected] of fixture.texts) {
  assert.equal(model.searchText(text), expected, 'searchText(' + JSON.stringify(text) + ')');
}
let compared = 0;
for (const variant of fixture.variants) {
  for (const [query, expected] of variant.queries) {
    const got = keys(variant.index, model.search(variant.index, query));
    assert.deepEqual(got, expected, 'consulta ' + JSON.stringify(query) + ' (' + variant.name + ')');
    compared++;
  }
}
// Consulta vazia, longa demais ou só espaços não devolvem nada, como no servidor.
assert.deepEqual(model.search(fixture.variants[0].index, ''), []);
assert.deepEqual(model.search(fixture.variants[0].index, '   '), []);
assert.deepEqual(model.search(fixture.variants[0].index, 'a'.repeat(241)), []);
// Fronteira de palavra e de número sem "lookbehind".
assert.equal(model.containsBounded('rua 12 centro', 'rua 12', c => c !== undefined && /\w/.test(c)), true);
assert.equal(model.containsBounded('rua 123', 'rua 12', c => c !== undefined && /\w/.test(c)), false);
assert.equal(model.containsBounded('rua 1 e rua 12', 'rua 12', c => c !== undefined && /\w/.test(c)), true);
console.log('ok: ' + compared + ' consultas e ' + fixture.texts.length + ' textos iguais ao servidor');
