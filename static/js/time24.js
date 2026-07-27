/**
 * Campos de hora sempre em 24h.
 *
 * O <input type="time"> nativo usa o locale do NAVEGADOR, não o lang do
 * documento: num Windows em en-US o campo aparece como "07:00 AM" mesmo com
 * <html lang="pt-BR">. Não existe atributo que force 24h, então quando
 * detectamos um navegador em 12h trocamos o campo por um texto mascarado
 * HH:MM. O valor continua no formato HH:MM, que é exatamente o que o
 * servidor já espera (TimeField do WTForms e strptime '%H:%M').
 */

function browserUses12hClock() {
  try {
    const parts = new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).formatToParts(new Date());
    if (parts.some((part) => part.type === 'dayPeriod')) {
      return true;
    }
    return new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).resolvedOptions().hour12 === true;
  } catch (err) {
    // Sem Intl confiável, assume 24h e mantém o campo nativo.
    return false;
  }
}

function clampTime(raw) {
  const digits = String(raw || '').replace(/\D/g, '').slice(0, 4);
  if (!digits) {
    return '';
  }
  if (digits.length <= 2) {
    // Ainda digitando a hora — não normaliza para não brigar com o cursor.
    return digits;
  }
  let hours = parseInt(digits.slice(0, 2), 10);
  let minutes = parseInt(digits.slice(2).padEnd(2, '0'), 10);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) {
    return '';
  }
  hours = Math.min(hours, 23);
  minutes = Math.min(minutes, 59);
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

function formatWhileTyping(raw) {
  const digits = String(raw || '').replace(/\D/g, '').slice(0, 4);
  if (digits.length <= 2) {
    return digits;
  }
  return `${digits.slice(0, 2)}:${digits.slice(2)}`;
}

/**
 * Ao sair do campo, completa o que o usuário deixou pela metade.
 * "9" e "09" viram 09:00; "930" vira 09:30; hora impossível é limitada.
 */
function normalizeOnBlur(raw) {
  const digits = String(raw || '').replace(/\D/g, '').slice(0, 4);
  if (!digits) {
    return '';
  }
  // 1 ou 2 dígitos = só a hora; 3 dígitos = H:MM (ex.: 930 -> 09:30).
  const preenchido = digits.length <= 2 ? digits.padStart(2, '0') + '00' : digits.padStart(4, '0');
  return clampTime(preenchido);
}

function convertToText(input) {
  if (input.dataset.time24 === 'true') {
    return;
  }
  const value = input.value || '';
  input.dataset.time24 = 'true';
  input.type = 'text';
  input.value = value;
  input.setAttribute('inputmode', 'numeric');
  input.setAttribute('maxlength', '5');
  input.setAttribute('autocomplete', 'off');
  if (!input.getAttribute('placeholder')) {
    input.setAttribute('placeholder', 'HH:MM');
  }
  if (!input.getAttribute('aria-describedby') && !input.getAttribute('title')) {
    input.setAttribute('title', 'Horário no formato 24 horas, por exemplo 14:30');
  }
  // pattern dá validação nativa de formulário sem depender de JS extra.
  input.setAttribute('pattern', '([01][0-9]|2[0-3]):[0-5][0-9]');

  input.addEventListener('input', () => {
    const cursorAtEnd = input.selectionStart === input.value.length;
    const formatted = formatWhileTyping(input.value);
    if (formatted !== input.value) {
      input.value = formatted;
      if (cursorAtEnd) {
        input.setSelectionRange(formatted.length, formatted.length);
      }
    }
  });

  input.addEventListener('blur', () => {
    input.value = normalizeOnBlur(input.value);
  });
}

function enhanceTimeInputs(root) {
  const scope = root instanceof Element || root instanceof Document ? root : document;
  scope.querySelectorAll('input[type="time"]').forEach(convertToText);
}

function initTime24() {
  if (!browserUses12hClock()) {
    return;
  }
  enhanceTimeInputs(document);

  // Offcanvas/modais podem injetar campos depois do load.
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType !== Node.ELEMENT_NODE) {
          return;
        }
        if (node.matches && node.matches('input[type="time"]')) {
          convertToText(node);
        } else {
          enhanceTimeInputs(node);
        }
      });
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initTime24);
} else {
  initTime24();
}

export { browserUses12hClock, clampTime, formatWhileTyping, normalizeOnBlur, enhanceTimeInputs };
