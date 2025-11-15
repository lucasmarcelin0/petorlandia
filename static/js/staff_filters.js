function resolveElement(target) {
  if (!target) return null;
  if (typeof target === 'string') {
    return document.querySelector(target);
  }
  return target;
}

function initSingleFilter(config = {}) {
  const filterInput = resolveElement(config.filterSelector || config.filterInput);
  const sortSelect = resolveElement(config.sortSelector || config.sortSelect);
  const roleSelect = resolveElement(config.roleSelector || config.roleSelect);
  const list = resolveElement(config.listSelector || config.list);
  const itemSelector = config.itemSelector || '[data-name]';

  if (!filterInput || !sortSelect || !list) {
    return;
  }

  const items = Array.from(list.querySelectorAll(itemSelector));
  if (!items.length) {
    return;
  }

  const normalize = (value) => (value || '').toString().trim().toLowerCase();

  const applyFilter = () => {
    const term = normalize(filterInput.value);
    const selectedRole = roleSelect ? normalize(roleSelect.value) : '';

    items.forEach((item) => {
      const itemRole = normalize(item.dataset.role);
      const matchesRole = !selectedRole || itemRole === selectedRole;
      const matchesText = !term || item.textContent.toLowerCase().includes(term);
      item.style.display = matchesRole && matchesText ? '' : 'none';
    });
  };

  const compareByDataset = (a, b, key, direction = 'asc') => {
    const aValue = normalize(a.dataset[key]);
    const bValue = normalize(b.dataset[key]);
    const result = aValue.localeCompare(bValue);
    return direction === 'desc' ? result * -1 : result;
  };

  const applySort = () => {
    const value = sortSelect.value;
    const visibleItems = items.filter((item) => item.style.display !== 'none');

    visibleItems.sort((a, b) => {
      switch (value) {
        case 'name_desc':
          return compareByDataset(b, a, 'name');
        case 'role_asc':
          return compareByDataset(a, b, 'role');
        case 'role_desc':
          return compareByDataset(b, a, 'role');
        case 'name_asc':
        default:
          return compareByDataset(a, b, 'name');
      }
    });

    visibleItems.forEach((item) => list.appendChild(item));
  };

  const handleChange = () => {
    applyFilter();
    applySort();
  };

  filterInput.addEventListener('input', handleChange);
  sortSelect.addEventListener('change', handleChange);
  if (roleSelect) {
    roleSelect.addEventListener('change', handleChange);
  }

  handleChange();
}

export function initStaffFilters(configs = []) {
  if (!Array.isArray(configs)) {
    configs = [configs];
  }
  configs.forEach((config) => initSingleFilter(config));
}
