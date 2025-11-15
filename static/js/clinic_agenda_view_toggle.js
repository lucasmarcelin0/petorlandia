function safeReadStorage(key) {
  if (typeof window === 'undefined' || !window.localStorage || !key) {
    return null;
  }
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    console.warn('Não foi possível ler o modo de visualização salvo.', error);
    return null;
  }
}

function safeWriteStorage(key, value) {
  if (typeof window === 'undefined' || !window.localStorage || !key) {
    return;
  }
  try {
    if (value === undefined || value === null) {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, value);
    }
  } catch (error) {
    console.warn('Não foi possível salvar o modo de visualização da agenda.', error);
  }
}

function applyButtonState(buttons, activeValue) {
  buttons.forEach((button) => {
    const isActive = button.dataset.viewValue === activeValue;
    button.classList.toggle('active', isActive);
    button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    button.setAttribute('tabindex', isActive ? '0' : '-1');
  });
}

function navigateToView(parameterName, targetValue) {
  if (typeof window === 'undefined' || !parameterName) {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set(parameterName, targetValue);
  window.location.assign(url.toString());
}

function initAgendaViewToggle(toggle) {
  if (!toggle) {
    return;
  }
  const buttons = Array.from(toggle.querySelectorAll('[data-view-value]'));
  if (!buttons.length) {
    return;
  }
  const parameterName = toggle.dataset.parameter || 'view';
  const storageKey = toggle.dataset.storageKey || 'clinicAgendaView';
  const currentView = (toggle.dataset.currentView || 'list').toLowerCase();
  const storedView = (safeReadStorage(storageKey) || '').toLowerCase();
  const url = new URL(window.location.href);
  const hasQueryParam = url.searchParams.has(parameterName);

  if (!hasQueryParam && storedView && storedView !== currentView) {
    url.searchParams.set(parameterName, storedView);
    window.location.replace(url.toString());
    return;
  }

  applyButtonState(buttons, currentView);

  function handleSelection(nextView) {
    if (!nextView || nextView === toggle.dataset.currentView) {
      safeWriteStorage(storageKey, nextView);
      return;
    }
    safeWriteStorage(storageKey, nextView);
    toggle.dataset.currentView = nextView;
    applyButtonState(buttons, nextView);
    navigateToView(parameterName, nextView);
  }

  buttons.forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      const nextView = (button.dataset.viewValue || '').toLowerCase();
      handleSelection(nextView || 'list');
    });
    button.addEventListener('keydown', (event) => {
      if (event.key === ' ' || event.key === 'Enter') {
        event.preventDefault();
        button.click();
      }
    });
  });

  toggle.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
      return;
    }
    event.preventDefault();
    const activeIndex = buttons.findIndex((btn) => btn.classList.contains('active'));
    const delta = event.key === 'ArrowLeft' ? -1 : 1;
    const nextIndex = (activeIndex + delta + buttons.length) % buttons.length;
    const nextButton = buttons[nextIndex];
    if (nextButton) {
      nextButton.focus();
      nextButton.click();
    }
  });
}

function initAllAgendaViewToggles() {
  const toggles = document.querySelectorAll('[data-appointments-view-toggle]');
  toggles.forEach(initAgendaViewToggle);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAllAgendaViewToggles);
} else {
  initAllAgendaViewToggles();
}
