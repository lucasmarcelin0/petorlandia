const HIDDEN_CLASS = 'd-none';

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
  if (pollInterval > 0) {
    window.setInterval(refresh, pollInterval);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDeliveryDetail);
} else {
  initDeliveryDetail();
}
