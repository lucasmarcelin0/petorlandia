(function(window, document) {
  'use strict';

  const PANEL_VALUES = {
    create: 'cadastro',
    list: 'listagem',
  };

  const VALUE_ALIASES = {
    cadastro: 'create',
    create: 'create',
    form: 'create',
    new: 'create',
    novo: 'create',
    listagem: 'list',
    list: 'list',
    listing: 'list',
    cadastrados: 'list',
    records: 'list',
  };

  function normalizePanel(value) {
    return VALUE_ALIASES[String(value || '').trim().toLowerCase()] || 'create';
  }

  function getPanelParam(root) {
    return root.dataset.panelParam || 'panel';
  }

  function escapeSelector(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
      return window.CSS.escape(value);
    }
    return String(value).replace(/["\\]/g, '\\$&');
  }

  function initAll(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('[data-record-panels]').forEach(initWorkspace);
  }

  function initWorkspace(root) {
    if (!(root instanceof Element)) return;
    if (root.dataset.recordPanelsInitialized === 'true') return;

    root.dataset.recordPanelsInitialized = 'true';
    root.querySelectorAll('[data-record-panel-button]').forEach((button) => {
      button.addEventListener('click', () => {
        openPanel(root, button.dataset.recordPanelButton, { updateUrl: true, focusPanel: true });
      });
    });

    root.addEventListener('click', (event) => {
      const trigger = event.target.closest('[data-record-open]');
      if (!trigger || !root.contains(trigger)) return;
      event.preventDefault();
      openPanel(root, trigger.dataset.recordOpen, { updateUrl: true, focusPanel: true });
    });

    const url = new URL(window.location.href);
    const requested = url.searchParams.get(getPanelParam(root));
    const initial = requested ? normalizePanel(requested) : normalizePanel(root.dataset.activePanel);
    openPanel(root, initial, { updateUrl: false, focusPanel: false });
  }

  function openPanel(rootOrKey, panelName, options) {
    const root = resolveRoot(rootOrKey);
    if (!root) return false;

    const targetPanel = normalizePanel(panelName);
    const opts = Object.assign({ updateUrl: false, focusPanel: false, loadDeferred: true }, options || {});

    root.dataset.activePanel = targetPanel;

    root.querySelectorAll('[data-record-panel-button]').forEach((button) => {
      const active = normalizePanel(button.dataset.recordPanelButton) === targetPanel;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) {
        button.setAttribute('tabindex', '0');
      } else {
        button.setAttribute('tabindex', '-1');
      }
    });

    let targetSection = null;
    root.querySelectorAll('[data-record-panel-section]').forEach((section) => {
      const active = normalizePanel(section.dataset.recordPanelSection) === targetPanel;
      section.hidden = !active;
      if (active) targetSection = section;
    });

    if (opts.updateUrl) {
      syncUrl(root, targetPanel);
    }

    if (targetSection && opts.loadDeferred) {
      loadDeferredListing(targetSection);
    }

    if (targetSection && opts.focusPanel) {
      window.requestAnimationFrame(() => {
        targetSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }

    return true;
  }

  function resolveRoot(rootOrKey) {
    if (rootOrKey instanceof Element) return rootOrKey;
    if (!rootOrKey) return document.querySelector('[data-record-panels]');
    return document.querySelector(`[data-record-panel-key="${escapeSelector(String(rootOrKey))}"]`);
  }

  function syncUrl(root, panelName) {
    const url = new URL(window.location.href);
    url.searchParams.set(getPanelParam(root), PANEL_VALUES[panelName] || panelName);
    const search = url.searchParams.toString();
    const nextUrl = `${url.pathname}${search ? `?${search}` : ''}${url.hash}`;
    if (nextUrl !== window.location.href) {
      window.history.replaceState({}, '', nextUrl);
    }
  }

  async function loadDeferredListing(section) {
    const placeholder = section.querySelector('[data-record-listing-placeholder]');
    if (!placeholder || placeholder.dataset.loading === 'true') return;

    const fetchUrl = placeholder.dataset.fetchUrl || window.location.href;
    const container = placeholder.closest('[data-record-listing-container]') || placeholder.parentElement;
    if (!container) return;

    placeholder.dataset.loading = 'true';
    clearPlaceholderError(placeholder);

    try {
      const response = await fetch(fetchUrl, {
        headers: {
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        credentials: 'same-origin',
        cache: 'no-store',
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const payload = await response.json();
      if (!payload || typeof payload.html !== 'string') {
        throw new Error('Missing listing html');
      }

      container.innerHTML = payload.html;
      if (window.PetorlandiaPanels && typeof window.PetorlandiaPanels.refreshListings === 'function') {
        window.PetorlandiaPanels.refreshListings();
      }
      if (typeof window.initializePopovers === 'function') {
        window.initializePopovers();
      }
      section.dispatchEvent(new CustomEvent('recordpanel:listingloaded', { bubbles: true }));
    } catch (error) {
      console.warn('[record-panels] listing load failed:', error);
      showPlaceholderError(placeholder);
      placeholder.dataset.loading = 'false';
    }
  }

  function showPlaceholderError(placeholder) {
    if (placeholder.querySelector('[data-record-placeholder-error]')) return;
    const error = document.createElement('span');
    error.dataset.recordPlaceholderError = 'true';
    error.className = 'text-warning ms-2';
    error.textContent = 'Nao foi possivel carregar.';
    placeholder.appendChild(error);
  }

  function clearPlaceholderError(placeholder) {
    placeholder.querySelector('[data-record-placeholder-error]')?.remove();
  }

  function highlightRecord(rootOrKey, selector) {
    const root = resolveRoot(rootOrKey);
    if (!root || !selector) return false;
    const target = root.querySelector(selector);
    if (!target) return false;

    const card = target.querySelector('.card') || target;
    card.classList.remove('record-highlight');
    void card.offsetWidth;
    card.classList.add('record-highlight');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
  }

  function scheduleHighlight(rootOrKey, selector) {
    if (!selector) return;
    let attempts = 0;
    const tryHighlight = () => {
      attempts += 1;
      if (highlightRecord(rootOrKey, selector) || attempts >= 12) return;
      window.setTimeout(tryHighlight, 180);
    };
    window.setTimeout(tryHighlight, 120);
  }

  document.addEventListener('DOMContentLoaded', () => initAll(document));

  document.addEventListener('form-sync-success', (event) => {
    const detail = event.detail || {};
    const form = detail.form;
    const data = detail.data || {};
    if (!form) return;

    if (form.classList.contains('js-tutor-form')) {
      openPanel('tutores', 'list', { updateUrl: true, focusPanel: false });
      if (data.tutor && data.tutor.id) {
        scheduleHighlight('tutores', `[data-tutor-id="${escapeSelector(String(data.tutor.id))}"]`);
      }
      return;
    }

    if (form.classList.contains('js-animal-form')) {
      openPanel('animais', 'list', { updateUrl: true, focusPanel: false });
      if (data.animal && data.animal.id) {
        scheduleHighlight('animais', `[data-animal-id="${escapeSelector(String(data.animal.id))}"]`);
      }
    }
  });

  window.PetorlandiaRecordPanels = {
    initAll,
    open: openPanel,
    highlight: highlightRecord,
  };
})(window, document);
