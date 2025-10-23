const HIDDEN_CLASS = 'd-none';

function parseHTML(html) {
  if (!html) {
    return [];
  }
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  return Array.from(template.content.children);
}

function createFeedbackManager(element) {
  if (!element) {
    return { show() {}, hide() {} };
  }
  const baseClasses = Array.from(element.classList).filter(
    (cls) => !cls.startsWith('alert-') && cls !== HIDDEN_CLASS && cls !== 'alert',
  );
  let hideTimeout;
  return {
    show(type, message, timeout = 4000) {
      element.className = `${baseClasses.join(' ')} alert alert-${type}`.trim();
      element.textContent = message;
      element.classList.remove(HIDDEN_CLASS);
      if (hideTimeout) {
        clearTimeout(hideTimeout);
      }
      if (timeout > 0) {
        hideTimeout = window.setTimeout(() => {
          this.hide();
        }, timeout);
      }
    },
    hide() {
      if (hideTimeout) {
        clearTimeout(hideTimeout);
        hideTimeout = undefined;
      }
      element.className = `${baseClasses.join(' ')} alert ${HIDDEN_CLASS}`.trim();
    },
  };
}

function updateEmptyState(listElement, emptyMessage) {
  if (!emptyMessage) {
    return;
  }
  const hasItems = listElement && listElement.children.length > 0;
  emptyMessage.classList.toggle(HIDDEN_CLASS, hasItems);
}

function disableWhileProcessing(button, action) {
  if (!button) {
    return action();
  }
  if (button.dataset.loading === 'true') {
    return Promise.resolve();
  }
  button.dataset.loading = 'true';
  button.disabled = true;
  return Promise.resolve()
    .then(action)
    .finally(() => {
      button.dataset.loading = 'false';
      button.disabled = false;
    });
}

function initAppointmentsAdmin() {
  const root = document.getElementById('appointments-admin');
  if (!root) {
    return;
  }
  const list = root.querySelector('[data-list]');
  const emptyMessage = root.querySelector('[data-empty-state]');
  const feedbackElement = root.querySelector('[data-feedback]');
  const loadMoreButton = root.querySelector('[data-load-more]');
  const fetchUrl = root.dataset.fetchUrl;
  const perPage = parseInt(root.dataset.perPage || '20', 10);
  let nextPage = root.dataset.nextPage ? parseInt(root.dataset.nextPage, 10) : null;
  let isLoading = false;
  const feedback = createFeedbackManager(feedbackElement);

  function setLoading(state) {
    isLoading = state;
    if (loadMoreButton) {
      loadMoreButton.disabled = state || !nextPage;
    }
  }

  function updateLoadMoreVisibility() {
    if (!loadMoreButton) {
      return;
    }
    if (nextPage) {
      loadMoreButton.classList.remove(HIDDEN_CLASS);
    } else {
      loadMoreButton.classList.add(HIDDEN_CLASS);
    }
  }

  async function fetchPage(page) {
    if (!fetchUrl || isLoading) {
      return;
    }
    setLoading(true);
    try {
      const url = new URL(fetchUrl, window.location.origin);
      url.searchParams.set('page', page);
      url.searchParams.set('per_page', perPage);
      const response = await fetch(url.toString(), {
        headers: {
          Accept: 'application/json',
        },
      });
      if (!response.ok) {
        throw new Error('Erro ao carregar agendamentos.');
      }
      const data = await response.json();
      if (data.html) {
        const newItems = parseHTML(data.html);
        newItems.forEach((item) => list.appendChild(item));
      }
      nextPage = data.next_page || null;
      root.dataset.nextPage = nextPage ? String(nextPage) : '';
      updateLoadMoreVisibility();
      updateEmptyState(list, emptyMessage);
    } catch (error) {
      feedback.show('danger', error.message || 'Falha ao carregar agendamentos.', 5000);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(form) {
    const confirmMessage = form.dataset.message;
    if (confirmMessage && !window.confirm(confirmMessage)) {
      return;
    }
    const listItem = form.closest('[data-appointment-id]');
    const submitButton = form.querySelector('button[type="submit"]');
    await disableWhileProcessing(submitButton, async () => {
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
          },
          body: new FormData(form),
        });
        if (!response.ok) {
          throw new Error('Não foi possível remover o agendamento.');
        }
        const data = await response.json();
        if (!data.success) {
          throw new Error(data.message || 'Não foi possível remover o agendamento.');
        }
        if (listItem) {
          listItem.remove();
        }
        updateEmptyState(list, emptyMessage);
        feedback.show('success', data.message || 'Agendamento removido.', 3000);
      } catch (error) {
        feedback.show('danger', error.message || 'Não foi possível remover o agendamento.', 5000);
      }
    });
  }

  updateEmptyState(list, emptyMessage);
  updateLoadMoreVisibility();

  if (loadMoreButton) {
    loadMoreButton.addEventListener('click', () => {
      if (nextPage) {
        fetchPage(nextPage);
      }
    });
  }

  root.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    if (!form.classList.contains('js-appointment-delete')) {
      return;
    }
    event.preventDefault();
    handleDelete(form);
  });
}

document.addEventListener('DOMContentLoaded', initAppointmentsAdmin);
