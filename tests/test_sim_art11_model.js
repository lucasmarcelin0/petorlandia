// Checklist do art. 11 no Portal SIM: situação de cada documento e pendências. Uso: node tests/test_sim_art11_model.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'sim_portal', 'app.js'), 'utf8');

// O app.js é um script de navegador sem módulos: recorta só as declarações testadas.
function declaration(marker) {
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `${marker} não encontrado em static/sim_portal/app.js`);
  let depth = 0;
  for (let k = start; k < source.length; k++) {
    const ch = source[k];
    if (ch === '{' || ch === '[') depth++;
    if (ch === '}' || ch === ']') {
      depth--;
      if (depth === 0) return source.slice(start, k + 1);
    }
  }
  throw new Error(`${marker} sem fechamento`);
}

const code = [
  'const ART11_ITEMS = [',
  'function docReceived(doc) {',
  'function art11Docs() {',
  'function docSituation(doc) {',
  'function art11Progress() {',
  'function art11Checklist() {',
  'function art11Pending() {',
].map(declaration).join(';\n');
const model = new Function('state', `${code};\nreturn { ART11_ITEMS, docSituation, art11Progress, art11Checklist, art11Pending };`);

const doc = (id, extra = {}) => ({ id, group: 'art11', required: true, status: 'Pendente', versions: [], ...extra });
const file = [{ id: 'u1', versionNo: 1 }];
const state = {
  documents: [
    doc('requerimento-assinado', { versions: file }),                                // enviado, SIM ainda não conferiu
    doc('plantas-baixas', { status: 'Recebido', versions: file }),
    doc('contrato-social-cnpj'),
    doc('cpf-cnpj', { status: 'Recebido' }),                                         // legado: status sem versões
    doc('certidoes-ambientais', { status: 'Em correcao', versions: file }),          // devolvido pelo SIM
    doc('registro-crmv', { required: false }),
    doc('comprovante-taxa', { required: false, status: 'Dispensado em 2026' }),
    { id: 'doc-responsavel-legal', group: 'anexos', required: true, status: 'Pendente', versions: [] },
  ],
};
const { ART11_ITEMS, docSituation, art11Progress, art11Checklist, art11Pending } = model(state);
const situation = (id) => docSituation(state.documents.find((item) => item.id === id)).key;

assert.equal(situation('contrato-social-cnpj'), 'missing');
assert.equal(situation('requerimento-assinado'), 'sent');
assert.equal(situation('cpf-cnpj'), 'sent');
assert.equal(situation('registro-crmv'), 'optional');
assert.equal(situation('comprovante-taxa'), 'waived');
// Arquivo devolvido pelo SIM não pode aparecer como entregue para o estabelecimento.
assert.equal(situation('certidoes-ambientais'), 'corrections');

assert.deepEqual(art11Progress(), { sent: 3, total: 5 }, 'documento em correção não conta como enviado');
assert.deepEqual(art11Pending().map((item) => item.inciso), ['III', 'VII'], 'pendências na ordem da lei');
assert.deepEqual(art11Checklist().map((item) => item.inciso), ['I', 'II', 'III', 'IV', 'VII', 'XI', 'XII']);
assert.equal(ART11_ITEMS.length, 12);

console.log('checklist do art. 11: ok');
