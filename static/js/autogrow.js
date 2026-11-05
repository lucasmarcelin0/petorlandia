// Toda textarea cresce com o conteúdo: ninguém deveria rolar dentro de um
// campo para reler o que acabou de escrever. Vale para as textareas que vêm
// no HTML, as que aparecem depois (modais, abas, trechos inseridos por fetch)
// e as que recebem texto por script. A altura original (rows, CSS) continua
// sendo o mínimo; um max-height do CSS continua sendo o teto.
//
// Para desligar num campo específico: data-autogrow="off".
// `data-autogrow` sem valor (ou "true") mantém o piso alto das descrições de
// produto e do animal, que já usavam este script antes de ele valer para todos.
(function () {
  'use strict';

  var OPT_IN_MIN_HEIGHT = 288;
  var pending = new Set();
  var frame = 0;

  function isTextarea(el) {
    return el && el.tagName === 'TEXTAREA';
  }

  function enabled(el) {
    return el.dataset.autogrow !== 'off';
  }

  function visible(el) {
    return el.isConnected && el.getClientRects().length > 0;
  }

  function px(value) {
    return parseFloat(value) || 0;
  }

  function grow(el, force) {
    if (!isTextarea(el) || !enabled(el) || !visible(el)) return;

    // Sem mudança de texto nem de largura, a altura certa é a mesma.
    var key = el.value.length + ':' + el.clientWidth;
    if (!force && el._autogrowKey === key) return;
    el._autogrowKey = key;

    var style = window.getComputedStyle(el);
    var borders = px(style.borderTopWidth) + px(style.borderBottomWidth);
    var paddings = px(style.paddingTop) + px(style.paddingBottom);
    var borderBox = style.boxSizing === 'border-box';

    // A primeira medida é a altura que o layout deu ao campo, antes de
    // qualquer ajuste nosso: ela vira o mínimo.
    var base = parseFloat(el.dataset.autogrowBase);
    if (isNaN(base)) {
      base = el.offsetHeight;
      if (el.hasAttribute('data-autogrow')) base = Math.max(base, OPT_IN_MIN_HEIGHT);
      el.dataset.autogrowBase = String(base);
    }

    // Encolher por um instante faz o scrollHeight medir só o texto. Guardar a
    // rolagem evita que a página (ou o modal) pule nesse instante.
    var scrolled = [];
    for (var node = el.parentElement; node; node = node.parentElement) {
      if (node.scrollTop) scrolled.push([node, node.scrollTop]);
    }
    var windowX = window.scrollX;
    var windowY = window.scrollY;

    el.style.height = '0px';
    var needed = Math.max(Math.ceil(el.scrollHeight + borders), base);
    var height = borderBox ? needed : needed - borders - paddings;
    el.style.height = height + 'px';
    // Barra de rolagem horizontal (white-space: pre) come altura do texto.
    var hidden = el.scrollHeight - el.clientHeight;
    if (hidden > 0) el.style.height = (height + hidden) + 'px';

    scrolled.forEach(function (entry) { entry[0].scrollTop = entry[1]; });
    if (window.scrollX !== windowX || window.scrollY !== windowY) window.scrollTo(windowX, windowY);
  }

  function each(root, fn) {
    if (!root) return;
    if (isTextarea(root)) fn(root);
    if (root.querySelectorAll) root.querySelectorAll('textarea').forEach(fn);
  }

  function schedule(el) {
    pending.add(el);
    if (frame) return;
    frame = window.requestAnimationFrame(function () {
      frame = 0;
      var batch = Array.from(pending);
      pending.clear();
      batch.forEach(function (item) { watch(item); grow(item, true); });
    });
  }

  // Campo oculto (aba, modal, <details>, d-none) não tem altura para medir:
  // ele é ajustado quando chega perto da área visível.
  var visibility = 'IntersectionObserver' in window
    ? new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) grow(entry.target);
        });
      }, { rootMargin: '400px 0px' })
    : null;

  function watch(el) {
    if (el._autogrowWatched) return;
    el._autogrowWatched = true;
    el.dataset.autogrowReady = 'true';
    if (visibility) visibility.observe(el);
  }

  function init(root) {
    each(root || document, function (el) { watch(el); grow(el, true); });
  }

  // Texto colocado por script (modelos de texto, rascunhos, limpeza depois de
  // enviar) não dispara "input"; o setter de value avisa.
  var valueProperty = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
  if (valueProperty && valueProperty.set && valueProperty.configurable) {
    Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {
      configurable: true,
      enumerable: valueProperty.enumerable,
      get: valueProperty.get,
      set: function (value) {
        valueProperty.set.call(this, value);
        schedule(this);
      }
    });
  }

  document.addEventListener('input', function (event) {
    if (isTextarea(event.target)) grow(event.target, true);
  }, true);

  document.addEventListener('focusin', function (event) {
    if (isTextarea(event.target)) grow(event.target);
  }, true);

  // reset() devolve o texto inicial sem passar pelo setter.
  document.addEventListener('reset', function (event) {
    window.setTimeout(function () { each(event.target, schedule); }, 0);
  }, true);

  // A largura muda a quebra de linha: celular girando, janela redimensionada.
  var resizeTimer = 0;
  window.addEventListener('resize', function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      each(document, function (el) { grow(el); });
    }, 150);
  });

  new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(function (node) {
        if (node.nodeType === 1) each(node, schedule);
      });
    });
  }).observe(document.documentElement, { childList: true, subtree: true });

  function start() {
    init(document);
    // A fonte da página pode chegar depois e mudar a quebra de linha.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () {
        each(document, function (el) { grow(el, true); });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.PetorlandiaAutogrow = { init: init, grow: grow };
})();
