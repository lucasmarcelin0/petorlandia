/**
 * CPF, telefone e RG: máscara que aceita o que o banco já guarda.
 *
 * O mesmo dado está gravado em formatos diferentes conforme a tela que o
 * salvou: "36243026809" e "362.430.268-09"; "16992690405", "(16) 99269-0405"
 * e "+5516992690405". Com `pattern` fixo no HTML, a ficha do tutor recusava o
 * que a consulta tinha gravado e vice-versa: a tela abria com o campo em
 * vermelho ("insira um CPF válido") sem ninguém ter digitado nada.
 *
 * Por isso estes campos não usam `pattern` nem `data-mask`. Marque o input com
 * `data-campo-br="cpf" | "telefone" | "rg"` e este arquivo:
 *
 * - mostra o valor sempre formatado (000.000.000-00, (00) 00000-0000);
 * - formata enquanto a pessoa digita, com ou sem pontuação;
 * - valida pela quantidade de dígitos, nunca pelo desenho da máscara;
 * - considera válido o valor que já veio gravado: dado antigo fora do padrão
 *   não pode impedir o salvamento dos outros campos.
 *
 * O servidor recebe com máscara e normaliza (document_utils.py).
 * tests/test_campos_br.js cobre as funções; tests/test_campos_br_guard.py
 * falha se um template voltar a pôr `pattern`/`data-mask` nesses campos.
 */
