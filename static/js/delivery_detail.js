const HIDDEN_CLASS = 'd-none';
const DEFAULT_ERROR_MESSAGE = 'Não foi possível cancelar o pedido.';

function updateStatusBadge(element, label, badgeClass) {
  if (!element) {
    return;
  }
  element.className = `badge ${badgeClass || 'bg-secondary'}`.trim();
  element.textContent = label || 'Atualizando...';
}

function buildTimelineItem(item) {
  const iconMap = {
    requested_at: '🕐',
    accepted_at: '🚚',
    completed_at: '✅',
    canceled_at: '❌',
  };
  const li = document.createElement('li');
  li.className = 'list-group-item';
  if (item.is_cancel) {
    li.classList.add('text-danger');
  }
  const icon = iconMap[item.key] || '📌';
  const timestamp = item.timestamp || 'Sem data';
  li.textContent = `${icon} ${item.label}: ${timestamp}`;
  return li;
}

function updateTimeline(container, timeline) {
  if (!container) {
    return;
  }
  container.innerHTML = '';
  if (!timeline || timeline.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'list-group-item text-muted';
    empty.textContent = 'Nenhum evento disponível.';
    container.appendChild(empty);
    return;
  }
  timeline.forEach((item) => {
    container.appendChild(buildTimelineItem(item));
  });
}

function ensureEmptyWorkerParagraph(section) {
  let emptyEl = section.querySelector('[data-worker-empty]');
  if (!emptyEl) {
    emptyEl = document.createElement('p');
    emptyEl.className = 'mb-0 text-muted';
    emptyEl.dataset.workerEmpty = '';
    section.appendChild(emptyEl);
  }
  return emptyEl;
}

function updateWorker(section, worker) {
  if (!section) {
    return;
  }
  const nameEl = section.querySelector('[data-worker-name]');
  const emailEl = section.querySelector('[data-worker-email]');
  let emptyEl = section.querySelector('[data-worker-empty]');

  if (worker) {
    if (nameEl) {
      nameEl.classList.remove(HIDDEN_CLASS);
      nameEl.textContent = `${worker.name} (ID ${worker.id})`;
    }
    if (emailEl) {
      emailEl.classList.remove(HIDDEN_CLASS);
      emailEl.textContent = worker.email ? `📧 ${worker.email}` : '';
    }
    if (emptyEl) {
      emptyEl.classList.add(HIDDEN_CLASS);
    }
  } else {
    if (nameEl) {
      nameEl.classList.add(HIDDEN_CLASS);
    }
    if (emailEl) {
      emailEl.classList.add(HIDDEN_CLASS);
      emailEl.textContent = '';
    }
    emptyEl = ensureEmptyWorkerParagraph(section);
    emptyEl.textContent = 'Nenhum entregador atribuído.';
    emptyEl.classList.remove(HIDDEN_CLASS);
  }
}

function ensureStatusContainer(form) {
  let status = form.querySelector('.form-status-message');
  if (!status) {
    status = document.createElement('div');
    status.className = 'form-status-message alert small mt-2';
    form.appendChild(status);
  }
  return status;
}

function showFormStatus(form, message, variant = 'info') {
  if (!form) return;
  if (window.FormFeedback && typeof window.FormFeedback.showStatus === 'function') {
    window.FormFeedback.showStatus(form, message, variant);
    return;
  }
  const status = ensureStatusContainer(form);
  status.textContent = message || '';
  status.classList.remove('d-none');
  ['success', 'danger', 'warning', 'info'].forEach((v) => {
    status.classList.remove(`alert-${v}`);
  });
  status.classList.add(`alert-${variant}`);
}

async function submitCancelForm(cancelForm) {
  const response = await fetch(cancelForm.action, {
    method: 'POST',
    body: new FormData(cancelForm),
    headers: {
      'X-Requested-With': 'XMLHttpRequest',
      Accept: 'application/json',
    },
  });

  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const data = isJson ? await response.json() : null;

  if (!response.ok || (data && data.success === false)) {
    const message = (data && (data.message || data.error)) || DEFAULT_ERROR_MESSAGE;
    const error = new Error(message);
    error.response = response;
    error.data = data;
    throw error;
  }

  return data;
}

function initCancelHandler(root, refreshCallback) {
  const cancelForm = root.querySelector('[data-cancel-form]');
  if (!cancelForm) {
    return;
  }

  cancelForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const run = () => submitCancelForm(cancelForm);

    const onSuccess = (data) => {
      const message = (data && data.message) || 'Pedido cancelado.';
      showFormStatus(cancelForm, message, 'info');
      refreshCallback();
    };

    const onError = (error) => {
      showFormStatus(cancelForm, error?.message || DEFAULT_ERROR_MESSAGE, 'danger');
      console.error('Erro ao cancelar pedido:', error);
    };

    if (window.FormFeedback && typeof window.FormFeedback.withSavingState === 'function') {
      window.FormFeedback
        .withSavingState(cancelForm, run, {
          loadingText: 'Cancelando...',
          successText: 'Cancelado',
          errorMessage: DEFAULT_ERROR_MESSAGE,
        })
        .then(onSuccess)
        .catch(onError);
    } else {
      const button = cancelForm.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
      }
      run()
        .then((data) => {
          if (button) {
            button.disabled = false;
          }
          onSuccess(data);
        })
        .catch((error) => {
          if (button) {
            button.disabled = false;
          }
          onError(error);
        });
    }
  });
}

function initDeliveryDetail() {
  const root = document.querySelector('[data-delivery-detail]');
  if (!root) {
    return;
  }
  const statusUrl = root.dataset.statusUrl;
  const pollInterval = parseInt(root.dataset.pollInterval || '0', 10);
  const badge = root.querySelector('[data-status-badge]');
  const timelineContainer = root.querySelector('[data-timeline]');
  const workerSection = root.querySelector('[data-worker-section]');

  async function refresh() {
    if (!statusUrl) {
      return;
    }
    try {
      const response = await fetch(statusUrl, {
        headers: {
          Accept: 'application/json',
        },
      });
      if (!response.ok) {
        throw new Error();
      }
      const data = await response.json();
      if (!data.success) {
        throw new Error();
      }
      updateStatusBadge(badge, data.status_label, data.badge_class);
      updateTimeline(timelineContainer, data.timeline);
      updateWorker(workerSection, data.worker);
    } catch (error) {
      updateStatusBadge(badge, 'Erro ao atualizar', 'bg-danger');
    }
  }

  refresh();
  initCancelHandler(root, refresh);
  if (pollInterval > 0) {
    window.setInterval(refresh, pollInterval);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDeliveryDetail);
} else {
  initDeliveryDetail();
}
