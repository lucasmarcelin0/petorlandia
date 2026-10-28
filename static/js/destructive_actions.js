/* Recolhe ações destrutivas sem substituir controles, formulários ou listeners.
 * A identificação pelo rótulo/ícone também cobre os fragmentos HTML e os
 * controles construídos pelos vários módulos legados do aplicativo.
 */
(() => {
  'use strict';
  const controls = 'button, a, input[type="submit"], input[type="button"]';
  const destructiveLabel = /^(excluir|deletar|apagar|remover|retirar|delete|remove)\b/i;
  const trashIcon = '[class*="fa-trash"], [class*="bi-trash"]';
  const alreadyProtected = '.destructive-actions, .dropdown-menu, [data-destructive-confirmation]';

  function labelOf(control) {
    return control.getAttribute('aria-label') || control.getAttribute('title') ||
      control.value || control.textContent.trim();
  }

  function isDestructive(control) {
    const labels = [control.getAttribute('aria-label'), control.getAttribute('title'),
      control.value, control.textContent];
    return control.hasAttribute('data-destructive-action') ||
      labels.some(label => destructiveLabel.test((label || '').replace(/^[^\p{L}]+/u, ''))) ||
      Array.from(control.querySelectorAll(trashIcon)).some(icon => icon.closest(controls) === control);
  }

  function protect(control) {
    if (!control.isConnected || control.closest(alreadyProtected) || !isDestructive(control)) return;
    const disclosure = document.createElement('details');
    disclosure.className = 'destructive-actions';
    const summary = document.createElement('summary');
    const label = labelOf(control) || 'ações do registro';
    summary.title = `Mais opções: ${label}`;
    summary.setAttribute('aria-label', summary.title);
    summary.textContent = '⋯';
    // O controle original continua no mesmo formulário, com CSRF, atributos e
    // listeners intactos. <summary> nunca envia o formulário.
    control.before(disclosure);
    disclosure.append(summary, control);
  }

  function scan(root) {
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    if (root.matches(controls)) protect(root);
    root.querySelectorAll(controls).forEach(protect);
  }

  function closeOthers(except) {
    document.querySelectorAll('.destructive-actions[open]').forEach(disclosure => {
      if (disclosure !== except) disclosure.open = false;
    });
  }

  function init() {
    scan(document.body);
    new MutationObserver(records => {
      records.forEach(record => {
        // Rótulos de botões também podem mudar após uma edição/seleção.
        const control = record.target.parentElement?.closest(controls);
        if (control) protect(control);
        if (record.target.matches?.(controls)) protect(record.target);
        record.addedNodes.forEach(scan);
      });
    }).observe(document.body, {childList: true, subtree: true, characterData: true});

    document.addEventListener('click', event => {
      closeOthers(event.target.closest('.destructive-actions'));
    });
    document.addEventListener('toggle', event => {
      if (event.target.matches('.destructive-actions[open]')) closeOthers(event.target);
    }, true);
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      const disclosure = event.target.closest('.destructive-actions[open]');
      closeOthers(null);
      if (disclosure) disclosure.querySelector('summary').focus();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
