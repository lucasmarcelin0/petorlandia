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
  const crmvInput = resolveElement(config.crmvSelector || config.crmvInput);
  const specialtySelect = resolveElement(config.specialtySelector || config.specialtySelect);
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
  const specialtiesCache = new WeakMap();

  const getSelectedSpecialties = () => {
    if (!specialtySelect) return [];
    if (specialtySelect.multiple) {
      return Array.from(specialtySelect.selectedOptions || [])
        .map((option) => normalize(option.value))
        .filter(Boolean);
    }
    const value = normalize(specialtySelect.value);
    return value ? [value] : [];
  };

  const getItemSpecialties = (item) => {
    if (specialtiesCache.has(item)) {
      return specialtiesCache.get(item);
    }
    const parsed = (item.dataset.specialties || '')
      .split('|')
      .map((value) => normalize(value))
      .filter(Boolean);
    specialtiesCache.set(item, parsed);
    return parsed;
  };

  const applyFilter = () => {
    const term = normalize(filterInput.value);
    const selectedRole = roleSelect ? normalize(roleSelect.value) : '';
    const crmvTerm = crmvInput ? normalize(crmvInput.value) : '';
    const selectedSpecialties = getSelectedSpecialties();

    items.forEach((item) => {
      const itemRole = normalize(item.dataset.role);
      const matchesRole = !selectedRole || itemRole === selectedRole;
      const matchesText = !term || item.textContent.toLowerCase().includes(term);
      const itemCrmv = normalize(item.dataset.crmv);
      const matchesCrmv = !crmvTerm || itemCrmv.includes(crmvTerm);
      const itemSpecialties = getItemSpecialties(item);
      const matchesSpecialties =
        !selectedSpecialties.length || selectedSpecialties.every((spec) => itemSpecialties.includes(spec));
      item.style.display = matchesRole && matchesText && matchesCrmv && matchesSpecialties ? '' : 'none';
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
  if (crmvInput) {
    crmvInput.addEventListener('input', handleChange);
  }
  if (specialtySelect) {
    specialtySelect.addEventListener('change', handleChange);
  }

  handleChange();
}

export function initStaffFilters(configs = []) {
  if (!Array.isArray(configs)) {
    configs = [configs];
  }
  configs.forEach((config) => initSingleFilter(config));
}
