const HIDDEN_CLASS = 'd-none';

function toggleLoading(element, show) {
  if (!element) {
    return;
  }
  element.classList.toggle(HIDDEN_CLASS, !show);
}

async function fetchSection(url, container, loadingIndicator, errorMessage) {
  if (!url || !container) {
    return;
  }
  toggleLoading(loadingIndicator, true);
  try {
    const response = await fetch(url, {
      headers: {
        Accept: 'application/json',
      },
    });
    if (!response.ok) {
      throw new Error(errorMessage);
    }
    const data = await response.json();
    if (!data.success || !data.html) {
      throw new Error(errorMessage);
    }
    container.innerHTML = data.html;
  } catch (error) {
    container.innerHTML = `<div class="alert alert-danger">${error.message || errorMessage}</div>`;
  } finally {
    toggleLoading(loadingIndicator, false);
  }
}

function initAnimalRecord() {
  const root = document.querySelector('[data-animal-record]');
  if (!root) {
    return;
  }

  const eventsUrl = root.dataset.eventsUrl;
  const historyUrl = root.dataset.historyUrl;
  const eventsContainer = root.querySelector('[data-events-container]');
  const historyContainer = root.querySelector('[data-history-container]');
  const eventsLoading = root.querySelector('[data-events-loading]');
  const historyLoading = root.querySelector('[data-history-loading]');
  let historyLoaded = false;

  if (eventsUrl) {
    fetchSection(
      eventsUrl,
      eventsContainer,
      eventsLoading,
      'Não foi possível carregar os próximos eventos.',
    );
  }

  const historyTab = document.getElementById('historico-tab');
  if (historyTab && historyUrl) {
    historyTab.addEventListener('shown.bs.tab', () => {
      if (historyLoaded) {
        return;
      }
      historyLoaded = true;
      fetchSection(
        historyUrl,
        historyContainer,
        historyLoading,
        'Não foi possível carregar o histórico médico.',
      );
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAnimalRecord);
} else {
  initAnimalRecord();
}