(function (global) {
  'use strict';

  function digitsOf(value) {
    return String(value == null ? '' : value).replace(/\D/g, '');
  }

  // --- CPF --------------------------------------------------------------------

  function maskCpf(value) {
    const d = digitsOf(value).slice(0, 11);
    let out = d.slice(0, 3);
    if (d.length > 3) out += `.${d.slice(3, 6)}`;
    if (d.length > 6) out += `.${d.slice(6, 9)}`;
    if (d.length > 9) out += `-${d.slice(9)}`;
    return out;
  }

  /** Valor gravado -> texto do campo. O que não é CPF completo fica como está. */
  function formatCpf(value) {
    const raw = String(value == null ? '' : value).trim();
    return digitsOf(raw).length === 11 ? maskCpf(raw) : raw;
  }

  // --- Telefone ---------------------------------------------------------------

  /** DDD + número de um telefone brasileiro, ou '' se não for um. */
  function phoneNationalDigits(value) {
    const raw = String(value == null ? '' : value).trim();
    let d = digitsOf(raw);
    if (raw.startsWith('+') && !d.startsWith('55')) {
      return ''; // número de outro país
    }
    if ((d.length === 12 || d.length === 13) && d.startsWith('55')) {
      d = d.slice(2);
    }
    if ((d.length === 11 || d.length === 12) && d.startsWith('0')) {
      d = d.slice(1);
    }
    return d.length === 10 || d.length === 11 ? d : '';
  }

  function maskPhoneDigits(digits) {
    const d = digits.slice(0, 11);
    if (!d) return '';
    if (d.length <= 2) return `(${d}`;
    const ddd = d.slice(0, 2);
    const rest = d.slice(2);
    if (rest.length <= 4) return `(${ddd}) ${rest}`;
    const cut = rest.length === 9 ? 5 : 4;
    return `(${ddd}) ${rest.slice(0, cut)}-${rest.slice(cut)}`;
  }

  /** Valor gravado -> texto do campo. Estrangeiro ou incompleto fica como está. */
  function formatPhone(value) {
    const raw = String(value == null ? '' : value).trim();
    const national = phoneNationalDigits(raw);
    return national ? maskPhoneDigits(national) : raw;
  }

  /** Máscara durante a digitação. */
  function maskPhoneTyping(value) {
    const raw = String(value == null ? '' : value);
    if (raw.trim().startsWith('+')) {
      const national = phoneNationalDigits(raw);
      // "+55 16 99269-0405" completo vira o formato nacional; outro país fica livre.
      return national && digitsOf(raw).length >= 12
        ? maskPhoneDigits(national)
        : raw.replace(/[^\d+()\- ]/g, '').slice(0, 20);
    }
    const national = phoneNationalDigits(raw);
    if (national) {
      return maskPhoneDigits(national);
    }
    // DDD nunca começa com zero: o zero na frente é o de tronco (016...).
    return maskPhoneDigits(digitsOf(raw).replace(/^0+/, ''));
  }

  // --- Regras -----------------------------------------------------------------

  const RG_RE = /^[0-9A-Za-z.\-\/ ]{3,20}$/;

  const KINDS = {
    cpf: {
      format: formatCpf,
      typing: maskCpf,
      inputmode: 'numeric',
      maxLength: 14,
      message(value) {
        return digitsOf(value).length === 11 ? '' : 'Informe o CPF com 11 dígitos.';
      },
    },
    telefone: {
      format: formatPhone,
      typing: maskPhoneTyping,
      inputmode: 'tel',
      maxLength: 20,
      message(value) {
        const raw = String(value).trim();
        if (phoneNationalDigits(raw)) return '';
        const total = digitsOf(raw).length;
        if (raw.startsWith('+') && total >= 8 && total <= 15) return '';
        return 'Informe o telefone com DDD (10 ou 11 dígitos).';
      },
    },
    rg: {
      format: (value) => String(value == null ? '' : value).trim(),
      typing: (value) => String(value == null ? '' : value).replace(/[^0-9A-Za-z.\-\/ ]/g, '').slice(0, 20),
      inputmode: '',
      maxLength: 20,
      message(value) {
        return RG_RE.test(String(value).trim()) ? '' : 'Informe o RG com letras e números (3 a 20 caracteres).';
      },
    },
  };

  function isKind(kind) {
    return Object.prototype.hasOwnProperty.call(KINDS, kind);
  }

  /**
   * Mensagem de erro do campo, ou '' se ele pode ser enviado.
   *
   * `stored` é o valor que veio do servidor: reenviar o mesmo dado (com
   * qualquer pontuação) é sempre válido, mesmo que ele esteja fora do padrão.
   */
  function validityMessage(kind, value, stored) {
    if (!isKind(kind)) return '';
    const text = String(value == null ? '' : value).trim();
    if (!text) return ''; // obrigatoriedade é com o atributo required
    const before = String(stored == null ? '' : stored).trim();
    if (before) {
      const same = kind === 'rg'
        ? text === before
        : (digitsOf(text) === digitsOf(before)
          || (kind === 'telefone' && phoneNationalDigits(text) !== ''
            && phoneNationalDigits(text) === phoneNationalDigits(before)));
      if (same) return '';
    }
    return KINDS[kind].message(text);
  }

  /** Posição do cursor logo depois do n-ésimo dígito do texto formatado. */
  function caretAfterDigits(text, count) {
    if (count <= 0) return 0;
    let seen = 0;
    for (let index = 0; index < text.length; index += 1) {
      if (/\d/.test(text[index])) {
        seen += 1;
        if (seen === count) return index + 1;
      }
    }
    return text.length;
  }

  const api = {
    KINDS,
    digitsOf,
    maskCpf,
    formatCpf,
    phoneNationalDigits,
    formatPhone,
    maskPhoneTyping,
    validityMessage,
    caretAfterDigits,
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

  const SELECTOR = 'input[data-campo-br]';
  const stored = new WeakMap();

  function refreshValidity(input) {
    const kind = input.dataset.campoBr;
    input.setCustomValidity(validityMessage(kind, input.value, stored.get(input)));
  }

  function onInput(event) {
    const input = event.target;
    const kind = input.dataset.campoBr;
    const raw = input.value;
    const masked = KINDS[kind].typing(raw);
    if (masked !== raw) {
      const caret = input.selectionStart;
      const atEnd = caret === null || caret >= raw.length;
      input.value = masked;
      if (document.activeElement === input && typeof input.setSelectionRange === 'function') {
        const position = atEnd
          ? masked.length
          : (kind === 'rg' ? Math.min(caret, masked.length) : caretAfterDigits(masked, digitsOf(raw.slice(0, caret)).length));
        try {
          input.setSelectionRange(position, position);
        } catch (error) {
          // type="email"/"number" não têm seleção; não é o caso destes campos.
        }
      }
    }
    refreshValidity(input);
  }

  function onBlur(event) {
    const input = event.target;
    const formatted = KINDS[input.dataset.campoBr].format(input.value);
    if (formatted !== input.value) {
      input.value = formatted;
    }
    refreshValidity(input);
  }

  function enhance(input) {
    if (!(input instanceof HTMLInputElement) || stored.has(input)) {
      return;
    }
    const kind = input.dataset.campoBr;
    if (!isKind(kind)) {
      return;
    }
    const spec = KINDS[kind];
    stored.set(input, input.value);
    // Um `pattern` esquecido voltaria a recusar o valor formatado.
    input.removeAttribute('pattern');
    if (spec.inputmode && !input.hasAttribute('inputmode')) {
      input.setAttribute('inputmode', spec.inputmode);
    }
    if (!input.hasAttribute('maxlength')) {
      input.maxLength = spec.maxLength;
    }
    const formatted = spec.format(input.value);
    if (formatted !== input.value) {
      input.value = formatted;
    }
    input.addEventListener('input', onInput);
    input.addEventListener('blur', onBlur);
    refreshValidity(input);
  }

  function scan(root) {
    if (root && typeof root.querySelectorAll === 'function') {
      root.querySelectorAll(SELECTOR).forEach(enhance);
    }
  }

  function init() {
    scan(document);
    // Formulários montados depois (modais, painéis carregados por fetch).
    new MutationObserver((records) => {
      records.forEach((record) => {
        record.addedNodes.forEach((node) => {
          if (node.nodeType !== 1) return;
          if (node.matches(SELECTOR)) {
            enhance(node);
          } else {
            scan(node);
          }
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });

    // Depois de salvar, o que está na tela passa a ser o valor gravado.
    document.addEventListener('form-sync-success', (event) => {
      const form = event.detail && event.detail.form;
      if (!form || typeof form.querySelectorAll !== 'function') return;
      form.querySelectorAll(SELECTOR).forEach((input) => {
        if (stored.has(input)) {
          stored.set(input, input.value);
          refreshValidity(input);
        }
      });
    });

    // form.reset() devolve o valor inicial sem disparar `input`.
    document.addEventListener('reset', (event) => {
      const form = event.target;
      setTimeout(() => {
        if (!form || typeof form.querySelectorAll !== 'function') return;
        form.querySelectorAll(SELECTOR).forEach((input) => {
          if (stored.has(input)) {
            input.value = KINDS[input.dataset.campoBr].format(input.value);
            refreshValidity(input);
          }
        });
      }, 0);
    }, true);
  }

  api.enhance = (root) => scan(root || document);
  global.PetCamposBR = api;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}(typeof window !== 'undefined' ? window : globalThis));
