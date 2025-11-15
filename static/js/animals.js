const filterForm = document.getElementById('filterForm');
const animalsContainer = document.getElementById('animals-container');
const basePath = filterForm ? new URL(filterForm.action, window.location.origin).pathname : window.location.pathname;

function buildParams(overrides = {}) {
  if (!filterForm) {
    const params = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(overrides)) {
      if (value === undefined) continue;
      if (value === null || value === '') {
        params.delete(key);
      } else {
        params.set(key, value);
      }
    }
    return params;
  }

  const params = new URLSearchParams();
  const formData = new FormData(filterForm);
  for (const [name, value] of formData.entries()) {
    if (value !== null && value !== '') {
      params.set(name, value);
    }
  }

  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined) continue;
    if (value === null || value === '') {
      params.delete(key);
    } else {
      params.set(key, value);
    }
  }

  return params;
}

function syncFormWithParams(params) {
  if (!filterForm) return;

  const assign = (name, fallback = '') => {
    const element = filterForm.elements.namedItem(name);
    if (!element) return;
    const value = params.get(name);
    if (value !== null) {
      element.value = value;
    } else {
      element.value = fallback;
    }
  };

  assign('modo', 'todos');
  assign('species_id');
  assign('breed_id');
  assign('sex');
  assign('age');
  assign('name');
}

async function loadAnimals(params, { pushState = true } = {}) {
  if (!animalsContainer) return;

  const search = params.toString();
  const requestUrl = search ? `${basePath}?${search}` : basePath;

  animalsContainer.setAttribute('aria-busy', 'true');

  try {
    const response = await fetch(requestUrl, {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      }
    });

    if (!response.ok) {
      throw new Error(`Falha ao carregar animais: ${response.status}`);
    }

    const data = await response.json();
    if (!data || typeof data.html !== 'string') {
      throw new Error('Resposta inválida do servidor.');
    }

    animalsContainer.innerHTML = data.html;
    initializePopovers();
  } catch (error) {
    console.error(error);
    window.location.href = requestUrl;
    return;
  } finally {
    animalsContainer.removeAttribute('aria-busy');
  }

  if (pushState) {
    const newUrl = search ? `${basePath}?${search}` : basePath;
    history.pushState({ animalsSearch: search }, '', newUrl);
  }
}

function initializePopovers() {
  if (!window.bootstrap || !window.bootstrap.Popover) return;
  document.querySelectorAll('[data-bs-toggle="popover"]').forEach((el) => {
    if (!window.bootstrap.Popover.getInstance(el)) {
      new window.bootstrap.Popover(el);
    }
  });
}

function handleFormChange(event) {
  if (!filterForm || event.target.form !== filterForm) return;
  const params = buildParams({ page: null });
  loadAnimals(params);
}

function handleFormSubmit(event) {
  if (!filterForm || event.target !== filterForm) return;
  event.preventDefault();
  const params = buildParams({ page: null });
  loadAnimals(params);
}

function handlePaginationClick(event) {
  if (!animalsContainer) return;
  const link = event.target.closest('.pagination a.page-link');
  if (!link || !animalsContainer.contains(link)) return;

  const parentItem = link.closest('.page-item');
  if (parentItem && parentItem.classList.contains('disabled')) {
    event.preventDefault();
    return;
  }

  event.preventDefault();
  const page = link.dataset.page;
  const params = buildParams({ page });
  loadAnimals(params);
}

async function handleDeleteSubmit(event) {
  const form = event.target.closest('.delete-animal-form');
  if (!form) return;

  event.preventDefault();
  if (!confirm('Excluir permanentemente este animal?')) return;

  try {
    const response = await fetch(form.action, {
      method: 'POST',
      headers: {
        Accept: 'application/json'
      }
    });

    if (response.ok) {
      const card = document.getElementById(`animal-card-${form.dataset.animalId}`);
      if (card) {
        card.remove();
      }
    } else {
      const data = await response.json().catch(() => ({}));
      alert(data.message || 'Erro ao excluir animal.');
    }
  } catch (error) {
    console.error('Erro ao excluir animal', error);
    alert('Erro ao excluir animal.');
  }
}

function registerEventListeners() {
  if (filterForm) {
    filterForm.addEventListener('submit', handleFormSubmit);
    filterForm.addEventListener('change', handleFormChange);
  }

  if (animalsContainer) {
    animalsContainer.addEventListener('click', handlePaginationClick);
    animalsContainer.addEventListener('submit', handleDeleteSubmit);
  }

  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(window.location.search);
    syncFormWithParams(params);
    loadAnimals(params, { pushState: false });
  });
}

function init() {
  if (!animalsContainer) return;
  registerEventListeners();
  initializePopovers();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
