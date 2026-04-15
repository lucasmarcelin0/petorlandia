(function(window, document) {
  'use strict';

  const PANEL_TYPES = {
    animals: {
      filterSelector: '#animal-filter',
      sortSelector: '#animal-sort',
      cardsSelector: '#animal-cards',
      paginationContainerSelector: '[data-animal-pagination-container]',
      paginationScopeSelector: '[data-animal-pagination]',
      storagePrefix: 'animal',
      defaultSort: 'date_desc',
    },
    tutors: {
      filterSelector: '#tutor-filter',
      sortSelector: '#tutor-sort',
      cardsSelector: '#tutor-cards',
      paginationContainerSelector: '[data-tutor-pagination-container]',
      paginationScopeSelector: '[data-tutor-pagination]',
      storagePrefix: 'tutor',
      defaultSort: 'name_asc',
      statusFilterSelector: '[data-status-filter]',
      applyButtonSelector: '[data-apply-filter]',
    },
  };

  const panelStates = new WeakMap();
  const debounceTimers = new WeakMap();
  const activeControllers = new WeakMap();

  // ── Estado de UI ──────────────────────────────────────────────────────────

  function setLoadingState(panel, loading) {
    const panelData = panelStates.get(panel);
    if (!panelData) return;
    const { cardsContainer } = panelData;

    panel.dataset.listingLoading = loading ? 'true' : 'false';

    // Spinner sobre os cards
    const existing = panel.querySelector('[data-listing-spinner]');
    if (loading) {
      if (!existing && cardsContainer) {
        const spinner = document.createElement('div');
        spinner.setAttribute('data-listing-spinner', '');
        spinner.className = 'listing-panel-spinner';
        spinner.innerHTML = '<div class="spinner-border spinner-border-sm text-primary me-2" role="status"></div><span>Carregando…</span>';
        cardsContainer.parentNode.insertBefore(spinner, cardsContainer);
        cardsContainer.style.opacity = '0.45';
        cardsContainer.style.pointerEvents = 'none';
      }
    } else {
      if (existing) existing.remove();
      if (cardsContainer) {
        cardsContainer.style.opacity = '';
        cardsContainer.style.pointerEvents = '';
      }
    }
  }

  function setErrorState(panel, hasError, onRetry) {
    const existing = panel.querySelector('[data-listing-error]');
    if (hasError) {
      if (!existing) {
        const err = document.createElement('div');
        err.setAttribute('data-listing-error', '');
        err.className = 'listing-panel-error alert alert-warning d-flex align-items-center gap-3 mt-2 mb-0';
        err.innerHTML = `
          <i class="fas fa-exclamation-triangle"></i>
          <span class="flex-grow-1">Não foi possível atualizar os resultados.</span>
          <button type="button" class="btn btn-sm btn-outline-warning ms-auto" data-retry>
            <i class="fas fa-rotate-right me-1"></i>Tentar novamente
          </button>`;
        const retryBtn = err.querySelector('[data-retry]');
        if (retryBtn && onRetry) {
          retryBtn.addEventListener('click', () => {
            err.remove();
            onRetry();
          });
        }
        panel.querySelector('[data-listing-spinner]')?.remove();
        const panelData = panelStates.get(panel);
        if (panelData && panelData.cardsContainer) {
          panelData.cardsContainer.parentNode.insertBefore(err, panelData.cardsContainer);
          panelData.cardsContainer.style.opacity = '';
          panelData.cardsContainer.style.pointerEvents = '';
        } else {
          panel.prepend(err);
        }
      }
    } else {
      if (existing) existing.remove();
    }
  }

  // ── Status filters ────────────────────────────────────────────────────────

  function collectStatusFilters(inputs) {
    if (!inputs || inputs.length === 0) {
      return new Set();
    }
    return new Set(
      Array.from(inputs)
        .filter((input) => input instanceof HTMLInputElement && input.checked)
        .map((input) => input.value)
    );
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  function initAllPanels(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('[data-listing-panel]').forEach(initPanel);
  }

  function initPanel(panel) {
    if (!(panel instanceof Element)) return;
    if (panel.dataset.listingInitialized === 'true') return;

    const type = panel.dataset.listingPanel || 'animals';
    const typeConfig = PANEL_TYPES[type];
    if (!typeConfig) return;

    const config = {
      type,
      fetchUrl: panel.dataset.fetchUrl || window.location.pathname,
      scopeParam: panel.dataset.scopeParam || 'scope',
      searchParam: panel.dataset.searchParam || (type === 'tutors' ? 'tutor_search' : 'animal_search'),
      sortParam: panel.dataset.sortParam || (type === 'tutors' ? 'tutor_sort' : 'animal_sort'),
      pageParam: panel.dataset.pageParam || 'page',
      defaultSort: panel.dataset.defaultSort || typeConfig.defaultSort,
      storagePrefix: panel.dataset.storageKey || typeConfig.storagePrefix,
      filterSelector: typeConfig.filterSelector,
      sortSelector: typeConfig.sortSelector,
      cardsSelector: typeConfig.cardsSelector,
      paginationContainerSelector: typeConfig.paginationContainerSelector,
      paginationScopeSelector: typeConfig.paginationScopeSelector,
      applyButtonSelector: typeConfig.applyButtonSelector || null,
    };

    const filterInput = panel.querySelector(config.filterSelector);
    const sortSelect = panel.querySelector(config.sortSelector);
    const cardsContainer = panel.querySelector(config.cardsSelector);
    const statusFilterInputs = config.statusFilterSelector
      ? panel.querySelectorAll(config.statusFilterSelector)
      : null;
    const applyButton = config.applyButtonSelector
      ? panel.querySelector(config.applyButtonSelector)
      : null;

    const state = {
      scope: panel.dataset.scope || 'all',
      page: parseInt(panel.dataset.page || '1', 10) || 1,
      search: filterInput ? filterInput.value.trim() : '',
      sort: sortSelect ? sortSelect.value : config.defaultSort,
      statusFilters: collectStatusFilters(statusFilterInputs),
    };

    const persisted = restorePreferences(config, state, filterInput, sortSelect, statusFilterInputs);

    panel.dataset.listingInitialized = 'true';
    panelStates.set(panel, { config, state, filterInput, sortSelect, cardsContainer, statusFilterInputs });

    // ── Listeners ──────────────────────────────────────────────────────────

    if (filterInput) {
      filterInput.addEventListener('input', () => {
        const { state: panelState, config: panelConfig } = panelStates.get(panel) || {};
        if (!panelState) return;
        panelState.search = filterInput.value.trim();
        persistPreference(panelConfig.storagePrefix, 'Filter', filterInput.value);
        setErrorState(panel, false);
        scheduleFetch(panel, 1);
      });

      // Enter dispara imediatamente sem esperar debounce
      filterInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          clearTimeout(debounceTimers.get(panel));
          setErrorState(panel, false);
          fetchPage(panel, 1);
        }
      });
    }

    if (sortSelect) {
      sortSelect.addEventListener('change', () => {
        const { state: panelState, config: panelConfig } = panelStates.get(panel) || {};
        if (!panelState) return;
        panelState.sort = sortSelect.value;
        persistPreference(panelConfig.storagePrefix, 'Sort', sortSelect.value);
        setErrorState(panel, false);
        fetchPage(panel, 1);
      });
    }

    // Botão "Aplicar filtros" — dispara fetch imediato
    if (applyButton) {
      applyButton.addEventListener('click', () => {
        const panelData = panelStates.get(panel);
        if (!panelData) return;
        // Sincroniza estado com campos atuais antes de buscar
        if (filterInput) panelData.state.search = filterInput.value.trim();
        if (sortSelect) panelData.state.sort = sortSelect.value;
        clearTimeout(debounceTimers.get(panel));
        setErrorState(panel, false);
        fetchPage(panel, 1);
      });
    }

    if (statusFilterInputs && statusFilterInputs.length) {
      statusFilterInputs.forEach((input) => {
        input.addEventListener('change', () => {
          const panelData = panelStates.get(panel);
          if (!panelData) return;
          const { state: panelState, config: panelConfig, statusFilterInputs: storedInputs } = panelData;
          panelState.statusFilters = collectStatusFilters(storedInputs);
          persistPreference(
            panelConfig.storagePrefix,
            'StatusFilters',
            JSON.stringify(Array.from(panelState.statusFilters))
          );
          applyStatusFilters(panel);
        });
      });
    }

    panel.addEventListener('click', (event) => {
      const panelData = panelStates.get(panel);
      if (!panelData) return;
      const { state: panelState } = panelData;

      const scopeLink = event.target.closest('[data-scope-value]');
      if (scopeLink && panel.contains(scopeLink)) {
        event.preventDefault();
        const newScope = scopeLink.dataset.scopeValue || 'all';
        if (panelState.scope !== newScope) {
          panelState.scope = newScope;
          updateScopeButtons(panel, newScope);
          setErrorState(panel, false);
          fetchPage(panel, 1);
        }
        return;
      }

      const paginationContainer = panel.querySelector(panelData.config.paginationContainerSelector);
      if (!paginationContainer) return;

      const pageLink = event.target.closest('[data-page]');
      if (pageLink && paginationContainer.contains(pageLink)) {
        const parentItem = pageLink.closest('.page-item');
        if (parentItem && parentItem.classList.contains('disabled')) {
          event.preventDefault();
          return;
        }
        const pageValue = parseInt(pageLink.dataset.page || '1', 10);
        if (!Number.isNaN(pageValue) && pageValue !== panelState.page) {
          event.preventDefault();
          setErrorState(panel, false);
          fetchPage(panel, pageValue);
        }
      }
    });

    updateScopeButtons(panel, state.scope);
    applyStatusFilters(panel);

    if (persisted.shouldFetch) {
      fetchPage(panel, 1);
    } else {
      syncUrl(panel);
    }
  }

  // ── Preferências ──────────────────────────────────────────────────────────

  function restorePreferences(config, state, filterInput, sortSelect, statusFilterInputs) {
    let shouldFetch = false;
    if (!config.storagePrefix) return { shouldFetch };

    try {
      if (filterInput && !state.search) {
        const storedFilter = window.localStorage.getItem(`${config.storagePrefix}Filter`);
        if (storedFilter) {
          filterInput.value = storedFilter;
          state.search = storedFilter.trim();
          shouldFetch = shouldFetch || Boolean(state.search);
        }
      }
      if (sortSelect) {
        const storedSort = window.localStorage.getItem(`${config.storagePrefix}Sort`);
        if (storedSort && Array.from(sortSelect.options).some((opt) => opt.value === storedSort)) {
          if (state.sort !== storedSort) {
            sortSelect.value = storedSort;
            state.sort = storedSort;
            shouldFetch = true;
          }
        }
      }
      if (statusFilterInputs && statusFilterInputs.length) {
        const storedStatuses = window.localStorage.getItem(`${config.storagePrefix}StatusFilters`);
        if (storedStatuses !== null) {
          let parsed;
          try {
            parsed = JSON.parse(storedStatuses);
          } catch (error) {
            parsed = storedStatuses.split(',').map((v) => v.trim()).filter(Boolean);
          }
          const availableValues = new Set(Array.from(statusFilterInputs).map((input) => input.value));
          const normalized = Array.isArray(parsed) ? parsed.filter((v) => availableValues.has(v)) : [];
          const statusSet = new Set(normalized);
          statusFilterInputs.forEach((input) => { input.checked = statusSet.has(input.value); });
          state.statusFilters = statusSet;
        } else {
          state.statusFilters = collectStatusFilters(statusFilterInputs);
        }
      }
    } catch (error) {
      console.warn('Unable to access localStorage for listing panel preferences.', error);
    }

    return { shouldFetch };
  }

  function persistPreference(prefix, suffix, value) {
    if (!prefix) return;
    try {
      window.localStorage.setItem(`${prefix}${suffix}`, value);
    } catch (error) {
      console.warn('Unable to persist listing panel preference.', error);
    }
  }

  // ── Fetch ─────────────────────────────────────────────────────────────────

  function scheduleFetch(panel, page) {
    clearTimeout(debounceTimers.get(panel));
    const timer = window.setTimeout(() => fetchPage(panel, page), 400);
    debounceTimers.set(panel, timer);
  }

  async function fetchPage(panel, page) {
    const panelData = panelStates.get(panel);
    if (!panelData) return;
    const { state, config } = panelData;
    state.page = page;

    const requestUrl = buildRequestUrl(panel, config, state);

    const previousController = activeControllers.get(panel);
    if (previousController) previousController.abort();
    const controller = new AbortController();
    activeControllers.set(panel, controller);

    setLoadingState(panel, true);

    let response;
    try {
      response = await fetch(requestUrl.toString(), {
        headers: {
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        credentials: 'same-origin',
        signal: controller.signal,
      });
    } catch (error) {
      if (error.name === 'AbortError') {
        setLoadingState(panel, false);
        return;
      }
      console.error('Listing panel request failed.', error);
      setLoadingState(panel, false);
      setErrorState(panel, true, () => fetchPage(panel, page));
      return;
    } finally {
      activeControllers.delete(panel);
    }

    setLoadingState(panel, false);

    if (!response || !response.ok) {
      console.warn('Listing panel received non-ok response:', response?.status);
      setErrorState(panel, true, () => fetchPage(panel, page));
      return;
    }

    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      console.error('Invalid JSON response for listing panel.', error);
      setErrorState(panel, true, () => fetchPage(panel, page));
      return;
    }

    if (!payload || typeof payload.html !== 'string') {
      console.warn('Listing panel response missing html payload.');
      setErrorState(panel, true, () => fetchPage(panel, page));
      return;
    }

    setErrorState(panel, false);
    updatePanelFromHtml(panel, payload.html, panelData);
    syncUrl(panel);
    updateScopeButtons(panel, state.scope);
    if (typeof window.initializePopovers === 'function') {
      window.initializePopovers();
    }
    panel.dispatchEvent(new CustomEvent('listingpanel:updated', {
      detail: { panel, state: { ...state } },
    }));
  }

  // ── URL ───────────────────────────────────────────────────────────────────

  function buildRequestUrl(panel, config, state) {
    const url = new URL(config.fetchUrl || window.location.pathname, window.location.origin);
    const params = new URLSearchParams(window.location.search);

    if (state.scope) params.set(config.scopeParam, state.scope);

    if (state.search) {
      params.set(config.searchParam, state.search);
    } else {
      params.delete(config.searchParam);
    }

    if (state.sort && state.sort !== config.defaultSort) {
      params.set(config.sortParam, state.sort);
    } else {
      params.delete(config.sortParam);
    }

    if (state.page && state.page > 1) {
      params.set(config.pageParam, state.page);
    } else {
      params.delete(config.pageParam);
    }

    url.search = params.toString();
    return url;
  }

  // ── Atualização do painel ─────────────────────────────────────────────────

  function updatePanelFromHtml(panel, html, panelData) {
    const template = document.createElement('div');
    template.innerHTML = html;
    const newPanel = template.querySelector(`[data-listing-panel="${panel.dataset.listingPanel}"]`);
    if (!newPanel) return;

    const { config, state, filterInput, sortSelect, cardsContainer } = panelData;

    const newCards = newPanel.querySelector(config.cardsSelector);
    if (newCards && cardsContainer) {
      cardsContainer.innerHTML = newCards.innerHTML;
    }

    const currentPagination = panel.querySelector(config.paginationContainerSelector);
    const newPagination = newPanel.querySelector(config.paginationContainerSelector);
    if (currentPagination) {
      if (newPagination) {
        currentPagination.replaceWith(newPagination);
      } else {
        currentPagination.innerHTML = '';
        currentPagination.classList.add('d-none');
      }
    } else if (newPagination) {
      if (cardsContainer) {
        cardsContainer.insertAdjacentElement('afterend', newPagination);
      } else {
        panel.appendChild(newPagination);
      }
    }

    // Não sobrescreve o valor do filtro de texto (usuário pode ter digitado
    // mais enquanto o request estava em voo).

    // Não sobrescreve state.sort pelo HTML do servidor — confiamos no estado
    // do cliente. O servidor retornou os dados na ordem certa; não precisamos
    // reler o <select> da resposta para evitar sobrescrever a seleção atual.

    state.scope = newPanel.dataset.scope || state.scope;
    panel.dataset.scope = state.scope;

    const newPage = parseInt(newPanel.dataset.page || `${state.page}`, 10);
    if (!Number.isNaN(newPage)) {
      state.page = newPage;
      panel.dataset.page = String(state.page);
    }

    applyStatusFilters(panel);
  }

  // ── Sync URL ──────────────────────────────────────────────────────────────

  function syncUrl(panel) {
    const panelData = panelStates.get(panel);
    if (!panelData) return;
    const { config, state } = panelData;

    const url = new URL(window.location.href);

    if (state.scope) {
      url.searchParams.set(config.scopeParam, state.scope);
    } else {
      url.searchParams.delete(config.scopeParam);
    }

    if (state.search) {
      url.searchParams.set(config.searchParam, state.search);
    } else {
      url.searchParams.delete(config.searchParam);
    }

    if (state.sort && state.sort !== config.defaultSort) {
      url.searchParams.set(config.sortParam, state.sort);
    } else {
      url.searchParams.delete(config.sortParam);
    }

    if (state.page && state.page > 1) {
      url.searchParams.set(config.pageParam, state.page);
    } else {
      url.searchParams.delete(config.pageParam);
    }

    const searchString = url.searchParams.toString();
    const newUrl = `${url.pathname}${searchString ? `?${searchString}` : ''}${url.hash}`;
    if (newUrl !== window.location.href) {
      window.history.replaceState({}, '', newUrl);
    }
  }

  // ── Scope buttons ─────────────────────────────────────────────────────────

  function updateScopeButtons(panel, activeScope) {
    panel.querySelectorAll('[data-scope-value]').forEach((link) => {
      const isActive = (link.dataset.scopeValue || 'all') === activeScope;
      link.classList.toggle('active', isActive);
      if (isActive) {
        link.setAttribute('aria-current', 'true');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  // ── Status filters ────────────────────────────────────────────────────────

  function applyStatusFilters(panel) {
    const panelData = panelStates.get(panel);
    if (!panelData) return;
    const { config, state, cardsContainer, statusFilterInputs } = panelData;
    if (!config.statusFilterSelector || !statusFilterInputs || !statusFilterInputs.length || !cardsContainer) return;

    const cards = cardsContainer.querySelectorAll('[data-status]');
    if (!cards.length) return;

    const activeFilters = Array.from(state.statusFilters || []);
    const hasActiveFilters = activeFilters.length > 0;
    cards.forEach((card) => {
      const cardStatuses = (card.dataset.status || '')
        .split(/\s+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const matches = hasActiveFilters
        ? activeFilters.some((status) => cardStatuses.includes(status))
        : false;
      card.classList.toggle('d-none', !matches);
    });
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', () => {
    initAllPanels(document);
  });

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        if (node.matches('[data-listing-panel]')) initPanel(node);
        node.querySelectorAll?.('[data-listing-panel]').forEach(initPanel);
      });
    }
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.PetorlandiaPanels = window.PetorlandiaPanels || {};
  window.PetorlandiaPanels.refreshListings = () => initAllPanels(document);

})(window, document);
