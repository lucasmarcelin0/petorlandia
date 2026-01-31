const FINAL_STATUSES = new Set(['AUTHORIZED', 'REJECTED', 'FAILED', 'CANCELED']);
const STATUS_LABELS = {
  QUEUED: 'Emitindo…',
  PROCESSING: 'Emitindo…',
};

function formatStatus(status) {
  if (!status) return status;
  return STATUS_LABELS[status] || status;
}

async function refreshFiscalStatus(card) {
  const documentId = card.dataset.documentId;
  if (!documentId) return;
  try {
    const resp = await fetch(`/fiscal/documents/${documentId}/status`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    if (!resp.ok) return;
    const data = await resp.json();
    const statusEl = card.querySelector('[data-fiscal-status]');
    if (statusEl && data.status) {
      statusEl.textContent = formatStatus(data.status);
      statusEl.dataset.status = data.status;
    }
    const fieldMap = {
      access_key: data.access_key,
      nfse_number: data.nfse_number,
      verification_code: data.verification_code,
      error_message: data.error_message,
    };
    Object.entries(fieldMap).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      const el = card.querySelector(`[data-fiscal-field="${key}"]`);
      if (el) {
        el.textContent = value;
      }
    });
    if (FINAL_STATUSES.has(data.status)) {
      card.dataset.fiscalPoll = 'false';
    }
  } catch (err) {
    // Ignore polling errors
  }
}

function initFiscalPolling() {
  const cards = Array.from(document.querySelectorAll('[data-fiscal-card]'))
    .filter((card) => card.dataset.documentId);
  if (!cards.length) return;

  cards.forEach((card) => {
    const status = card.querySelector('[data-fiscal-status]')?.dataset.status || '';
    if (!FINAL_STATUSES.has(status)) {
      card.dataset.fiscalPoll = 'true';
    }
    const statusEl = card.querySelector('[data-fiscal-status]');
    if (statusEl && status) {
      statusEl.textContent = formatStatus(status);
    }
  });

  const poll = async () => {
    const active = cards.filter((card) => card.dataset.fiscalPoll === 'true');
    if (!active.length) return;
    await Promise.all(active.map((card) => refreshFiscalStatus(card)));
  };

  poll();
  setInterval(poll, 20000);
}

document.addEventListener('DOMContentLoaded', initFiscalPolling);
