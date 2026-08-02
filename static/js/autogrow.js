// Textareas longas crescem com o conteúdo: quem escreve a descrição de um
// produto precisa enxergar o texto inteiro sem rolar dentro do campo.
(function () {
  'use strict';

  var MIN_HEIGHT = 288;

  function grow(el) {
    el.style.height = 'auto';
    el.style.height = Math.max(el.scrollHeight, MIN_HEIGHT) + 'px';
  }

  function init(root) {
    (root || document).querySelectorAll('textarea[data-autogrow]').forEach(function (el) {
      if (el.dataset.autogrowReady === 'true') return;
      el.dataset.autogrowReady = 'true';
      el.addEventListener('input', function () { grow(el); });
      grow(el);
    });
  }

  document.addEventListener('DOMContentLoaded', function () { init(document); });
  window.PetorlandiaAutogrow = { init: init };
})();
