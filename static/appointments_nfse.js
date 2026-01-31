const NFSE_FINAL_STATUSES = new Set(['AUTHORIZED', 'REJECTED', 'FAILED', 'CANCELED']);

async function refreshNfseStatus(el) {
  const documentId = el.dataset.documentId;
  if (!documentId) return;
  try {
    const resp = await fetch(`/fiscal/documents/${documentId}/status`, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.status) {
      el.textContent = data.status;
      el.dataset.status = data.status;
      if (NFSE_FINAL_STATUSES.has(data.status)) {
        el.dataset.nfsePoll = 'false';
      }
    }
  } catch (err) {
    // Ignore polling errors
  }
}

function initNfsePolling() {
  const elements = Array.from(document.querySelectorAll('[data-nfse-status]'));
  if (!elements.length) return;

  elements.forEach((el) => {
    const status = el.dataset.status || '';
    if (!NFSE_FINAL_STATUSES.has(status)) {
      el.dataset.nfsePoll = 'true';
    }
  });

  const poll = async () => {
    const active = elements.filter((el) => el.dataset.nfsePoll === 'true');
    if (!active.length) return;
    await Promise.all(active.map((el) => refreshNfseStatus(el)));
  };

  poll();
  setInterval(poll, 20000);
}

document.addEventListener('DOMContentLoaded', initNfsePolling);
