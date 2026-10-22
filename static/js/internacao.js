(function () {
  'use strict';

  const dateFormat = new Intl.DateTimeFormat('pt-BR', {
    timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short'
  });

  document.querySelectorAll('[data-ih-print]').forEach(function (button) {
    button.addEventListener('click', function () { window.print(); });
  });

  function syncPrescriptionFields(form) {
    const mode = form.querySelector('[data-ih-modo]').value;
    form.querySelectorAll('[data-ih-modes]').forEach(function (group) {
      const active = group.dataset.ihModes.split(' ').includes(mode);
      group.hidden = !active;
      group.querySelectorAll('input,select,textarea').forEach(function (field) {
        field.disabled = !active;
        field.required = active && field.hasAttribute('data-ih-required');
      });
    });
  }

  function appendParagraph(container, value, strong) {
    const paragraph = document.createElement('p');
    if (strong) {
      const title = document.createElement('strong');
      title.textContent = value;
      paragraph.appendChild(title);
    } else {
      paragraph.textContent = value;
    }
    container.appendChild(paragraph);
  }

  async function previewPrescription(form) {
    if (form.dataset.ihPreviewPending === 'true') return false;
    const panel = form.querySelector('[data-ih-preview]');
    const button = form.querySelector('[data-ih-preview-button]');
    panel.hidden = false;
    panel.replaceChildren();
    if (!form.reportValidity()) {
      appendParagraph(panel, 'Preencha os campos obrigatórios para conferir a programação.');
      return false;
    }
    button.disabled = true;
    form.dataset.ihPreviewPending = 'true';
    appendParagraph(panel, 'Conferindo os horários…');
    const controller = new AbortController();
    const timeout = window.setTimeout(function () { controller.abort(); }, 15000);
    try {
      const response = await fetch(form.dataset.previewUrl, {
        method: 'POST', body: new FormData(form),
        headers: {Accept: 'application/json', 'X-CSRFToken': form.querySelector('[name="csrf_token"]').value},
        credentials: 'same-origin', signal: controller.signal
      });
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Não foi possível conferir os horários. Atualize a página e tente novamente.');
      }
      const result = await response.json();
      panel.replaceChildren();
      if (!response.ok || !result.ok) {
        throw new Error(result.erro || 'Não foi possível conferir a programação. Revise os dados.');
      }
      const times = result.horarios || [];
      const mode = form.querySelector('[data-ih-modo]').value;
      if (mode === 'prn') {
        appendParagraph(panel, 'Prescrição se necessário (PRN)', true);
        appendParagraph(panel, 'Não gera doses programadas. A equipe registra a administração quando a condição indicada ocorrer, respeitando o intervalo mínimo e o limite em 24 horas.');
      } else {
        appendParagraph(panel, `${result.total ?? times.length} dose(s) prevista(s) · Horários de Brasília`, true);
        const list = document.createElement('ol');
        times.slice(0, 24).forEach(function (value) {
          const item = document.createElement('li');
          item.textContent = dateFormat.format(new Date(value));
          list.appendChild(item);
        });
        panel.appendChild(list);
        if (times.length > 24) appendParagraph(panel, `Mostrando os primeiros 24 horários de ${times.length}. Os demais seguirão a mesma programação até o término informado.`);
      }
      form.dataset.ihPreviewValid = 'true';
      appendParagraph(panel, 'Confira os horários e clique novamente em “Ativar prescrição” ou “Ativar nova versão” para confirmar.');
      return true;
    } catch (error) {
      panel.replaceChildren();
      appendParagraph(panel, error.name === 'AbortError' ? 'A conexão demorou a responder. A prescrição ainda não foi ativada. Tente conferir novamente.' : (error.message || 'Falha de conexão. A prescrição ainda não foi ativada.'));
      form.dataset.ihPreviewValid = 'false';
      return false;
    } finally {
      button.disabled = false;
      form.dataset.ihPreviewPending = 'false';
      window.clearTimeout(timeout);
    }
  }

  function setupMedicationSearch(form) {
    const input = form.querySelector('[data-ih-medicamento]');
    if (!input) return;
    const suggestions = document.getElementById(input.getAttribute('list'));
    if (!suggestions) return;
    let debounceTimer;
    let controller;
    let sequence = 0;

    input.addEventListener('input', function () {
      window.clearTimeout(debounceTimer);
      if (controller) controller.abort();
      const query = input.value.trim();
      const currentSequence = ++sequence;
      suggestions.replaceChildren();
      if (query.length < 2) return;
      debounceTimer = window.setTimeout(async function () {
        controller = new AbortController();
        const searchController = controller;
        const timeout = window.setTimeout(function () { searchController.abort(); }, 8000);
        try {
          const url = new URL(input.dataset.searchUrl, window.location.origin);
          url.searchParams.set('q', query);
          const response = await fetch(url, {
            headers: {Accept: 'application/json'}, credentials: 'same-origin', signal: searchController.signal
          });
          if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
          const items = await response.json();
          if (currentSequence !== sequence || !Array.isArray(items)) return;
          suggestions.replaceChildren();
          items.slice(0, 12).forEach(function (item) {
            const name = item.nome_exibicao || item.nome_exibicao_busca || item.nome;
            if (typeof name !== 'string' || !name.trim()) return;
            const option = document.createElement('option');
            option.value = name;
            suggestions.appendChild(option);
          });
        } catch (_error) {
          // A busca é auxiliar: o nome digitado continua disponível sem conexão.
        } finally {
          window.clearTimeout(timeout);
        }
      }, 250);
    });
  }

  document.querySelectorAll('[data-ih-prescricao]').forEach(function (form) {
    setupMedicationSearch(form);
    syncPrescriptionFields(form);
    form.addEventListener('input', function () {
      form.dataset.ihPreviewValid = 'false';
      const panel = form.querySelector('[data-ih-preview]');
      if (!panel.hidden) {
        panel.replaceChildren();
        appendParagraph(panel, 'A prescrição foi alterada. Confira os horários novamente antes de ativar.');
      }
    });
    form.querySelector('[data-ih-modo]').addEventListener('change', function () {
      syncPrescriptionFields(form);
    });
    form.querySelector('[data-ih-preview-button]').addEventListener('click', function () {
      previewPrescription(form);
    });
    form.addEventListener('submit', function (event) {
      if (form.dataset.ihPreviewValid !== 'true') {
        event.preventDefault();
        previewPrescription(form).then(function () {
          form.querySelector('[data-ih-preview]').scrollIntoView({behavior: 'smooth', block: 'center'});
        });
        return;
      }
      form.querySelectorAll('button[type="submit"]').forEach(function (button) {
        button.disabled = true;
        button.dataset.ihOriginalLabel = button.textContent;
        button.textContent = 'Salvando…';
      });
    });
  });

  document.querySelectorAll('[data-ih-submit]').forEach(function (form) {
    const result = form.querySelector('[data-ih-resultado]');
    const reason = form.querySelector('[data-ih-motivo]');
    const retrospective = form.querySelector('[data-ih-retrospectivo]');
    const reasonRequired = reason ? reason.required : false;
    function syncReason() {
      if (reason) reason.required = reasonRequired || Boolean((result && result.value === 'omitida') || (retrospective && retrospective.value));
    }
    if (result) result.addEventListener('change', syncReason);
    if (retrospective) retrospective.addEventListener('input', syncReason);
    syncReason();
    form.addEventListener('submit', function () {
      form.querySelectorAll('button[type="submit"]').forEach(function (button) {
        button.disabled = true;
        button.dataset.ihOriginalLabel = button.textContent;
        button.textContent = 'Salvando…';
      });
    });
  });

  function setupInternacaoTabs() {
    const nav = document.getElementById('internacaoTabs');
    const container = document.getElementById('internacaoTabContent');
    if (!nav || !container) return;

    const STORAGE_KEY = 'abaAtivaInternacao';
    const tabLinks = Array.from(nav.querySelectorAll('[data-bs-target], [href^="#"]'));
    const panes = Array.from(container.querySelectorAll('.tab-pane'));

    function getTargetId(link) {
      if (!link) return '';
      const target = link.getAttribute('data-bs-target') || link.getAttribute('href') || '';
      return target.replace(/^#/, '');
    }

    function activateTab(targetId, updateHash, scrollTarget) {
      if (!targetId) return false;
      const cleanId = targetId.replace(/^#/, '');
      const targetPane = document.getElementById(cleanId);
      if (!targetPane || !panes.includes(targetPane)) return false;

      tabLinks.forEach(function (link) {
        const isCurrent = getTargetId(link) === cleanId;
        link.classList.toggle('active', isCurrent);
        link.setAttribute('aria-selected', isCurrent ? 'true' : 'false');
        link.setAttribute('tabindex', isCurrent ? '0' : '-1');
      });

      panes.forEach(function (pane) {
        const isCurrent = pane === targetPane;
        pane.classList.toggle('active', isCurrent);
        pane.classList.toggle('show', isCurrent);
      });

      try {
        window.localStorage.setItem(STORAGE_KEY, cleanId);
      } catch (_e) {}

      if (updateHash) {
        if (window.history && window.history.replaceState) {
          window.history.replaceState(null, '', '#' + cleanId);
        } else {
          window.location.hash = '#' + cleanId;
        }
      }

      if (scrollTarget) {
        if (scrollTarget.tagName === 'DETAILS') {
          scrollTarget.open = true;
        }
        if (typeof scrollTarget.scrollIntoView === 'function') {
          window.setTimeout(function () {
            scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }, 60);
        }
      }

      return true;
    }

    nav.addEventListener('click', function (event) {
      const link = event.target.closest('[data-bs-target], [href^="#"]');
      if (!link || !nav.contains(link)) return;
      const targetId = getTargetId(link);
      if (targetId) {
        event.preventDefault();
        activateTab(targetId, true);
      }
    });

    function resolveLocationHash() {
      const hash = window.location.hash ? window.location.hash.slice(1) : '';
      if (!hash) return false;

      if (activateTab(hash, false)) {
        return true;
      }

      const element = document.getElementById(hash);
      if (element) {
        const parentPane = element.closest('.tab-pane');
        if (parentPane && panes.includes(parentPane)) {
          activateTab(parentPane.id, false, element);
          return true;
        }
      }

      return false;
    }

    let initialized = resolveLocationHash();
    if (!initialized) {
      let saved = null;
      try {
        saved = window.localStorage.getItem(STORAGE_KEY);
      } catch (_e) {}
      if (saved && activateTab(saved, false)) {
        initialized = true;
      }
    }
    if (!initialized && panes.length > 0) {
      activateTab(panes[0].id, false);
    }

    window.addEventListener('hashchange', function () {
      resolveLocationHash();
    });

    document.addEventListener('click', function (event) {
      const anchor = event.target.closest('a[href^="#"]');
      if (!anchor || nav.contains(anchor)) return;
      const href = anchor.getAttribute('href');
      if (!href || href === '#') return;
      const hash = href.slice(1);
      if (!hash) return;
      const element = document.getElementById(hash);
      if (!element) return;

      const parentPane = element.closest('.tab-pane');
      if (parentPane && panes.includes(parentPane)) {
        event.preventDefault();
        activateTab(parentPane.id, true, element);
      }
    });
  }

  setupInternacaoTabs();

  window.addEventListener('pageshow', function () {
    document.querySelectorAll('button[data-ih-original-label]').forEach(function (button) {
      button.disabled = false;
      button.textContent = button.dataset.ihOriginalLabel;
    });
  });
})();
