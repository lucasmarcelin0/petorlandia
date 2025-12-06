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

function buildRemovalBadge(syncStatus) {
  const badge = document.createElement('span');
  badge.className = 'badge ms-2';
  if (syncStatus === 'queued') {
    badge.classList.add('bg-warning', 'text-dark');
    badge.innerHTML = '<i class="fas fa-cloud-slash me-1"></i>Aguardando sincronização';
    badge.title = 'Este item será removido quando a conexão voltar.';
  } else {
    badge.classList.add('bg-success');
    badge.innerHTML = '<i class="fas fa-check me-1"></i>Excluído';
    badge.title = 'Remoção concluída';
  }
  if (window.bootstrap && bootstrap.Tooltip) {
    bootstrap.Tooltip.getOrCreateInstance(badge);
  }
  return badge;
}

function addRemovedAnimalToList(form, syncStatus = 'completed') {
  const removedWrapper = document.getElementById('removidos-wrapper');
  const removedList = removedWrapper ? removedWrapper.querySelector('.list-group') : null;
  if (!removedList || !removedWrapper) return;

  const li = document.createElement('li');
  li.className = 'list-group-item d-flex justify-content-between align-items-center';

  const infoSpan = document.createElement('span');
  const nameStrong = document.createElement('strong');
  const animalName = form.dataset.animalName || '';
  const animalSpecies = form.dataset.animalSpecies || '';
  const animalBreed = form.dataset.animalBreed || '';
  nameStrong.textContent = animalName;
  infoSpan.appendChild(nameStrong);
  infoSpan.appendChild(document.createTextNode(` — ${animalSpecies} / ${animalBreed}`));
  infoSpan.appendChild(buildRemovalBadge(syncStatus));

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
  removedList.appendChild(li);
  removedWrapper.classList.remove('d-none');
}

document.addEventListener('form-sync-success', (ev) => {
  const detail = ev.detail || {};
  const form = detail.form;
  const data = detail.data || {};
  const response = detail.response;

  if (!form || !form.classList.contains('js-animal-delete-form')) return;
  if (ev.defaultPrevented || form.dataset.removalHandled === 'true') return;

  const syncStatus = detail.syncStatus || (!response ? 'queued' : (response.ok && data.success !== false ? 'completed' : 'error'));
  const isQueued = syncStatus === 'queued';
  const isSuccess = syncStatus === 'completed' || isQueued;
  if (!isSuccess) return;

  ev.preventDefault();
  form.dataset.removalHandled = 'true';

  const animalId = form.dataset.animalId;
  const rowId = animalId ? `animal-row-${animalId}` : null;
  if (form.dataset.removedItem === 'true') {
    const listItem = form.closest('li');
    if (listItem) listItem.remove();
  } else {
    if (rowId) {
      const row = document.getElementById(rowId);
      if (row) row.remove();
    }

    const tableBody = document.querySelector('#animals-table tbody');
    updateAnimalsEmptyState(tableBody);
    addRemovedAnimalToList(form, syncStatus === 'queued' ? 'queued' : 'completed');
  }

  const message = data && data.message ? data.message : (isQueued ? 'Remoção aguardando sincronização.' : 'Animal removido com sucesso.');
  if (typeof showToast === 'function') {
    showToast(message, isQueued ? 'warning' : 'success');
  }
});
