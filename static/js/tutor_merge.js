/*
 * Unificar cadastros de tutor.
 *
 * Quando o e-mail digitado na ficha já pertence a outro cadastro, o servidor
 * responde 409 com `merge_offer` (ver update_tutor em blueprints/pacientes.py)
 * e o offline.js dispara o evento `tutor-merge-offer`. Aqui o aviso ganha a
 * opção de juntar os dois cadastros: os animais e o histórico deste vão para o
 * cadastro que já usa o e-mail (onde a pessoa faz login).
 */
(function () {
  'use strict';

  const PANEL_CLASS = 'tutor-merge-offer';

  function csrfToken(form) {
    const input = form && form.querySelector('input[name="csrf_token"]');
    if (input && input.value) return input.value;
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function plural(n, um, varios) {
    return `${n} ${n === 1 ? um : varios}`;
  }

  function removePanel(form) {
    const old = form && form.querySelector('.' + PANEL_CLASS);
    if (old) old.remove();
  }

  function setStatus(panel, text, variant) {
    const status = panel.querySelector('.tutor-merge-offer__status');
    if (!status) return;
    status.className = `tutor-merge-offer__status small mt-2 text-${variant}`;
    status.textContent = text;
  }

  function afterMerge(redirectUrl) {
    // Na consulta, o animal continua o mesmo (só mudou de tutor): recarrega a
    // própria tela. Fora dela, abre a ficha do cadastro que ficou.
    const path = window.location.pathname || '';
    if (path.startsWith('/consulta') || !redirectUrl) {
      window.location.reload();
    } else {
      window.location.assign(redirectUrl);
    }
  }

  // Conta que a própria pessoa criou e a clínica ainda não enxerga: o
  // servidor não manda nome nem animais dela, só o e-mail digitado.
  function targetLabel(offer) {
    return offer.target_name
      ? `o cadastro de ${offer.target_name} (nº ${offer.target_id})`
      : `a conta que a pessoa criou com ${offer.email || 'este e-mail'}`;
  }

  async function merge(form, offer, panel, button) {
    const animais = plural(offer.source_animals || 0, 'animal', 'animais');
    const ok = window.confirm(
      `Unificar com ${targetLabel(offer)}?\n\n` +
      `${animais} e todo o histórico deste cadastro passam para lá. ` +
      'O e-mail e a senha dessa conta continuam valendo, e este cadastro deixa de existir.'
    );
    if (!ok) return;

    button.disabled = true;
    setStatus(panel, 'Unificando cadastros...', 'muted');

    const body = new FormData();
    body.append('target_id', offer.target_id);
    if (offer.email) body.append('email', offer.email);
    const token = csrfToken(form);
    if (token) body.append('csrf_token', token);

    let data = null;
    let resp = null;
    try {
      resp = await fetch(offer.url, {
        method: 'POST',
        headers: { Accept: 'application/json', 'X-CSRFToken': token },
        body,
        credentials: 'same-origin',
      });
      try { data = await resp.json(); } catch (e) { data = null; }
    } catch (error) {
      console.error('Erro ao unificar cadastros:', error);
    }

    if (resp && resp.ok && data && data.success !== false) {
      setStatus(panel, data.message || 'Cadastros unificados.', 'success');
      if (window.FormFeedback && typeof window.FormFeedback.showStatus === 'function') {
        window.FormFeedback.showStatus(form, data.message || 'Cadastros unificados.', 'success');
      }
      setTimeout(() => afterMerge(data.redirect), 1200);
      return;
    }

    button.disabled = false;
    setStatus(
      panel,
      (data && data.message) || 'Não foi possível unificar agora. Verifique a conexão e tente novamente.',
      'danger'
    );
  }

  function buildPanel(form, offer) {
    const panel = document.createElement('div');
    panel.className = `${PANEL_CLASS} col-12 alert alert-info mt-2`;
    panel.setAttribute('role', 'region');
    panel.setAttribute('aria-label', 'Unificar cadastros');

    const title = document.createElement('div');
    title.className = 'fw-semibold mb-1';
    title.textContent = 'É a mesma pessoa?';

    const text = document.createElement('p');
    text.className = 'mb-2 small';
    const origem = plural(offer.source_animals || 0, 'animal', 'animais');
    const onde = offer.target_name
      ? `o de ${offer.target_name} (nº ${offer.target_id}, hoje com ` +
        `${plural(offer.target_animals || 0, 'animal', 'animais')})`
      : 'a conta que a própria pessoa criou com esse e-mail';
    text.textContent =
      `Você pode unificar os cadastros: ${origem} e o histórico deste cadastro ` +
      `passam para ${onde}, que é onde a pessoa entra com esse e-mail.`;

    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap gap-2';

    const mergeBtn = document.createElement('button');
    mergeBtn.type = 'button';
    mergeBtn.className = 'btn btn-primary btn-sm';
    mergeBtn.innerHTML = '<i class="bi bi-people"></i> ';
    mergeBtn.appendChild(document.createTextNode('Unificar cadastros'));
    mergeBtn.addEventListener('click', () => merge(form, offer, panel, mergeBtn));

    const dismissBtn = document.createElement('button');
    dismissBtn.type = 'button';
    dismissBtn.className = 'btn btn-outline-secondary btn-sm';
    dismissBtn.textContent = 'Não, vou corrigir o e-mail';
    dismissBtn.addEventListener('click', () => {
      panel.remove();
      const email = form.querySelector('input[name="email"]');
      if (email) email.focus();
    });

    const status = document.createElement('div');
    status.className = 'tutor-merge-offer__status small mt-2';
    status.setAttribute('aria-live', 'polite');

    actions.append(mergeBtn, dismissBtn);
    panel.append(title, text, actions, status);
    return panel;
  }

  document.addEventListener('tutor-merge-offer', (ev) => {
    const detail = ev.detail || {};
    const form = detail.form;
    const offer = detail.offer;
    if (!form || !offer || !offer.url || !offer.target_id) return;

    removePanel(form);
    const panel = buildPanel(form, offer);
    const status = form.querySelector('.form-status-message');
    if (status && status.parentNode) {
      status.parentNode.insertBefore(panel, status.nextSibling);
    } else {
      form.appendChild(panel);
    }
    try { panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) {}

    // Um novo envio (ex.: e-mail corrigido) tira a oferta antiga da tela.
    form.addEventListener('submit', () => removePanel(form), { once: true });
  });
})();
