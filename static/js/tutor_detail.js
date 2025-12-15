// Filter animals list by name without page reload

document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('animal-search');
  const table = document.getElementById('animals-table');
  if (!searchInput || !table) return;

  const rows = table.querySelectorAll('tbody tr');

  searchInput.addEventListener('input', () => {
    const term = searchInput.value.toLowerCase();
    rows.forEach(row => {
      const nameCell = row.querySelector('.animal-name');
      const name = nameCell ? nameCell.textContent.toLowerCase() : '';
      row.style.display = name.includes(term) ? '' : 'none';
    });
  });
});

function updateAnimalsEmptyState(tableBody) {
  if (!tableBody) return;
  const hasAnimalRows = tableBody.querySelector('tr[id^="animal-row-"]');
  let emptyStateRow = tableBody.querySelector('tr[data-empty-state]');
  if (hasAnimalRows) {
    if (emptyStateRow) emptyStateRow.remove();
    return;
  }
  if (!emptyStateRow) {
    emptyStateRow = document.createElement('tr');
    emptyStateRow.dataset.emptyState = 'true';
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.className = 'text-muted text-center';
    cell.textContent = 'Nenhum animal cadastrado.';
    emptyStateRow.appendChild(cell);
    tableBody.appendChild(emptyStateRow);
  }
}

function buildRemovedStatusBadge(options = {}) {
  const badge = document.createElement('span');
  badge.dataset.removedStatus = 'true';
  badge.classList.add('badge', 'ms-2', 'align-middle');
  const queued = Boolean(options.queued);
  if (queued) {
    badge.classList.add('bg-warning', 'text-dark');
    badge.innerHTML = '<i class="fas fa-cloud-slash me-1"></i>Aguardando sincronização';
    badge.title = 'Remoção pendente de sincronização.';
  } else {
    badge.classList.add('bg-danger-subtle', 'text-danger');
    badge.innerHTML = '<i class="fas fa-trash-alt me-1"></i>Excluído';
    badge.title = 'Remoção concluída.';
  }
  return badge;
}

function addRemovedAnimalToList(form, detail = {}) {
  const removedWrapper = document.getElementById('removidos-wrapper');
  const removedList = removedWrapper ? removedWrapper.querySelector('.list-group') : null;
  if (!removedList || !removedWrapper) return;

  const animalId = form.dataset.animalId || '';
  const existing = animalId ? removedList.querySelector(`li[data-animal-id="${animalId}"]`) : null;
  const li = existing || document.createElement('li');
  li.className = 'list-group-item d-flex justify-content-between align-items-center';
  if (animalId) li.dataset.animalId = animalId;
  if (existing) li.innerHTML = '';

  const infoSpan = document.createElement('span');
  const nameStrong = document.createElement('strong');
  const animalName = form.dataset.animalName || '';
  const animalSpecies = form.dataset.animalSpecies || '';
  const animalBreed = form.dataset.animalBreed || '';
  nameStrong.textContent = animalName;
  infoSpan.appendChild(nameStrong);
  infoSpan.appendChild(document.createTextNode(` — ${animalSpecies} / ${animalBreed}`));
  infoSpan.appendChild(buildRemovedStatusBadge({ queued: detail.offlineQueued }));

  const deleteForm = document.createElement('form');
  deleteForm.action = form.getAttribute('action');
  deleteForm.method = 'POST';
  deleteForm.className = 'js-animal-delete-form d-inline';
  deleteForm.dataset.sync = '';
  deleteForm.dataset.confirm = `Excluir permanentemente ${animalName}?`;
  deleteForm.dataset.animalId = form.dataset.animalId || '';
  deleteForm.dataset.animalName = animalName;
  deleteForm.dataset.animalSpecies = animalSpecies;
  deleteForm.dataset.animalBreed = animalBreed;
  deleteForm.dataset.removedItem = 'true';

  const deleteButton = document.createElement('button');
  deleteButton.type = 'submit';
  deleteButton.className = 'btn btn-sm btn-danger';
  deleteButton.textContent = '❌ Excluir Definitivamente';
  deleteForm.appendChild(deleteButton);

  li.appendChild(infoSpan);
  li.appendChild(deleteForm);
  if (!existing) {
    removedList.appendChild(li);
  }
  removedWrapper.classList.remove('d-none');
}

document.addEventListener('form-sync-success', (ev) => {
  const detail = ev.detail || {};
  const form = detail.form;
  const data = detail.data || {};
  const response = detail.response;

  if (!form || !form.classList.contains('js-animal-delete-form')) return;
  if (ev.defaultPrevented) return;
  if ((!response || !response.ok || (data && data.success === false)) && !detail.offlineQueued) return;

  ev.preventDefault();

  const animalId = form.dataset.animalId;
  const rowId = animalId ? `animal-row-${animalId}` : null;
  const isRemovedItem = form.dataset.removedItem === 'true';
  if (isRemovedItem) {
    const listItem = form.closest('li');
    if (listItem) listItem.remove();
  } else {
    if (rowId) {
      const row = document.getElementById(rowId);
      if (row) row.remove();
    }

    const tableBody = document.querySelector('#animals-table tbody');
    updateAnimalsEmptyState(tableBody);
    addRemovedAnimalToList(form, detail);
    if (!detail.offlineQueued && typeof showToast === 'function') {
      const toastMessage = (data && data.message) || 'Animal removido.';
      showToast(toastMessage, 'success');
    }
  }
});
