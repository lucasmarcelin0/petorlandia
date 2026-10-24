const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function environment() {
  const elements = new Map();
  class Element extends EventTarget {
    constructor(tag = 'input') { super(); this.tag = tag; this.value = ''; this.hidden = false; this.children = []; this.validityMessage = ''; }
    set id(id) { this._id = id; elements.set(id, this); }
    get id() { return this._id; }
    setAttribute(key, value) { this[key] = value; }
    append(...children) { this.children.push(...children); }
    before(el) { this.beforeElement = el; }
    add(option) { this.children.push(option); }
    focus() { this.focused = true; }
    setCustomValidity(message) { this.validityMessage = message; }
    reportValidity() { return !this.validityMessage; }
  }
  const labels = {};
  for (const id of ['dose', 'frequencia', 'duracao']) {
    const el = new Element(); el.id = id; labels[id] = {};
  }
  const document = { getElementById: id => elements.get(id), createElement: tag => new Element(tag),
    querySelector: selector => labels[selector.match(/for="(.*?)"/)[1]] };
  const context = vm.createContext({ document, Event, Option: function (text, value) { this.text = text; this.value = value; } });
  for (const file of ['numero_extenso.js', 'posologia_estruturada.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'js', file), 'utf8'), context);
  }
  const api = context.PosologiaEstruturada;
  const controller = api.mount(document);
  const get = id => document.getElementById(id);
  function change(id, value, event = 'change') { const el = get(id); el.value = value; el.dispatchEvent(new Event(event)); }
  return { api, controller, get, change, labels };
}

test('dose, intervalo e duração usam número, extenso e plural correto', () => {
  const { api } = environment();
  assert.equal(api.format('dose', '1', 'comprimido'), '1 comprimido (um comprimido)');
  assert.equal(api.format('dose', '2', 'comprimido'), '2 comprimidos (dois comprimidos)');
  assert.equal(api.format('frequencia', '8', 'hora'), 'a cada 8 horas (oito horas)');
  assert.equal(api.format('duracao', '7', 'dia'), 'por 7 dias (sete dias)');
  assert.equal(api.format('frequencia', '1', 'minuto'), 'a cada 1 minuto (um minuto)');
  assert.equal(api.format('duracao', '2', 'mês'), 'por 2 meses (dois meses)');
  assert.equal(api.format('dose', '1', 'g'), '1 g (um grama)');
});

test('frações e decimais não sofrem arredondamento nem aproximação por extenso', () => {
  const { api } = environment();
  assert.equal(api.format('dose', '0,5', 'mL'), '0,5 mL (zero vírgula cinco mililitros)');
  assert.equal(api.format('dose', '0.125', 'mL'), '0,125 mL (zero vírgula um dois cinco mililitros)');
  assert.equal(api.format('dose', '0,33', 'comprimido'), '0,33 comprimidos (zero vírgula três três comprimidos)');
  assert.equal(api.format('dose', '1,234567', 'mg'), '1,234567 mg (um vírgula dois três quatro cinco seis sete miligramas)');
  assert.equal(api.format('dose', '0,000001', 'g'), '0,000001 g (zero vírgula zero zero zero zero zero um gramas)');
});

test('valores incompletos ou inválidos nunca geram dose', () => {
  const { api } = environment();
  for (const value of ['', '0', '-1', '1e3', '1/2', '1,2,3', 'Infinity', '0,0000001', '1000000']) {
    assert.equal(api.format('dose', value, 'mL'), '', value);
  }
  assert.equal(api.format('dose', '1', ''), '');
});

test('interpreta apenas texto simples ou extenso coerente e preserva exceções', () => {
  const { api } = environment();
  assert.equal(api.parse('dose', '1 comprimido (um comprimido)').value, '1');
  assert.equal(api.parse('frequencia', 'a cada 8 horas (oito horas)').unit, 'hora');
  for (const text of ['1 comprimido (dois comprimidos)', '1 comprimido (com alimento)',
    '1–2 comprimidos', 'meio comprimido', '1 mL, após alimentação', 'a cada 1 comprimido']) {
    assert.equal(api.parse('dose', text), null, text);
  }
});

test('seleções atualizam os campos usados na prévia e na receita', () => {
  const { get, change, labels } = environment();
  change('dose-quantidade', '1');
  assert.equal(get('dose').value, '');
  change('dose-unidade', 'comprimido');
  change('frequencia-quantidade', '8'); change('frequencia-unidade', 'hora');
  change('duracao-quantidade', '7'); change('duracao-unidade', 'dia');
  assert.equal(get('dose').value, '1 comprimido (um comprimido)');
  assert.equal(get('frequencia').value, 'a cada 8 horas (oito horas)');
  assert.equal(get('duracao').value, 'por 7 dias (sete dias)');
  assert.equal(get('dose').hidden, true);
  assert.equal(labels.dose.htmlFor, 'dose-quantidade');
});

test('outro valor permite digitar decimal e valida entrada sem reaproveitar dose anterior', () => {
  const { get, change, controller } = environment();
  change('dose-unidade', 'mL'); change('dose-quantidade', 'outro');
  change('dose-valor', '0,125', 'input');
  assert.equal(get('dose').value, '0,125 mL (zero vírgula um dois cinco mililitros)');
  change('dose-valor', '-1', 'input');
  assert.equal(get('dose').value, '');
  assert.equal(controller.validate(), false);
  change('dose-valor', '1,5', 'input');
  assert.equal(controller.validate(), true);
  assert.equal(get('dose').value, '1,5 mL (um vírgula cinco mililitros)');
});

test('bulário, limpeza e orientação complexa sincronizam sem alterar o texto recebido', () => {
  const { get, controller, change } = environment();
  get('dose').value = '0,125 mL'; controller.sync();
  assert.equal(get('dose-quantidade').value, 'outro');
  assert.equal(get('dose-valor').value, '0,125');
  assert.equal(get('dose').value, '0,125 mL');
  get('dose').value = '1 a 2 comprimidos, com alimento'; controller.sync();
  assert.equal(get('dose').hidden, false);
  assert.equal(get('dose').value, '1 a 2 comprimidos, com alimento');
  get('dose').value = ''; controller.sync();
  assert.equal(get('dose-quantidade').value, '');
  assert.equal(get('dose-unidade').value, '');
  assert.equal(get('dose').hidden, true);
  change('dose-quantidade', '1'); controller.sync();
  assert.equal(get('dose-quantidade').value, '1', 'não limpar seleção parcial durante a prévia');
});

test('dose única e uso contínuo dispensam quantidade e podem voltar para intervalo', () => {
  const { get, change } = environment();
  change('frequencia-unidade', 'unica');
  assert.equal(get('frequencia').value, 'dose única');
  assert.equal(get('frequencia-quantidade').disabled, true);
  change('duracao-unidade', 'continuo');
  assert.equal(get('duracao').value, 'uso contínuo');
  change('frequencia-unidade', 'hora');
  assert.equal(get('frequencia-quantidade').disabled, false);
  assert.equal(get('frequencia').value, '');
});
