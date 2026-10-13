/**
 * Datas sempre no padrão brasileiro: dd/mm/aaaa.
 *
 * O <input type="date"> nativo (e também datetime-local e month) é desenhado
 * no idioma do NAVEGADOR, não no lang da página: num Chrome em inglês ele
 * aparece como "mm/dd/yyyy" mesmo com <html lang="pt-BR">, e não existe
 * atributo que mude isso. Então cada um desses campos ganha um espelho de
 * texto em dd/mm/aaaa (com calendário em português), e o campo original fica
 * no DOM, escondido, com o mesmo id/name e o valor ISO (aaaa-mm-dd). Nenhuma
 * tela precisa mudar:
 *
 * - `campo.value` continua lendo e escrevendo ISO, e o espelho acompanha;
 * - `input`/`change` continuam disparando no campo original;
 * - o formulário continua enviando ISO pelo `name` original;
 * - checkValidity()/reportValidity()/focus() do original respondem pelo espelho.
 *
 * Carregado por todos os layouts. tests/test_datas_formato_brasileiro.py
 * falha se alguma página com campo de data deixar de carregar este arquivo;
 * tests/test_date_br.js cobre as conversões e tests/test_date_br_browser.py
 * exercita o componente num Chromium configurado em inglês.
 */
(function (global) {
  'use strict';

  // ---------------------------------------------------------------------------
  // Conversões (funções puras, sem DOM)
  // ---------------------------------------------------------------------------

  const KINDS = {
    date: {
      placeholder: 'dd/mm/aaaa',
      digits: 8,
      groups: [2, 2, 4],
      yearGroup: 2,
      separators: ['/', '/'],
      title: 'Data no formato dd/mm/aaaa',
      invalid: 'Informe uma data válida no formato dd/mm/aaaa.',
      missing: 'Informe a data (dd/mm/aaaa).',
      subject: 'uma data',
    },
    'datetime-local': {
      placeholder: 'dd/mm/aaaa hh:mm',
      digits: 12,
      groups: [2, 2, 4, 2, 2],
      yearGroup: 2,
      separators: ['/', '/', ' ', ':'],
      title: 'Data e hora no formato dd/mm/aaaa hh:mm (24 horas)',
      invalid: 'Informe data e hora válidas no formato dd/mm/aaaa hh:mm.',
      missing: 'Informe a data e a hora (dd/mm/aaaa hh:mm).',
      subject: 'data e hora',
    },
    month: {
      placeholder: 'mm/aaaa',
      digits: 6,
      groups: [2, 4],
      yearGroup: 1,
      separators: ['/'],
      title: 'Mês no formato mm/aaaa',
      invalid: 'Informe um mês válido no formato mm/aaaa.',
      missing: 'Informe o mês (mm/aaaa).',
      subject: 'um mês',
    },
  };

  const MONTH_NAMES = [
    'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
    'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
  ];

  const ISO_RE = {
    date: /^(\d{4,6})-(\d{2})-(\d{2})$/,
    'datetime-local': /^(\d{4,6})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,3})?)?$/,
    month: /^(\d{4,6})-(\d{2})$/,
  };

  // Como a pessoa digita/cola: dia e mês com 1 ou 2 dígitos, ano com 4.
  const TYPED_RE = {
    date: /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/,
    'datetime-local': /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:\s*,\s*|\s+|T)(\d{1,2})[:h](\d{2})$/,
    month: /^(\d{1,2})[/.-](\d{4})$/,
  };

  function isKind(kind) {
    return Object.prototype.hasOwnProperty.call(KINDS, kind);
  }

  function pad(value, size) {
    return String(value).padStart(size || 2, '0');
  }

  function isLeapYear(year) {
    return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  }

  function daysInMonth(year, month) {
    return [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  }

  /** Motivo de a data ser impossível, ou '' se ela existe no calendário. */
  function impossibility(parts) {
    if (!(parts.m >= 1 && parts.m <= 12)) {
      return 'Mês inválido: use de 01 a 12.';
    }
    if (parts.d !== undefined) {
      const max = daysInMonth(parts.y, parts.m);
      if (!(parts.d >= 1 && parts.d <= max)) {
        return `Dia inválido: ${MONTH_NAMES[parts.m - 1]} de ${parts.y} tem ${max} dias.`;
      }
    }
    if (parts.hh !== undefined && !(parts.hh >= 0 && parts.hh <= 23 && parts.mi >= 0 && parts.mi <= 59)) {
      return 'Hora inválida: use de 00:00 a 23:59.';
    }
    return '';
  }

  /** Valor técnico (ISO, como o <input> nativo usa) -> partes, ou null. */
  function parseIso(kind, iso) {
    const match = isKind(kind) ? ISO_RE[kind].exec(String(iso == null ? '' : iso).trim()) : null;
    if (!match) {
      return null;
    }
    const parts = { y: Number(match[1]), m: Number(match[2]) };
    if (kind !== 'month') {
      parts.d = Number(match[3]);
    }
    if (kind === 'datetime-local') {
      parts.hh = Number(match[4]);
      parts.mi = Number(match[5]);
      parts.ss = match[6] ? Number(match[6]) : 0;
    }
    if (parts.y < 1 || impossibility(parts) || (parts.ss !== undefined && parts.ss > 59)) {
      return null;
    }
    return parts;
  }

  function partsToIso(kind, parts) {
    const year = pad(parts.y, 4);
    if (kind === 'month') {
      return `${year}-${pad(parts.m)}`;
    }
    const day = `${year}-${pad(parts.m)}-${pad(parts.d)}`;
    return kind === 'datetime-local' ? `${day}T${pad(parts.hh)}:${pad(parts.mi)}` : day;
  }

  /** ISO -> texto brasileiro (dd/mm/aaaa, dd/mm/aaaa hh:mm ou mm/aaaa). */
  function toDisplay(kind, iso) {
    const parts = parseIso(kind, iso);
    if (!parts) {
      return '';
    }
    const year = pad(parts.y, 4);
    if (kind === 'month') {
      return `${pad(parts.m)}/${year}`;
    }
    const day = `${pad(parts.d)}/${pad(parts.m)}/${year}`;
    return kind === 'datetime-local' ? `${day} ${pad(parts.hh)}:${pad(parts.mi)}` : day;
  }

  /**
   * Texto digitado -> { iso, error }.
   *
   * iso '' com error null significa campo vazio. Datas impossíveis (31/02)
   * são recusadas com motivo, nunca "roladas" para o mês seguinte como faz
   * `new Date(2026, 1, 31)`.
   */
  function parseTyped(kind, text) {
    const raw = String(text == null ? '' : text).trim();
    if (!raw || !isKind(kind)) {
      return { iso: '', error: null };
    }
    const spec = KINDS[kind];
    // Colar uma data técnica (2026-09-22) também vale.
    const iso = parseIso(kind, raw);
    if (iso && iso.y >= 1000) {
      return { iso: partsToIso(kind, iso), error: null };
    }
    const match = TYPED_RE[kind].exec(raw);
    if (!match) {
      return { iso: '', error: spec.invalid };
    }
    const parts = kind === 'month'
      ? { m: Number(match[1]), y: Number(match[2]) }
      : { d: Number(match[1]), m: Number(match[2]), y: Number(match[3]) };
    if (kind === 'datetime-local') {
      parts.hh = Number(match[4]);
      parts.mi = Number(match[5]);
    }
    if (parts.y < 1000) {
      return { iso: '', error: 'Ano inválido: use quatro dígitos (por exemplo, 2026).' };
    }
    const problem = impossibility(parts);
    if (problem) {
      return { iso: '', error: problem };
    }
    return { iso: partsToIso(kind, parts), error: null };
  }

  /**
   * Máscara enquanto digita. Aceita só dígitos e põe as barras sozinha
   * ("22092026" -> "22/09/2026"); quem digita a barra depois de um dígito
   * ("1/2/2026") ganha o zero à esquerda em vez de ter os dígitos embaralhados.
   */
  function maskTyping(kind, raw) {
    if (!isKind(kind)) {
      return String(raw || '');
    }
    const text = String(raw == null ? '' : raw);
    const pasted = parseTyped(kind, text);
    if (pasted.iso) {
      return toDisplay(kind, pasted.iso);
    }
    const { groups: sizes, separators, yearGroup } = KINDS[kind];
    const done = [];
    let current = '';
    let endsWithSeparator = false;
    const tokens = text.match(/\d+|\D+/g) || [];
    tokens.forEach((token) => {
      if (done.length >= sizes.length) {
        return;
      }
      if (/^\d/.test(token)) {
        endsWithSeparator = false;
        for (const digit of token) {
          if (done.length >= sizes.length) {
            break;
          }
          current += digit;
          if (current.length === sizes[done.length]) {
            done.push(current);
            current = '';
          }
        }
        return;
      }
      endsWithSeparator = true;
      // Separador digitado no meio de um grupo: completa com zero à esquerda
      // (o ano não, ele precisa dos quatro dígitos).
      if (current && done.length !== yearGroup && done.length < sizes.length - 1) {
        done.push(current.padStart(sizes[done.length], '0'));
        current = '';
      }
    });
    let out = '';
    done.forEach((group, index) => {
      out += (index ? separators[index - 1] : '') + group;
    });
    if (current) {
      out += (done.length ? separators[done.length - 1] : '') + current;
    } else if (endsWithSeparator && done.length && done.length < sizes.length) {
      out += separators[done.length - 1];
    }
    return out;
  }

  /** Posição do cursor logo depois do n-ésimo dígito do texto formatado. */
  function caretAfterDigits(text, count) {
    if (count <= 0) {
      return 0;
    }
    let seen = 0;
    for (let index = 0; index < text.length; index += 1) {
      if (/\d/.test(text[index])) {
        seen += 1;
        if (seen === count) {
          return index + 1;
        }
      }
    }
    return text.length;
  }

  /** Chave numérica para comparar valores ISO (min/max) sem depender de fuso. */
  function isoKey(kind, iso) {
    const parts = parseIso(kind, iso);
    if (!parts) {
      return null;
    }
    if (kind === 'month') {
      return parts.y * 100 + parts.m;
    }
    const day = parts.y * 10000 + parts.m * 100 + parts.d;
    return kind === 'datetime-local'
      ? day * 1000000 + parts.hh * 10000 + parts.mi * 100 + parts.ss
      : day;
  }

  /** Mensagem de limite (min/max) em pt-BR, ou ''. */
  function rangeMessage(kind, iso, min, max) {
    const value = isoKey(kind, iso);
    if (value === null) {
      return '';
    }
    const subject = KINDS[kind].subject;
    const lower = isoKey(kind, min);
    if (lower !== null && value < lower) {
      return `Escolha ${subject} a partir de ${toDisplay(kind, min)}.`;
    }
    const upper = isoKey(kind, max);
    if (upper !== null && value > upper) {
      return `Escolha ${subject} até ${toDisplay(kind, max)}.`;
    }
    return '';
  }

  /** ISO -> Date local (sem o deslocamento de fuso de `new Date('aaaa-mm-dd')`). */
  function isoToDate(kind, iso) {
    const parts = parseIso(kind, iso);
    if (!parts) {
      return null;
    }
    const date = new Date(2000, parts.m - 1, parts.d || 1, parts.hh || 0, parts.mi || 0, parts.ss || 0, 0);
    date.setFullYear(parts.y);
    return date;
  }

  /**
   * 'aaaa-mm-dd' (ou com hora) -> Date no fuso local, ou null.
   *
   * Use sempre isto no lugar de `new Date('2026-09-22')`: essa forma é lida
   * como meia-noite em UTC e, no Brasil, vira 21h do dia ANTERIOR — a tela
   * mostra um dia a menos.
   */
  function parseDateLocal(value) {
    if (value instanceof Date) {
      return Number.isNaN(value.getTime()) ? null : value;
    }
    const text = String(value == null ? '' : value).trim();
    return isoToDate('datetime-local', text) || isoToDate('date', text);
  }

  /** Hoje no fuso de quem está usando, em ISO (nunca o "hoje" de UTC). */
  function todayIso() {
    return dateToIso('date', new Date());
  }

  function dateToIso(kind, date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
      return '';
    }
    return partsToIso(kind, {
      y: date.getFullYear(),
      m: date.getMonth() + 1,
      d: date.getDate(),
      hh: date.getHours(),
      mi: date.getMinutes(),
    });
  }

  const api = {
    KINDS,
    toDisplay,
    parseTyped,
    parseIso,
    maskTyping,
    caretAfterDigits,
    rangeMessage,
    isoToDate,
    dateToIso,
    parseDateLocal,
    todayIso,
  };

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (typeof document === 'undefined' || typeof HTMLInputElement === 'undefined') {
    return;
  }

  // ---------------------------------------------------------------------------
  // Componente de página
  // ---------------------------------------------------------------------------

  const SELECTOR = Object.keys(KINDS).map((kind) => `input[type="${kind}" i]`).join(',');
  const PROXY_CLASS = 'date-br-input';
  const NATIVE_CLASS = 'date-br-native';
  // Fica no campo original e sobrevive a cloneNode/innerHTML: diz se ele já era
  // readonly antes de nós, para um clone poder ser restaurado corretamente.
  const MARK = 'data-date-br';
  const MIRRORED_ATTRIBUTES = [
    'class', 'style', 'hidden', 'disabled', 'required', 'readonly', 'title', 'min', 'max',
    'value', 'type', 'form', 'tabindex', 'aria-label', 'aria-describedby', 'aria-invalid',
  ];
  // Teclas que não fecham o calendário aberto (navegação e modificadores).
  const CALENDAR_KEYS = new Set(['ArrowUp', 'ArrowDown', 'Tab', 'Shift', 'Control', 'Alt', 'Meta', 'CapsLock']);

  const LOCALE_PT = {
    weekdays: {
      shorthand: ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'],
      longhand: ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado'],
    },
    months: {
      shorthand: ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'],
      longhand: ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'],
    },
    firstDayOfWeek: 0,
    ordinal: () => '',
    rangeSeparator: ' até ',
    weekAbbreviation: 'Sem',
    scrollTitle: 'Role para alterar',
    toggleTitle: 'Clique para alternar',
    amPM: ['AM', 'PM'],
    yearAriaLabel: 'Ano',
    monthAriaLabel: 'Mês',
    hourAriaLabel: 'Hora',
    minuteAriaLabel: 'Minuto',
    time_24hr: true,
  };

  const proto = HTMLInputElement.prototype;
  const nativeValue = Object.getOwnPropertyDescriptor(proto, 'value');
  const states = new WeakMap();
  const proxyOwners = new WeakMap();
  const scriptSrc = document.currentScript && document.currentScript.src;
  let uid = 0;
  let calendarAssets = null;

  function readValue(input) {
    return nativeValue.get.call(input);
  }

  function kindOf(input) {
    const type = (input.getAttribute('type') || '').toLowerCase();
    return isKind(type) ? type : null;
  }

  function coarsePointer() {
    return typeof global.matchMedia === 'function' && global.matchMedia('(pointer: coarse)').matches;
  }

  function injectStyle() {
    if (document.getElementById('date-br-style')) {
      return;
    }
    const style = document.createElement('style');
    style.id = 'date-br-style';
    style.textContent = [
      `.${NATIVE_CLASS}{display:none!important}`,
      `.${PROXY_CLASS}.${PROXY_CLASS}{padding-right:2.1rem;background-repeat:no-repeat;background-position:right .6rem center;background-size:1rem 1rem;`
        + 'background-image:url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 16 16\' fill=\'%236c757d\'%3E%3Cpath d=\'M3.5 0a.5.5 0 0 1 .5.5V1h8V.5a.5.5 0 0 1 1 0V1h1a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2h1V.5a.5.5 0 0 1 .5-.5M1 4v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V4z\'/%3E%3C/svg%3E")}',
      `.${PROXY_CLASS}.is-invalid{background-image:none}`,
    ].join('\n');
    (document.head || document.documentElement).appendChild(style);
  }

  // --- espelho <-> original ---------------------------------------------------

  function syncAttributes(state) {
    const { input, proxy, kind } = state;
    const spec = KINDS[kind];
    const classes = Array.from(input.classList).filter((name) => name !== NATIVE_CLASS && name !== 'flatpickr-input');
    classes.push(PROXY_CLASS);
    if (state.showError && state.typedError && !classes.includes('is-invalid')) {
      classes.push('is-invalid');
    }
    proxy.className = classes.join(' ');
    proxy.style.cssText = input.style.cssText;
    proxy.hidden = input.hidden;
    proxy.disabled = input.disabled;
    proxy.required = input.required;
    proxy.readOnly = state.readonly;
    proxy.placeholder = spec.placeholder;
    proxy.title = input.getAttribute('title') || spec.title;
    ['form', 'tabindex', 'aria-describedby', 'aria-invalid'].forEach((name) => {
      if (input.hasAttribute(name)) {
        proxy.setAttribute(name, input.getAttribute(name));
      } else {
        proxy.removeAttribute(name);
      }
    });
    if (!proxy.hasAttribute('aria-labelledby') && input.hasAttribute('aria-label')) {
      proxy.setAttribute('aria-label', input.getAttribute('aria-label'));
    }
    const bounds = `${input.getAttribute('min') || ''}|${input.getAttribute('max') || ''}`;
    if (state.fp && bounds !== state.bounds) {
      // fp.set() regrava o texto a partir da data selecionada no calendário;
      // preserva o que a pessoa digitou.
      const text = proxy.value;
      state.fp.set({
        minDate: isoToDate(kind, input.getAttribute('min')),
        maxDate: isoToDate(kind, input.getAttribute('max')),
      });
      if (proxy.value !== text) {
        proxy.value = text;
      }
    }
    state.bounds = bounds;
    updateValidity(state);
  }

  function updateValidity(state) {
    const { input, proxy, kind } = state;
    const iso = readValue(input);
    let message = state.customMessage || state.typedError;
    if (!message && !iso && proxy.required && !proxy.value.trim()) {
      message = KINDS[kind].missing;
    }
    if (!message && iso) {
      message = rangeMessage(kind, iso, input.getAttribute('min'), input.getAttribute('max'));
    }
    proxy.setCustomValidity(message || '');
  }

  function setError(state, message, visible) {
    state.typedError = message || '';
    const show = Boolean(visible && state.typedError);
    if (show !== state.showError) {
      state.showError = show;
      syncAttributes(state);
    } else {
      updateValidity(state);
    }
  }

  /** Valor do original mudou por código: redesenha o texto brasileiro. */
  function render(state) {
    const iso = readValue(state.input);
    const text = toDisplay(state.kind, iso);
    if (state.fp) {
      state.muted = true;
      try {
        const date = isoToDate(state.kind, iso);
        if (date) {
          state.fp.setDate(date, false);
        } else {
          state.fp.clear(false);
        }
      } finally {
        state.muted = false;
      }
    }
    if (state.proxy.value !== text) {
      state.proxy.value = text;
    }
    setError(state, '', false);
  }

  /** Grava ISO no original como o navegador faria (input + change). */
  function commit(state, iso) {
    const { input } = state;
    if (readValue(input) === iso) {
      return;
    }
    nativeValue.set.call(input, iso);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  /**
   * Interpreta o texto do espelho. Durante a digitação só grava data completa
   * e válida: apagar para redigitar não pode esvaziar o campo (um filtro com
   * onchange="this.form.submit()" enviaria vazio). Ao sair do campo (final),
   * texto incompleto ou impossível esvazia o original e mostra o motivo.
   */
  function fromText(state, final) {
    const { proxy, kind } = state;
    const text = proxy.value;
    const result = parseTyped(kind, text);
    if (result.iso) {
      if (final) {
        const canonical = toDisplay(kind, result.iso);
        if (canonical !== text) {
          proxy.value = canonical;
        }
      }
      commit(state, result.iso);
      setError(state, '', false);
      return;
    }
    if (!text.trim()) {
      if (final) {
        commit(state, '');
      }
      setError(state, '', false);
      return;
    }
    const complete = text.replace(/\D/g, '').length >= KINDS[kind].digits;
    if (final) {
      commit(state, '');
    }
    setError(state, result.error || KINDS[kind].invalid, final || complete);
  }

  function onProxyInput(state, event) {
    // A tela só enxerga os eventos do campo original.
    event.stopPropagation();
    const { proxy, kind } = state;
    if (event.isTrusted && state.fp && state.fp.isOpen) {
      state.fp.close();
    }
    const raw = proxy.value;
    const masked = maskTyping(kind, raw);
    if (masked !== raw) {
      const caret = proxy.selectionStart;
      const atEnd = caret === null || caret >= raw.length;
      proxy.value = masked;
      if (document.activeElement === proxy && typeof proxy.setSelectionRange === 'function') {
        const position = atEnd ? masked.length : caretAfterDigits(masked, raw.slice(0, caret).replace(/\D/g, '').length);
        proxy.setSelectionRange(position, position);
      }
    }
    fromText(state, false);
  }

  function onProxyKeydown(state, event) {
    const fp = state.fp;
    if (event.key === 'Enter') {
      fromText(state, true);
      if (fp && fp.isOpen) {
        event.preventDefault();
        fp.close();
      }
      // Sem isto o flatpickr trataria o Enter como "abrir calendário".
      event.stopImmediatePropagation();
      return;
    }
    if (event.key === 'Escape' && fp && fp.isOpen) {
      event.preventDefault();
      event.stopPropagation();
      fp.close();
      return;
    }
    if ((event.key === 'ArrowDown' && event.altKey) || event.key === 'F4') {
      event.preventDefault();
      openCalendar(state);
      return;
    }
    // Digitando com o calendário aberto: fecha antes que o flatpickr use a
    // tecla (Backspace, por exemplo, apagaria a data inteira).
    if (fp && fp.isOpen && !CALENDAR_KEYS.has(event.key)) {
      fp.close();
    }
  }

  function onProxyClick(state, event) {
    const { proxy } = state;
    if (proxy.disabled || proxy.readOnly || (state.fp && state.fp.isOpen)) {
      return;
    }
    // No celular, tocar no texto é para digitar; o calendário abre pelo ícone.
    if (coarsePointer()) {
      const box = proxy.getBoundingClientRect();
      if (event.clientX < box.right - 44) {
        return;
      }
      proxy.readOnly = true;
      proxy.blur();
    }
    openCalendar(state);
  }

  // --- calendário (flatpickr, carregado sob demanda) -------------------------

  function assetUrl(path) {
    return new URL(`../vendor/flatpickr/${path}`, scriptSrc || document.baseURI).href;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`falha ao carregar ${src}`));
      document.head.appendChild(script);
    });
  }

  function loadStyle(href) {
    if (document.querySelector(`link[href="${href}"]`)) {
      return;
    }
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function ensureCalendarAssets() {
    if (!calendarAssets) {
      if (!document.querySelector('link[href*="flatpickr"][rel="stylesheet"]')) {
        loadStyle(assetUrl('flatpickr.min.css'));
      }
      loadStyle(assetUrl('plugins/monthSelect/style.css'));
      calendarAssets = (global.flatpickr ? Promise.resolve() : loadScript(assetUrl('flatpickr.min.js')))
        .then(() => (typeof global.monthSelectPlugin === 'function'
          ? null
          : loadScript(assetUrl('plugins/monthSelect/index.js'))))
        .catch((error) => {
          // Sem calendário a digitação em dd/mm/aaaa continua funcionando.
          if (global.console) {
            global.console.warn('Calendário indisponível:', error);
          }
        });
    }
    return calendarAssets;
  }

  function createCalendar(state) {
    if (state.fp || typeof global.flatpickr !== 'function') {
      return state.fp;
    }
    const { input, proxy, kind } = state;
    if (kind === 'month' && typeof global.monthSelectPlugin !== 'function') {
      return null;
    }
    const options = {
      locale: LOCALE_PT,
      // Quem interpreta o texto digitado é este arquivo, não o flatpickr
      // (ele "rolaria" 31/02 para 03/03 e apagaria texto inválido).
      allowInput: false,
      clickOpens: false,
      disableMobile: true,
      allowInvalidPreload: true,
      dateFormat: kind === 'datetime-local' ? 'd/m/Y H:i' : 'd/m/Y',
      enableTime: kind === 'datetime-local',
      time_24hr: true,
      minuteIncrement: 1,
      defaultDate: isoToDate(kind, readValue(input)),
      minDate: isoToDate(kind, input.getAttribute('min')),
      maxDate: isoToDate(kind, input.getAttribute('max')),
      errorHandler: () => {},
      parseDate: (text) => isoToDate(kind, parseTyped(kind, text).iso) || undefined,
      onChange: (dates) => {
        if (state.muted) {
          return;
        }
        commit(state, dates.length ? dateToIso(kind, dates[0]) : '');
        setError(state, '', false);
      },
      onClose: () => {
        if (coarsePointer()) {
          proxy.readOnly = state.readonly;
          proxy.blur();
        }
      },
    };
    if (kind === 'month') {
      options.plugins = [new global.monthSelectPlugin({ shorthand: true, dateFormat: 'm/Y', altFormat: 'm/Y' })];
    }
    const text = proxy.value;
    state.muted = true;
    try {
      state.fp = global.flatpickr(proxy, options);
    } catch (error) {
      state.fp = null;
    } finally {
      state.muted = false;
    }
    if (!state.fp) {
      return null;
    }
    // O flatpickr marca o campo como readonly quando allowInput é false; aqui a
    // digitação continua permitida.
    proxy.readOnly = state.readonly;
    if (proxy.value !== text) {
      proxy.value = text;
    }
    // Modais e offcanvas do Bootstrap prendem o foco dentro deles; o calendário
    // fica no <body>, então o foco nele não pode chegar à armadilha.
    state.fp.calendarContainer.addEventListener('focusin', (event) => event.stopPropagation());
    state.fp.calendarContainer.setAttribute('translate', 'no');
    syncAttributes(state);
    return state.fp;
  }

  function openCalendar(state) {
    const { proxy } = state;
    if (proxy.disabled || state.readonly) {
      return;
    }
    ensureCalendarAssets().then(() => {
      const fp = createCalendar(state);
      if (!fp || fp.isOpen) {
        if (!fp && coarsePointer()) {
          proxy.readOnly = state.readonly;
        }
        return;
      }
      const text = proxy.value;
      const date = isoToDate(state.kind, readValue(state.input));
      state.muted = true;
      try {
        if (date) {
          fp.setDate(date, false);
        } else {
          fp.clear(false);
          proxy.value = text;
        }
      } finally {
        state.muted = false;
      }
      fp.open();
    });
  }

  // --- original: acessores e encaminhamentos ---------------------------------

  function installOverrides(state) {
    const { input, proxy } = state;
    const wrapSetter = (name) => {
      const descriptor = Object.getOwnPropertyDescriptor(proto, name);
      if (!descriptor || !descriptor.set) {
        return;
      }
      Object.defineProperty(input, name, {
        configurable: true,
        enumerable: descriptor.enumerable,
        get() {
          return descriptor.get.call(this);
        },
        set(value) {
          const before = readValue(this);
          descriptor.set.call(this, value);
          // Script regravou o mesmo valor enquanto a pessoa digita: não apaga
          // o que ela está escrevendo.
          if (readValue(this) === before && document.activeElement === proxy) {
            return;
          }
          render(state);
        },
      });
    };
    wrapSetter('value');
    wrapSetter('valueAsDate');
    wrapSetter('valueAsNumber');
    ['stepUp', 'stepDown'].forEach((name) => {
      input[name] = function stepAndRender(step) {
        proto[name].call(this, step);
        render(state);
      };
    });
    // O original está fora da validação nativa (readonly); quem valida é o espelho.
    input.checkValidity = () => proxy.checkValidity();
    input.reportValidity = () => proxy.reportValidity();
    input.setCustomValidity = (message) => {
      state.customMessage = String(message == null ? '' : message);
      updateValidity(state);
    };
    ['validity', 'validationMessage', 'willValidate'].forEach((name) => {
      Object.defineProperty(input, name, { configurable: true, get: () => proxy[name] });
    });
    input.focus = (options) => proxy.focus(options);
    input.blur = () => proxy.blur();
    input.click = () => openCalendar(state);
    input.showPicker = () => openCalendar(state);
    input.scrollIntoView = (...args) => proxy.scrollIntoView(...args);
  }

  const OVERRIDDEN = [
    'value', 'valueAsDate', 'valueAsNumber', 'stepUp', 'stepDown', 'checkValidity', 'reportValidity',
    'setCustomValidity', 'validity', 'validationMessage', 'willValidate', 'focus', 'blur', 'click',
    'showPicker', 'scrollIntoView',
  ];

  // --- ciclo de vida ----------------------------------------------------------

  function labelsFor(state) {
    const labels = state.input.labels ? Array.from(state.input.labels) : [];
    const ids = labels.map((label) => {
      if (!label.id) {
        uid += 1;
        label.id = `${state.input.id || 'campo-data'}-rotulo-${uid}`;
      }
      if (!label.dataset.dateBrLabel) {
        label.dataset.dateBrLabel = 'true';
        label.addEventListener('click', (event) => {
          const target = states.get(state.input) ? state.proxy : null;
          if (!target || event.target === target) {
            return;
          }
          event.preventDefault();
          target.focus();
        });
      }
      return label.id;
    });
    if (ids.length) {
      state.proxy.setAttribute('aria-labelledby', ids.join(' '));
    }
  }

  function placeProxy(state) {
    const { input, proxy } = state;
    const parent = input.parentNode;
    if (!parent) {
      proxy.remove();
      return;
    }
    if (proxy.nextSibling === input || input.nextSibling === proxy) {
      return;
    }
    // O espelho ocupa o lugar visual do original: antes dele quando o original
    // abre o grupo (mantém :first-child do .input-group), depois nos demais.
    if (input.parentElement && input.parentElement.firstElementChild === input) {
      parent.insertBefore(proxy, input);
    } else {
      parent.insertBefore(proxy, input.nextSibling);
    }
  }

  /** Clone (cloneNode/innerHTML) de um campo já tratado: volta ao estado nativo. */
  function restoreClone(input) {
    if (input.getAttribute(MARK) !== 'readonly') {
      input.removeAttribute('readonly');
    }
    input.classList.remove(NATIVE_CLASS);
    input.removeAttribute(MARK);
    [input.previousElementSibling, input.nextElementSibling].forEach((sibling) => {
      if (sibling && sibling.classList.contains(PROXY_CLASS) && !proxyOwners.has(sibling)) {
        sibling.remove();
      }
    });
  }

  function enhance(input) {
    if (!(input instanceof HTMLInputElement) || states.has(input)) {
      return;
    }
    const kind = kindOf(input);
    if (!kind) {
      return;
    }
    if (input.hasAttribute(MARK)) {
      restoreClone(input);
    }
    const proxy = document.createElement('input');
    proxy.type = 'text';
    proxy.setAttribute('inputmode', 'numeric');
    proxy.setAttribute('autocomplete', 'off');
    proxy.setAttribute('spellcheck', 'false');
    proxy.maxLength = KINDS[kind].placeholder.length;
    proxy.size = KINDS[kind].placeholder.length + 1;
    proxy.dataset.dateBrKind = kind;

    const state = {
      input,
      proxy,
      kind,
      fp: null,
      readonly: input.hasAttribute('readonly'),
      customMessage: '',
      typedError: '',
      showError: false,
      muted: false,
    };
    states.set(input, state);
    proxyOwners.set(proxy, state);

    const hadFocus = document.activeElement === input;
    input.setAttribute(MARK, state.readonly ? 'readonly' : '');
    input.classList.add(NATIVE_CLASS);
    input.setAttribute('readonly', '');

    placeProxy(state);
    labelsFor(state);
    syncAttributes(state);
    proxy.value = toDisplay(kind, readValue(input));
    updateValidity(state);
    installOverrides(state);

    proxy.addEventListener('input', (event) => onProxyInput(state, event));
    proxy.addEventListener('change', (event) => event.stopPropagation());
    proxy.addEventListener('blur', () => fromText(state, true));
    proxy.addEventListener('keydown', (event) => onProxyKeydown(state, event));
    proxy.addEventListener('click', (event) => onProxyClick(state, event));
    // Autopreenchimento do navegador escreve direto no original.
    ['input', 'change'].forEach((type) => {
      input.addEventListener(type, (event) => {
        if (event.isTrusted) {
          render(state);
        }
      });
    });

    attributeObserver.observe(input, { attributes: true, attributeFilter: MIRRORED_ATTRIBUTES, attributeOldValue: true });
    if (hadFocus) {
      proxy.focus();
    }
    // Pré-carrega o calendário sem atrasar a abertura da página.
    const idle = global.requestIdleCallback || ((callback) => setTimeout(callback, 200));
    idle(() => ensureCalendarAssets());
  }

  function teardown(state) {
    const { input, proxy } = state;
    states.delete(input);
    proxyOwners.delete(proxy);
    if (state.fp) {
      state.fp.destroy();
    }
    proxy.remove();
    OVERRIDDEN.forEach((name) => {
      if (Object.prototype.hasOwnProperty.call(input, name)) {
        delete input[name];
      }
    });
    input.classList.remove(NATIVE_CLASS);
    if (!state.readonly) {
      input.removeAttribute('readonly');
    }
    input.removeAttribute(MARK);
  }

  const attributeObserver = new MutationObserver((records) => {
    const touched = new Set();
    records.forEach((record) => {
      const state = states.get(record.target);
      if (!state) {
        return;
      }
      const { input } = state;
      if (record.attributeName === 'type') {
        if (kindOf(input) !== state.kind) {
          teardown(state);
          enhance(input);
        }
        return;
      }
      if (record.attributeName === 'readonly') {
        // O original precisa continuar readonly (fora da validação nativa);
        // o readonly "da tela" passa a valer no espelho.
        if (!input.hasAttribute('readonly')) {
          state.readonly = false;
          state.skipReadonly = (state.skipReadonly || 0) + 1;
          input.setAttribute('readonly', '');
        } else if (state.skipReadonly) {
          state.skipReadonly -= 1;
        } else {
          state.readonly = true;
        }
        input.setAttribute(MARK, state.readonly ? 'readonly' : '');
      }
      if (record.attributeName === 'class' && !input.classList.contains(NATIVE_CLASS)) {
        input.classList.add(NATIVE_CLASS);
      }
      touched.add(state);
      if (record.attributeName === 'value') {
        state.valueTouched = true;
      }
    });
    touched.forEach((state) => {
      if (!states.has(state.input)) {
        return;
      }
      syncAttributes(state);
      if (state.valueTouched) {
        state.valueTouched = false;
        render(state);
      }
    });
  });

  function scan(root) {
    if (!root || typeof root.querySelectorAll !== 'function') {
      return;
    }
    root.querySelectorAll(`.${PROXY_CLASS}`).forEach((proxy) => {
      if (!proxyOwners.has(proxy)) {
        proxy.remove();
      }
    });
    root.querySelectorAll(SELECTOR).forEach(enhance);
  }

  const treeObserver = new MutationObserver((records) => {
    const moved = new Set();
    records.forEach((record) => {
      if (record.type === 'attributes') {
        if (!states.has(record.target)) {
          enhance(record.target);
        }
        return;
      }
      record.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) {
          return;
        }
        if (states.has(node)) {
          moved.add(states.get(node));
        } else if (node.matches(SELECTOR)) {
          enhance(node);
        } else if (node.classList.contains(PROXY_CLASS) && !proxyOwners.has(node)) {
          node.remove();
        } else {
          scan(node);
        }
      });
      record.removedNodes.forEach((node) => {
        if (node.nodeType === 1 && states.has(node)) {
          moved.add(states.get(node));
        }
      });
    });
    // Original movido ou removido sozinho: o espelho acompanha.
    moved.forEach((state) => {
      if (state.input.isConnected) {
        placeProxy(state);
      } else {
        state.proxy.remove();
      }
    });
  });

  function init() {
    injectStyle();
    scan(document);
    treeObserver.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['type'],
    });
    // form.reset() devolve o valor padrão ao original sem passar pelo setter.
    document.addEventListener('reset', (event) => {
      const form = event.target;
      setTimeout(() => {
        Array.from(form.elements || []).forEach((element) => {
          const state = states.get(element);
          if (state) {
            state.customMessage = '';
            render(state);
          }
        });
      }, 0);
    }, true);
  }

  api.enhance = (root) => scan(root || document);
  api.refresh = (input) => {
    const state = states.get(input);
    if (state) {
      render(state);
    }
  };
  api.proxyFor = (input) => {
    const state = states.get(input);
    return state ? state.proxy : null;
  };
  global.PetDateBR = api;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}(typeof window !== 'undefined' ? window : globalThis));
