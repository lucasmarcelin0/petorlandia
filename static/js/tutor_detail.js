// Filter animals list by name without page reload

document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('animal-search');
  const table = document.getElementById('animals-table');
  if (!searchInput || !table) return;

  searchInput.addEventListener('input', () => {
    const term = searchInput.value.toLowerCase();
    const rows = table.querySelectorAll('tbody tr[id^="animal-row-"]');
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

  const csrfInput = document.createElement('input');
  csrfInput.type = 'hidden';
  csrfInput.name = 'csrf_token';
  csrfInput.value = document.querySelector('meta[name="csrf-token"]')?.content || '';
  deleteForm.appendChild(csrfInput);

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

function createAnimalRow(animal) {
  if (!animal || !animal.id) return null;

  const tr = document.createElement('tr');
  tr.id = `animal-row-${animal.id}`;

  const tdName = document.createElement('td');
  const nameWrapper = document.createElement('div');
  nameWrapper.className = 'd-flex align-items-center gap-2';

  if (animal.image) {
    const img = document.createElement('img');
    img.src = animal.image;
    img.alt = `Foto de ${animal.name}`;
    img.className = 'avatar';
    img.style.setProperty('--avatar-size', '36px');
    if (typeof animal.photo_offset_x !== 'undefined') img.dataset.offsetX = animal.photo_offset_x;
    if (typeof animal.photo_offset_y !== 'undefined') img.dataset.offsetY = animal.photo_offset_y;
    if (typeof animal.photo_rotation !== 'undefined') img.dataset.rotation = animal.photo_rotation;
    if (typeof animal.photo_zoom !== 'undefined') img.dataset.zoom = animal.photo_zoom;
    if (typeof updateAvatarTransform === 'function') {
      const offsetX = parseFloat(img.dataset.offsetX) || 0;
      const offsetY = parseFloat(img.dataset.offsetY) || 0;
      const rotation = parseFloat(img.dataset.rotation) || 0;
      const zoom = parseFloat(img.dataset.zoom) || 1;
      updateAvatarTransform(img, offsetX, offsetY, rotation, zoom);
    }
    nameWrapper.appendChild(img);
  } else {
    const placeholder = document.createElement('div');
    placeholder.className = 'avatar placeholder';
    placeholder.style.setProperty('--avatar-size', '36px');
    placeholder.innerHTML = '<i class="fas fa-paw"></i>';
    nameWrapper.appendChild(placeholder);
  }

  const nameSpan = document.createElement('span');
  nameSpan.className = 'animal-name fw-semibold';
  nameSpan.textContent = animal.name || '';
  nameWrapper.appendChild(nameSpan);

  tdName.appendChild(nameWrapper);

  const tdSpecies = document.createElement('td');
  tdSpecies.className = 'animal-species';
  const speciesBadge = document.createElement('span');
  speciesBadge.className = 'badge bg-light text-dark border me-2';
  speciesBadge.textContent = animal.species || '—';
  const breedText = document.createElement('span');
  breedText.className = 'text-muted';
  breedText.textContent = animal.breed || '—';
  tdSpecies.appendChild(speciesBadge);
  tdSpecies.appendChild(breedText);

  const tdSex = document.createElement('td');
  tdSex.className = 'animal-sex';
  const sexBadge = document.createElement('span');
  const sex = animal.sex || '—';
  sexBadge.textContent = sex;
  sexBadge.classList.add('badge');
  if (sex === 'Fêmea') {
    sexBadge.classList.add('bg-pink');
  } else if (sex === 'Macho') {
    sexBadge.classList.add('bg-info-subtle', 'text-info');
  } else {
    sexBadge.classList.add('bg-light', 'text-dark', 'border');
  }
  tdSex.appendChild(sexBadge);

  const tdActions = document.createElement('td');
  tdActions.className = 'text-end';
  const actionsWrapper = document.createElement('div');
  actionsWrapper.className = 'd-flex gap-2 justify-content-end flex-wrap';

  if (animal.links?.consulta) {
    const consultaLink = document.createElement('a');
    consultaLink.href = animal.links.consulta;
    consultaLink.className = 'btn btn-outline-success btn-sm';
    consultaLink.innerHTML = '<i class="fas fa-stethoscope me-1"></i> Consulta';
    actionsWrapper.appendChild(consultaLink);
  }

  if (animal.links?.ficha) {
    const fichaLink = document.createElement('a');
    fichaLink.href = animal.links.ficha;
    fichaLink.className = 'btn btn-outline-info btn-sm';
    fichaLink.innerHTML = '<i class="fas fa-file-lines me-1"></i> Ficha';
    actionsWrapper.appendChild(fichaLink);
  }

  if (animal.links?.delete) {
    const deleteForm = document.createElement('form');
    deleteForm.action = animal.links.delete;
    deleteForm.method = 'POST';
    deleteForm.className = 'js-animal-delete-form d-inline';
    deleteForm.dataset.sync = '';
    deleteForm.dataset.confirm = 'Tem certeza que deseja remover este animal?';
    deleteForm.dataset.animalId = animal.id;
    deleteForm.dataset.animalName = animal.name || '';
    deleteForm.dataset.animalSpecies = animal.species || '';
    deleteForm.dataset.animalBreed = animal.breed || '';

    const csrfInput = document.createElement('input');
    csrfInput.type = 'hidden';
    csrfInput.name = 'csrf_token';
    csrfInput.value = document.querySelector('meta[name="csrf-token"]')?.content || '';
    deleteForm.appendChild(csrfInput);

    const deleteButton = document.createElement('button');
    deleteButton.type = 'submit';
    deleteButton.className = 'btn btn-outline-danger btn-sm';
    deleteButton.innerHTML = '<i class="fas fa-trash"></i>';
    deleteForm.appendChild(deleteButton);

    actionsWrapper.appendChild(deleteForm);
  }

  tdActions.appendChild(actionsWrapper);

  tr.appendChild(tdName);
  tr.appendChild(tdSpecies);
  tr.appendChild(tdSex);
  tr.appendChild(tdActions);

  return tr;
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

document.addEventListener('form-sync-success', (ev) => {
  const detail = ev.detail || {};
  const form = detail.form;
  const data = detail.data || {};
  const success = detail.success;
  if (!form || form.id !== 'new-animal-form') return;
  if (!success) return;

  ev.preventDefault();

  const animal = data.animal;
  const tableBody = document.querySelector('#animals-table tbody');
  const newRow = createAnimalRow(animal);
  if (newRow && tableBody) {
    tableBody.appendChild(newRow);
    updateAnimalsEmptyState(tableBody);
    const searchInput = document.getElementById('animal-search');
    if (searchInput && searchInput.value.trim()) {
      searchInput.dispatchEvent(new Event('input'));
    }
  }

  const modal = bootstrap.Modal.getInstance(form.closest('.modal'));
  modal?.hide();
  form.reset();

  if (typeof showToast === 'function') {
    const message = (data && data.message) || 'Animal cadastrado com sucesso!';
    showToast(message, 'success');
  }
});
