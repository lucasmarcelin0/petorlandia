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

function buildStatusBadge(label, variant, iconClass, tooltip){
  const badge = document.createElement('span');
  badge.className = `badge text-bg-${variant} ms-2 d-inline-flex align-items-center gap-1`;
  if(tooltip){
    badge.title = tooltip;
  }
  if(iconClass){
    const icon = document.createElement('i');
    icon.className = iconClass;
    badge.appendChild(icon);
  }
  badge.appendChild(document.createTextNode(label));
  return badge;
}

function showLocalToast(message, category = 'info'){
  const toastEl = document.getElementById('actionToast');
  if(!toastEl || !message) return;
  toastEl.querySelector('.toast-body').textContent = message;
  const classes = ['bg-danger','bg-info','bg-success','bg-warning','bg-primary','bg-secondary','bg-dark'];
  toastEl.classList.remove(...classes);
  toastEl.classList.add(`bg-${category}`);
  bootstrap.Toast.getOrCreateInstance(toastEl).show();
}

function addRemovedAnimalToList(form, options = {}) {
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
  if(options.badge){
    li.appendChild(options.badge);
  }
  li.appendChild(deleteForm);
  removedList.appendChild(li);
  removedWrapper.classList.remove('d-none');
}

document.addEventListener('form-sync-success', (ev) => {
  const detail = ev.detail || {};
  const form = detail.form;
  const data = detail.data || {};
  const response = detail.response;
  const offlineQueued = Boolean(detail.offlineQueued);

  if (!form || !form.classList.contains('js-animal-delete-form')) return;
  if (ev.defaultPrevented || detail.handledRemoval) return;

  const removalSucceeded = offlineQueued || (response && response.ok && !(data && data.success === false));
  if (!removalSucceeded) return;

  ev.preventDefault();
  detail.handledRemoval = true;

  const animalId = form.dataset.animalId;
  const rowId = animalId ? `animal-row-${animalId}` : null;
  const message = data.message || (offlineQueued ? 'Remoção aguardando sincronização.' : 'Animal removido com sucesso.');
  const badge = buildStatusBadge(
    offlineQueued ? 'Aguardando sincronização' : 'Excluído',
    offlineQueued ? 'warning' : 'success',
    offlineQueued ? 'fa-solid fa-cloud-arrow-up' : 'fa-solid fa-circle-check',
    offlineQueued ? 'O dispositivo está offline. Este item será excluído ao sincronizar.' : 'A exclusão foi processada com sucesso.'
  );

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
    addRemovedAnimalToList(form, { badge });
  }

  const toastCategory = offlineQueued ? 'warning' : (data.category || 'success');
  showLocalToast(message, toastCategory);
});
