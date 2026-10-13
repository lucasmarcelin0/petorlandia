/* Folha SINAN para impressão: ajusta a letra dos valores longos à casa e a folha à largura da tela. */
(function () {
  'use strict';

  var LARGURA_FOLHA_MM = 210;
  var FATOR_MINIMO = 0.56;

  function sobra(el, vertical) {
    return vertical ? el.scrollHeight > el.clientHeight + 1 : el.scrollWidth > el.clientWidth + 1;
  }

  // Diminui a letra até o valor caber; só então deixa quebrar em duas linhas. Nada é cortado.
  function ajustar(el) {
    var vertical = el.classList.contains('obs');
    var fator = 1;
    el.classList.remove('quebrado');
    el.style.setProperty('--f', fator);
    while (sobra(el, vertical) && fator > FATOR_MINIMO) {
      fator -= 0.04;
      el.style.setProperty('--f', fator.toFixed(2));
    }
    if (!vertical && sobra(el, false)) el.classList.add('quebrado');
  }

  function ajustarTudo() {
    document.querySelectorAll('.folha .v').forEach(ajustar);
  }

  function escalarParaTela() {
    var mm = document.createElement('div');
    mm.style.cssText = 'position:absolute;visibility:hidden;width:' + LARGURA_FOLHA_MM + 'mm';
    document.body.appendChild(mm);
    var largura = mm.getBoundingClientRect().width;
    mm.remove();
    var escala = Math.min(1, (document.documentElement.clientWidth - 16) / largura);
    document.documentElement.style.setProperty('--escala', escala.toFixed(3));
  }

  document.addEventListener('DOMContentLoaded', function () {
    escalarParaTela();
    ajustarTudo();
    window.addEventListener('resize', escalarParaTela);
    window.addEventListener('beforeprint', ajustarTudo);

    var botao = document.querySelector('[data-imprimir]');
    if (botao) botao.addEventListener('click', function () { window.print(); });

    // Simulação: campos não guardados podem ser digitados na tela, só para a impressão.
    document.querySelectorAll('.nao-guardado').forEach(function (el) {
      el.addEventListener('focus', function () {
        var selecao = window.getSelection();
        selecao.removeAllRanges();
        var faixa = document.createRange();
        faixa.selectNodeContents(el);
        selecao.addRange(faixa);
      });
      el.addEventListener('keydown', function (evento) {
        if (evento.key === 'Enter') { evento.preventDefault(); el.blur(); }
      });
      el.addEventListener('input', function () {
        el.setAttribute('data-digitado', '');
        ajustar(el);
      });
    });
  });
})();
