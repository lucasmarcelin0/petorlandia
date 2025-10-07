const DEFAULT_TIMEOUT_MS = 8000;

export class TutorSearchError extends Error {
  constructor(code, message, options = {}) {
    super(message);
    this.name = 'TutorSearchError';
    this.code = code;
    if (options.cause) {
      this.cause = options.cause;
    }
  }
}

function createTutorFetcher({ endpoint = '/buscar_tutores', timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  let activeController = null;

  return async function fetchTutors(query) {
    if (activeController) {
      // Abort the previous request before starting a new one.
      activeController.abort();
    }

    const controller = new AbortController();
    activeController = controller;

    let didTimeout = false;
    const timeoutId = setTimeout(() => {
      didTimeout = true;
      controller.abort();
    }, timeoutMs);

    try {
      const response = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`, {
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        signal: controller.signal,
      });

      if (response.status === 429) {
        throw new TutorSearchError(
          'rate_limit',
          'Muitas buscas seguidas. Aguarde um instante e tente novamente.'
        );
      }

      if (response.status >= 500) {
        throw new TutorSearchError(
          'server',
          'Não foi possível buscar os tutores agora. Tente novamente em instantes.'
        );
      }

      if (!response.ok) {
        throw new TutorSearchError(
          'http_error',
          'Não foi possível buscar os tutores. Verifique os dados e tente novamente.'
        );
      }

      return await response.json();
    } catch (error) {
      if (error.name === 'AbortError') {
        if (didTimeout) {
          throw new TutorSearchError(
            'timeout',
            'A busca demorou mais do que o esperado. Tente novamente.'
          );
        }
        return { aborted: true };
      }

      if (error instanceof TutorSearchError) {
        throw error;
      }

      throw new TutorSearchError('network', 'Não foi possível conectar ao servidor.', { cause: error });
    } finally {
      clearTimeout(timeoutId);
      if (activeController === controller) {
        activeController = null;
      }
    }
  };
}

const defaultFormatTutor = (tutor) => {
  if (!tutor) {
    return '';
  }
  const email = tutor.email ? ` (${tutor.email})` : '';
  return `${tutor.name || 'Tutor'}${email}`;
};

export function setupTutorSearch({
  input,
  resultsList,
  statusElement,
  endpoint = '/buscar_tutores',
  minChars = 2,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  formatTutor = defaultFormatTutor,
  onTutorSelected = () => {},
  retryLabel = 'Tentar novamente',
  emptyMessage = 'Nenhum tutor encontrado.',
  loadingMessage = 'Buscando tutores...',
  offlineMessage = 'Você está offline. Verifique sua conexão e tente novamente.',
} = {}) {
  if (!input || !resultsList) {
    return {
      hideResults: () => {},
      refresh: () => {},
      showResults: () => {},
    };
  }

  const fetchTutors = createTutorFetcher({ endpoint, timeoutMs });

  const state = {
    currentQuery: '',
    requestId: 0,
    lastResults: [],
  };

  const updateStatus = (message) => {
    if (statusElement) {
      statusElement.textContent = message || '';
    }
  };

  const setBusy = (busy) => {
    if (busy) {
      resultsList.setAttribute('aria-busy', 'true');
    } else {
      resultsList.removeAttribute('aria-busy');
    }
  };

  const showList = () => {
    resultsList.classList.remove('d-none');
    resultsList.dataset.visible = 'true';
    if (input) {
      input.setAttribute('aria-expanded', 'true');
    }
  };

  const hideList = () => {
    resultsList.classList.add('d-none');
    resultsList.dataset.visible = 'false';
    if (input) {
      input.setAttribute('aria-expanded', 'false');
    }
    setBusy(false);
  };

  const renderLoading = () => {
    resultsList.innerHTML = '';
    state.lastResults = [];
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex align-items-center gap-2';
    li.setAttribute('role', 'option');

    const spinner = document.createElement('span');
    spinner.className = 'spinner-border spinner-border-sm text-primary';
    spinner.setAttribute('role', 'status');
    spinner.setAttribute('aria-hidden', 'true');

    const text = document.createElement('span');
    text.textContent = loadingMessage;

    li.appendChild(spinner);
    li.appendChild(text);
    resultsList.appendChild(li);

    showList();
    updateStatus(loadingMessage);
    setBusy(true);
  };

  const renderEmpty = () => {
    resultsList.innerHTML = '';
    state.lastResults = [];
    const li = document.createElement('li');
    li.className = 'list-group-item text-muted';
    li.setAttribute('role', 'option');
    li.textContent = emptyMessage;
    resultsList.appendChild(li);

    showList();
    updateStatus(emptyMessage);
    setBusy(false);
  };

  const renderError = (error) => {
    resultsList.innerHTML = '';
    state.lastResults = [];

    const messageByCode = {
      offline: offlineMessage,
      timeout: 'A busca demorou mais do que o esperado. Tente novamente.',
      rate_limit: 'Muitas buscas seguidas. Aguarde alguns segundos antes de tentar novamente.',
      server: 'Não foi possível buscar os tutores agora. Tente novamente em instantes.',
      network: 'Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.',
    };

    const message = messageByCode[error.code] || error.message || 'Não foi possível buscar os tutores.';

    const li = document.createElement('li');
    li.className = 'list-group-item d-flex align-items-center gap-2';
    li.setAttribute('role', 'option');

    const text = document.createElement('span');
    text.textContent = message;
    li.appendChild(text);

    const retryButton = document.createElement('button');
    retryButton.type = 'button';
    retryButton.className = 'btn btn-sm btn-outline-secondary ms-auto';
    retryButton.textContent = retryLabel;
    retryButton.dataset.retrySearch = 'true';
    retryButton.setAttribute('aria-label', `${retryLabel}: ${message}`);
    li.appendChild(retryButton);

    resultsList.appendChild(li);

    showList();
    updateStatus(message);
    setBusy(false);
  };

  const renderResults = (tutors) => {
    resultsList.innerHTML = '';
    state.lastResults = tutors.slice();

    tutors.forEach((tutor, index) => {
      const li = document.createElement('li');
      li.className = 'list-group-item list-group-item-action';
      li.tabIndex = 0;
      li.dataset.tutorIndex = String(index);
      li.setAttribute('role', 'option');
      li.textContent = formatTutor(tutor, index, tutors);
      resultsList.appendChild(li);
    });

    showList();
    const countMessage = tutors.length === 1
      ? '1 tutor encontrado.'
      : `${tutors.length} tutores encontrados.`;
    updateStatus(countMessage);
    setBusy(false);
  };

  const executeSearch = async (query, { skipMinLength = false } = {}) => {
    state.currentQuery = query;
    if (!skipMinLength && query.length < minChars) {
      state.lastResults = [];
      resultsList.innerHTML = '';
      hideList();
      updateStatus('');
      setBusy(false);
      return;
    }

    const requestId = ++state.requestId;
    renderLoading();

    try {
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        throw new TutorSearchError('offline', offlineMessage);
      }

      const response = await fetchTutors(query);
      if (response && response.aborted) {
        return;
      }

      if (requestId !== state.requestId) {
        return;
      }

      if (!Array.isArray(response) || response.length === 0) {
        renderEmpty();
        return;
      }

      renderResults(response);
    } catch (error) {
      if (requestId !== state.requestId) {
        return;
      }

      if (!(error instanceof TutorSearchError)) {
        error = new TutorSearchError('unknown', error?.message || 'Não foi possível buscar tutores.');
      }

      renderError(error);
    }
  };

  resultsList.setAttribute('role', resultsList.getAttribute('role') || 'listbox');
  resultsList.setAttribute('aria-live', resultsList.getAttribute('aria-live') || 'polite');
  resultsList.setAttribute('aria-atomic', resultsList.getAttribute('aria-atomic') || 'false');
  hideList();

  input.addEventListener('input', () => {
    const value = input.value.trim();
    state.currentQuery = value;
    if (!value) {
      state.lastResults = [];
      resultsList.innerHTML = '';
      hideList();
      updateStatus('');
      setBusy(false);
      return;
    }
    executeSearch(value);
  });

  resultsList.addEventListener('click', (event) => {
    const retryButton = event.target.closest('[data-retry-search]');
    if (retryButton) {
      event.preventDefault();
      if (state.currentQuery) {
        executeSearch(state.currentQuery, { skipMinLength: true });
      }
      return;
    }

    const item = event.target.closest('[data-tutor-index]');
    if (!item) {
      return;
    }

    const index = Number.parseInt(item.dataset.tutorIndex, 10);
    const tutor = state.lastResults[index];
    if (tutor) {
      onTutorSelected(tutor, { query: state.currentQuery, index });
    }
  });

  resultsList.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }

    const item = event.target.closest('[data-tutor-index]');
    if (!item) {
      return;
    }

    event.preventDefault();
    const index = Number.parseInt(item.dataset.tutorIndex, 10);
    const tutor = state.lastResults[index];
    if (tutor) {
      onTutorSelected(tutor, { query: state.currentQuery, index });
    }
  });

  return {
    hideResults: hideList,
    showResults: showList,
    refresh: () => {
      if (state.currentQuery) {
        executeSearch(state.currentQuery, { skipMinLength: true });
      }
    },
  };
}
