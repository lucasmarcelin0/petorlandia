(function () {
  const table = document.querySelector('[data-plantao-table]');
  if (!table) {
    return;
  }

  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const filterSelect = document.querySelector('[data-plantao-filter]');
  const sortSelect = document.querySelector('[data-plantao-sort]');
  const searchInput = document.querySelector('[data-plantao-search]');

  function highlightLateRows() {
    rows.forEach((row) => {
      if (row.dataset.atrasado === '1') {
        row.classList.add('table-warning');
      } else {
        row.classList.remove('table-warning');
      }
    });
  }

  function applyFilter() {
    const veterinarioId = filterSelect ? filterSelect.value : '';
    const term = searchInput ? searchInput.value.toLowerCase().trim() : '';
    rows.forEach((row) => {
      const matchesVeterinario = !veterinarioId || row.dataset.veterinario === veterinarioId;
      const matchesTerm = !term || row.textContent.toLowerCase().includes(term);
      row.style.display = matchesVeterinario && matchesTerm ? '' : 'none';
    });
  }

  function compareRows(a, b, key, direction) {
    const multiplier = direction === 'desc' ? -1 : 1;
    if (key === 'turno') {
      return a.dataset.turno.localeCompare(b.dataset.turno) * multiplier;
    }
    const dateA = new Date(a.dataset.inicio);
    const dateB = new Date(b.dataset.inicio);
    return (dateA - dateB) * multiplier;
  }

  function applySort() {
    if (!sortSelect) {
      return;
    }
    const value = sortSelect.value || 'inicio:asc';
    const [key, direction] = value.split(':');
    const sorted = rows.slice().sort((a, b) => compareRows(a, b, key, direction));
    const tbody = table.querySelector('tbody');
    sorted.forEach((row) => tbody.appendChild(row));
  }

  filterSelect && filterSelect.addEventListener('change', applyFilter);
  searchInput && searchInput.addEventListener('input', applyFilter);
  sortSelect && sortSelect.addEventListener('change', () => {
    applySort();
    highlightLateRows();
  });

  applySort();
  applyFilter();
  highlightLateRows();
})();
