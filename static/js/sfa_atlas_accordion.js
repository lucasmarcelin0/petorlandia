/*
 * Atlas de campo em sanfona: abaixo do mapa só um assunto aparece por vez.
 * Abrir um painel (Rota, Camadas, Ocorrências…) ou um bloco de mapas de apoio fecha os outros.
 * É só apresentação: os painéis continuam no DOM, então nenhuma função deles muda.
 * Sem este script (ou se algo falhar) tudo segue visível como antes.
 */
(function () {
  'use strict';
  const rail = document.querySelector('.field-rail');
  const nav = rail && rail.querySelector('.atlas-rail-nav');
  if (!rail || !nav) return;

  const buttons = Array.from(nav.querySelectorAll('[data-atlas-panel]'));
  const panels = buttons.map(b => document.getElementById(b.dataset.atlasPanel)).filter(Boolean);
  const outside = Array.from(document.querySelectorAll('#panel-reference > details.ento-panel'));
  const hint = document.createElement('p');
  hint.className = 'atlas-rail-hint';
  hint.textContent = 'Escolha um assunto acima. Abrir um fecha o outro.';
  nav.after(hint);
  let current = null;

  function paint() {
    buttons.forEach(b => {
      const on = b.dataset.atlasPanel === current;
      b.setAttribute('aria-expanded', String(on));
      const panel = document.getElementById(b.dataset.atlasPanel);
      if (panel) { panel.classList.toggle('is-acc-closed', !on); panel.classList.toggle('is-acc-open', on); }
    });
    hint.hidden = current !== null;
  }

  function closeOutside(except) {
    outside.forEach(d => { if (d !== except && d.open) d.open = false; });
  }

  function open(id) {
    current = id;
    paint();
    if (id) closeOutside(null);
    // Mapas dentro de painéis que acabaram de aparecer precisam recalcular o tamanho.
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }

  rail.classList.add('is-accordion');
  buttons.forEach(b => {
    b.setAttribute('aria-controls', b.dataset.atlasPanel);
    b.setAttribute('aria-expanded', 'false');
  });
  // Antes do tratamento antigo (que apenas rolava até o painel): a sanfona assume o clique.
  nav.addEventListener('click', e => {
    const b = e.target.closest('[data-atlas-panel]');
    if (!b) return;
    e.stopImmediatePropagation();
    open(current === b.dataset.atlasPanel ? null : b.dataset.atlasPanel);
  }, true);

  outside.forEach(d => d.addEventListener('toggle', () => {
    if (!d.open) return;
    closeOutside(d);
    if (current !== null) open(null);
    d.classList.add('is-acc-open-flash');
    setTimeout(() => d.classList.remove('is-acc-open-flash'), 260);
  }));

  // Quadra clicada no mapa e parada adicionada à rota abrem o painel correspondente.
  const selection = document.getElementById('field-selection');
  if (selection) new MutationObserver(() => {
    if (selection.querySelector('.field-selected-number') && current !== 'field-selection') open('field-selection');
  }).observe(selection, {childList: true});
  const list = document.getElementById('atlas-route-list');
  if (list) {
    let count = list.children.length;
    new MutationObserver(() => {
      const now = list.children.length;
      if (now > count && current !== 'atlas-route') open('atlas-route');
      count = now;
    }).observe(list, {childList: true});
  }

  closeOutside(null);
  open(null);
})();
