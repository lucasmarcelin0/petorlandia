/* Seletores de posologia: os campos de texto continuam sendo o contrato da receita. */
(function (global) {
  'use strict';
  const doseUnits = [
    ['comprimido', 'comprimidos'], ['cápsula', 'cápsulas'], ['mL', 'mL'],
    ['g', 'g'], ['mg', 'mg'], ['mcg', 'mcg'], ['gota', 'gotas'],
    ['pipeta', 'pipetas'], ['sachê', 'sachês'], ['aplicação', 'aplicações'], ['UI', 'UI'],
  ];
  const timeUnits = [['minuto', 'minutos'], ['hora', 'horas'], ['dia', 'dias'],
    ['semana', 'semanas'], ['mês', 'meses']];
  const definitions = [
    { id: 'dose', label: 'Quantidade da dose', units: doseUnits,
      values: ['0,25', '0,5', '0,75', '1', '1,5', '2', '2,5', '3', '4', '5', '6', '8', '10', '15', '20'] },
    { id: 'frequencia', label: 'Intervalo: a cada', units: timeUnits,
      values: ['1', '2', '3', '4', '6', '8', '12', '24', '30', '48', '72'], special: ['unica', 'Dose única'] },
    { id: 'duracao', label: 'Duração: por', units: timeUnits,
      values: ['1', '2', '3', '4', '5', '7', '10', '14', '15', '21', '28', '30', '60', '90'], special: ['continuo', 'Uso contínuo'] },
  ];
  const unitNames = { mL: ['mililitro', 'mililitros'], g: ['grama', 'gramas'],
    mg: ['miligrama', 'miligramas'], mcg: ['micrograma', 'microgramas'],
    UI: ['unidade internacional', 'unidades internacionais'] };

  function number(value) {
    const raw = String(value).trim();
    if (!/^\d+(?:[.,]\d{1,6})?$/.test(raw)) return null;
    const n = Number(raw.replace(',', '.'));
    return Number.isFinite(n) && n > 0 && n <= 999999 ? n : null;
  }
  function written(n) {
    const ext = global.NumeroExtenso.numeroPorExtenso;
    if (Number.isInteger(n)) return ext(n);
    // Não arredondar 0,125 para 0,13 nem transformar 0,33 em um terço.
    const [integer, decimal] = String(n).split('.');
    return `${ext(Number(integer))} vírgula ${decimal.split('').map(d => ext(Number(d))).join(' ')}`;
  }
  function format(id, value, unit) {
    const def = definitions.find(item => item.id === id);
    if (def.special && unit === def.special[0]) return def.special[1].toLowerCase();
    const n = number(value);
    const pair = def.units.find(item => item[0] === unit);
    if (n === null || !pair) return '';
    const plural = n === 1 ? 0 : 1;
    const prefix = id === 'frequencia' ? 'a cada ' : id === 'duracao' ? 'por ' : '';
    return `${prefix}${String(n).replace('.', ',')} ${pair[plural]} (${written(n)} ${(unitNames[unit] || pair)[plural]})`;
  }
  function parse(id, text) {
    const def = definitions.find(item => item.id === id);
    if (!text.trim()) return { value: '', unit: '' };
    if (def.special && text.toLowerCase() === def.special[1].toLowerCase()) {
      return { value: '', unit: def.special[0] };
    }
    const match = text.trim().match(/^(?:a cada |por )?(\d+(?:[.,]\d+)?)\s+([^()]+?)(?:\s+\(([^()]+)\))?$/i);
    if (!match || number(match[1]) === null) return null;
    // Só interpretar a sintaxe do campo correto; preservar instruções importadas.
    if ((id === 'dose' && /^(a cada|por) /i.test(text)) ||
        (id === 'frequencia' && /^por /i.test(text)) ||
        (id === 'duracao' && /^a cada /i.test(text))) return null;
    const pair = def.units.find(item => item.some(u => u.toLowerCase() === match[2].trim().toLowerCase()));
    if (!pair) return null;
    if (match[3]) {
      const expected = format(id, match[1], pair[0]).match(/\((.*)\)$/)[1];
      if (match[3].toLowerCase() !== expected.toLowerCase()) return null;
    }
    return { value: String(number(match[1])).replace('.', ','), unit: pair[0] };
  }

  function mount(document) {
    if (!global.NumeroExtenso) return null;
    const groups = definitions.map(def => {
      const target = document.getElementById(def.id);
      const panel = document.createElement('div');
      panel.className = 'posologia-selectors';
      function element(tag, props) {
        const el = document.createElement(tag);
        Object.assign(el, props);
        return el;
      }
      const quantity = element('select', { id: `${def.id}-quantidade`, className: 'form-select' });
      quantity.setAttribute('aria-label', def.label);
      quantity.add(new Option('Quantidade', ''));
      def.values.forEach(value => quantity.add(new Option(value, value)));
      quantity.add(new Option('Outro valor…', 'outro'));
      const other = element('input', { id: `${def.id}-valor`, type: 'text', className: 'form-control', hidden: true });
      other.inputMode = 'decimal';
      other.placeholder = 'Ex.: 0,125';
      other.setAttribute('aria-label', `${def.label}: outro valor`);
      const unit = element('select', { id: `${def.id}-unidade`, className: 'form-select' });
      unit.setAttribute('aria-label', def.id === 'dose' ? 'Unidade da dose' : `Unidade de tempo: ${def.id}`);
      unit.add(new Option(def.id === 'dose' ? 'Unidade' : 'Tempo', ''));
      def.units.forEach(pair => unit.add(new Option(pair[0], pair[0])));
      if (def.special) unit.add(new Option(def.special[1], def.special[0]));
      const row = element('div', { className: 'posologia-selectors__row' });
      row.append(quantity, unit);
      const hint = element('small', { className: 'text-muted d-block mt-1', textContent: def.label });
      const fallback = element('div', { hidden: true, className: 'mt-1' });
      const note = element('small', { className: 'text-muted d-block', textContent: 'Orientação recebida preservada. Para substituir:' });
      const replace = element('button', { type: 'button', className: 'btn btn-sm btn-outline-secondary mt-1', textContent: 'Usar quantidade e unidade' });
      fallback.append(note, replace);
      panel.append(row, other, hint, fallback);
      target.before(panel);
      const label = document.querySelector(`label[for="${def.id}"]`);
      let lastText;
      function sync() {
        if (lastText === target.value) return;
        lastText = target.value;
        const parsed = parse(def.id, target.value);
        const custom = !parsed;
        target.hidden = !custom;
        fallback.hidden = !custom;
        row.hidden = custom;
        hint.hidden = custom;
        label.htmlFor = custom ? def.id : quantity.id;
        other.setCustomValidity('');
        if (custom) { other.hidden = true; return; }
        unit.value = parsed.unit;
        quantity.value = !parsed.value || def.values.includes(parsed.value) ? parsed.value : 'outro';
        other.value = parsed.value;
        other.hidden = quantity.value !== 'outro';
        quantity.disabled = !!def.special && unit.value === def.special[0];
        if (quantity.disabled) other.hidden = true;
      }
      function update(event) {
        other.hidden = quantity.value !== 'outro';
        const special = !!def.special && unit.value === def.special[0];
        quantity.disabled = special;
        if (special) other.hidden = true;
        const value = quantity.value === 'outro' ? other.value : quantity.value;
        const error = !special && quantity.value === 'outro' && other.value && number(value) === null;
        other.setCustomValidity(error ? 'Informe um número maior que zero, com até 6 casas decimais (ex.: 0,5).' : '');
        lastText = format(def.id, value, unit.value);
        target.value = lastText;
        target.dispatchEvent(new Event('input', { bubbles: true }));
        if (event && event.target === quantity && quantity.value === 'outro') other.focus();
      }
      quantity.addEventListener('change', update);
      unit.addEventListener('change', update);
      other.addEventListener('input', update);
      target.addEventListener('input', sync);
      replace.addEventListener('click', () => { target.value = ''; lastText = undefined; sync(); update(); quantity.focus(); });
      sync();
      return { sync, validate: () => target.hidden && !other.hidden ? other.reportValidity() : true };
    });
    return { sync: () => groups.forEach(group => group.sync()), validate: () => groups.every(group => group.validate()) };
  }
  global.PosologiaEstruturada = { format, parse, number, mount };
})(typeof window !== 'undefined' ? window : globalThis);
