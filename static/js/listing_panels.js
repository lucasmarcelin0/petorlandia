(function(window, document) {
  'use strict';

  const PANEL_TYPES = {
    animals: {
      filterSelector: '#animal-filter',
      sortSelector: '#animal-sort',
      speciesFilterSelector: '#animal-species-filter',
      statusFilterSelector: '#animal-status-filter',
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
    },
  };

  const panelStates = new WeakMap();
  const debounceTimers = new WeakMap();
  const activeControllers = new WeakMap();

  function initAllPanels(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('[data-listing-panel]').forEach(initPanel);
  }

  function initPanel(panel) {
    if (!(panel instanceof Element)) {
      return;
    }
    if (panel.dataset.listingInitialized === 'true') {
      return;
    }

    const type = panel.dataset.listingPanel || 'animals';
    const typeConfig = PANEL_TYPES[type];
    if (!typeConfig) {
      return;
    }

    const config = {
      type,
      fetchUrl: panel.dataset.fetchUrl || window.location.pathname,
      scopeParam: panel.dataset.scopeParam || 'scope',
      searchParam: panel.dataset.searchParam || (type === 'tutors' ? 'tutor_search' : 'animal_search'),
      sortParam: panel.dataset.sortParam || (type === 'tutors' ? 'tutor_sort' : 'animal_sort'),
      pageParam: panel.dataset.pageParam || 'page',
      defaultSort: panel.dataset.defaultSort || typeConfig.defaultSort,
      storagePrefix: panel.dataset.storageKey || typeConfig.storagePrefix,
      speciesParam: panel.dataset.speciesParam || 'animal_species',
      statusParam: panel.dataset.statusParam || 'animal_status',
      speciesFilterSelector: typeConfig.speciesFilterSelector,
      statusFilterSelector: typeConfig.statusFilterSelector,
      filterSelector: typeConfig.filterSelector,
      sortSelector: typeConfig.sortSelector,
      cardsSelector: typeConfig.cardsSelector,
      paginationContainerSelector: typeConfig.paginationContainerSelector,
      paginationScopeSelector: typeConfig.paginationScopeSelector,
    };

    const filterInput = panel.querySelector(config.filterSelector);
    const sortSelect = panel.querySelector(config.sortSelector);
    const cardsContainer = panel.querySelector(config.cardsSelector);
    const speciesSelect = config.speciesFilterSelector
      ? panel.querySelector(config.speciesFilterSelector)
      : null;
    const statusSelect = config.statusFilterSelector
      ? panel.querySelector(config.statusFilterSelector)
      : null;

    const state = {
      scope: panel.dataset.scope || 'all',
      page: parseInt(panel.dataset.page || '1', 10) || 1,
      search: filterInput ? filterInput.value.trim() : '',
      sort: sortSelect ? sortSelect.value : config.defaultSort,
      species: panel.dataset.species || (speciesSelect ? speciesSelect.value : ''),
      status: panel.dataset.status || (statusSelect ? statusSelect.value : ''),
    };

    const persisted = restorePreferences(config, state, filterInput, sortSelect);

    panel.dataset.listingInitialized = 'true';
    panelStates.set(panel, { config, state, filterInput, sortSelect, cardsContainer, speciesSelect, statusSelect });

    if (filterInput) {
      filterInput.addEventListener('input', () => {
        const { state: panelState, config: panelConfig } = panelStates.get(panel) || {};
        if (!panelState) return;
        panelState.search = filterInput.value.trim();
        persistPreference(panelConfig.storagePrefix, 'Filter', filterInput.value);
        scheduleFetch(panel, 1);
      });
    }

    if (sortSelect) {
      sortSelect.addEventListener('change', () => {
        const { state: panelState, config: panelConfig } = panelStates.get(panel) || {};
        if (!panelState) return;
        panelState.sort = sortSelect.value;
        persistPreference(panelConfig.storagePrefix, 'Sort', sortSelect.value);
        fetchPage(panel, 1);
      });
    }

    if (speciesSelect) {
      speciesSelect.addEventListener('change', () => {
        const panelData = panelStates.get(panel);
        if (!panelData) return;
        panelData.state.species = speciesSelect.value;
        fetchPage(panel, 1);
      });
    }

    if (statusSelect) {
      statusSelect.addEventListener('change', () => {
        const panelData = panelStates.get(panel);
        if (!panelData) return;
        panelData.state.status = statusSelect.value;
        fetchPage(panel, 1);
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
          fetchPage(panel, 1);
        }
        return;
      }

      const paginationContainer = panel.querySelector(panelData.config.paginationContainerSelector);
      if (!paginationContainer) {
        return;
      }

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
          fetchPage(panel, pageValue);
        }
      }
    });

    updateScopeButtons(panel, state.scope);
    if (persisted.shouldFetch) {
      fetchPage(panel, 1);
    } else {
      syncUrl(panel);
    }
  }

  function restorePreferences(config, state, filterInput, sortSelect) {
    let shouldFetch = false;
    if (!config.storagePrefix) {
      return { shouldFetch };
    }

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

  function scheduleFetch(panel, page) {
    clearTimeout(debounceTimers.get(panel));
    const timer = window.setTimeout(() => fetchPage(panel, page), 250);
    debounceTimers.set(panel, timer);
  }

  async function fetchPage(panel, page) {
    const panelData = panelStates.get(panel);
    if (!panelData) return;
    const { state, config } = panelData;
    state.page = page;

    const requestUrl = buildRequestUrl(panel, config, state);

    const previousController = activeControllers.get(panel);
    if (previousController) {
      previousController.abort();
    }
    const controller = new AbortController();
    activeControllers.set(panel, controller);

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
        return;
      }
      console.error('Listing panel request failed, falling back to navigation.', error);
      window.location.href = requestUrl.toString();
      return;
    } finally {
      activeControllers.delete(panel);
    }

    if (!response || !response.ok) {
      window.location.href = requestUrl.toString();
      return;
    }

    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      console.error('Invalid JSON response for listing panel.', error);
      window.location.href = requestUrl.toString();
      return;
    }

    if (!payload || typeof payload.html !== 'string') {
      window.location.href = requestUrl.toString();
      return;
    }

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

  function buildRequestUrl(panel, config, state) {
    const url = new URL(config.fetchUrl || window.location.pathname, window.location.origin);
    const params = new URLSearchParams(window.location.search);

    if (state.scope) {
      params.set(config.scopeParam, state.scope);
    }
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
    if (config.speciesParam) {
      if (state.species) {
        params.set(config.speciesParam, state.species);
      } else {
        params.delete(config.speciesParam);
      }
    }
    if (config.statusParam) {
      if (state.status) {
        params.set(config.statusParam, state.status);
      } else {
        params.delete(config.statusParam);
      }
    }
    if (state.page && state.page > 1) {
      params.set(config.pageParam, state.page);
    } else {
      params.delete(config.pageParam);
    }

    url.search = params.toString();
    return url;
  }

  function updatePanelFromHtml(panel, html, panelData) {
    const template = document.createElement('div');
    template.innerHTML = html;
    const newPanel = template.querySelector(`[data-listing-panel="${panel.dataset.listingPanel}"]`);
    if (!newPanel) {
      return;
    }

    const { config, state, filterInput, sortSelect, cardsContainer, speciesSelect, statusSelect } = panelData;

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

    const newFilter = newPanel.querySelector(config.filterSelector);
    if (newFilter && filterInput) {
      filterInput.value = newFilter.value;
      state.search = filterInput.value.trim();
    }

    const newSort = newPanel.querySelector(config.sortSelector);
    if (newSort && sortSelect) {
      sortSelect.value = newSort.value;
      state.sort = sortSelect.value;
    }

    if (config.speciesFilterSelector && speciesSelect) {
      const newSpecies = newPanel.querySelector(config.speciesFilterSelector);
      if (newSpecies) {
        speciesSelect.innerHTML = newSpecies.innerHTML;
        speciesSelect.value = newSpecies.value;
        state.species = speciesSelect.value;
      }
    }

    if (config.statusFilterSelector && statusSelect) {
      const newStatus = newPanel.querySelector(config.statusFilterSelector);
      if (newStatus) {
        statusSelect.innerHTML = newStatus.innerHTML;
        statusSelect.value = newStatus.value;
        state.status = statusSelect.value;
      }
    }

    state.scope = newPanel.dataset.scope || state.scope;
    panel.dataset.scope = state.scope;

    if (typeof newPanel.dataset.species === 'string') {
      state.species = newPanel.dataset.species;
      panel.dataset.species = state.species;
    }

    if (typeof newPanel.dataset.status === 'string') {
      state.status = newPanel.dataset.status;
      panel.dataset.status = state.status;
    }

    const newPage = parseInt(newPanel.dataset.page || `${state.page}`, 10);
    if (!Number.isNaN(newPage)) {
      state.page = newPage;
      panel.dataset.page = String(state.page);
    }
  }

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
    if (config.speciesParam) {
      if (state.species) {
        url.searchParams.set(config.speciesParam, state.species);
      } else {
        url.searchParams.delete(config.speciesParam);
      }
    }
    if (config.statusParam) {
      if (state.status) {
        url.searchParams.set(config.statusParam, state.status);
      } else {
        url.searchParams.delete(config.statusParam);
      }
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

  document.addEventListener('DOMContentLoaded', () => {
    initAllPanels(document);
  });

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) {
          return;
        }
        if (node.matches('[data-listing-panel]')) {
          initPanel(node);
        }
        node.querySelectorAll?.('[data-listing-panel]').forEach(initPanel);
      });
    }
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.PetorlandiaPanels = window.PetorlandiaPanels || {};
  window.PetorlandiaPanels.refreshListings = () => initAllPanels(document);
})(window, document);
