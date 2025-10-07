(function () {
  const SORT_STORAGE_KEY = 'tutorSortPreference';
  const FILTER_STORAGE_KEY = 'tutorFilterPreference';

  function fetchTutors(term) {
    if (!term || term.length < 2) {
      return Promise.resolve([]);
    }
    const url = `/buscar_tutores?q=${encodeURIComponent(term)}`;
    return fetch(url, { headers: { 'Accept': 'application/json' } })
      .then(resp => (resp.ok ? resp.json() : []))
      .catch(() => []);
  }

  function toggleCombobox(listEl, container, show) {
    if (!listEl) {
      return;
    }
    if (show) {
      listEl.classList.remove('d-none');
      container?.classList.add('is-open');
    } else {
      listEl.classList.add('d-none');
      container?.classList.remove('is-open');
    }
  }

  function initTutorQuickSearch() {
    const input = document.getElementById('busca-tutor');
    const list = document.getElementById('lista-tutores');
    if (!input || !list) {
      return;
    }
    const container = input.closest('[data-combobox]') || input.parentElement;

    const hideList = () => toggleCombobox(list, container, false);

    input.addEventListener('input', async () => {
      const term = input.value.trim();
      if (term.length < 2) {
        list.innerHTML = '';
        hideList();
        return;
      }
      const tutors = await fetchTutors(term);
      list.innerHTML = '';
      if (!tutors.length) {
        hideList();
        return;
      }
      tutors.forEach(tutor => {
        const li = document.createElement('li');
        li.className = 'list-group-item list-group-item-action';
        const parts = [`${tutor.name} (${tutor.email})`];
        if (tutor.specialties) {
          parts.push(`– ${tutor.specialties}`);
        }
        li.textContent = parts.join(' ');
        li.addEventListener('click', () => {
          window.location.href = `/ficha_tutor/${tutor.id}`;
        });
        list.appendChild(li);
      });
      toggleCombobox(list, container, true);
    });

    document.addEventListener('click', event => {
      if (!container?.contains(event.target)) {
        hideList();
      }
    });
  }

  function getCardAge(card) {
    if (!card.dataset.dob) {
      return 0;
    }
    const diff = Date.now() - new Date(card.dataset.dob).getTime();
    return Math.floor(diff / (365.25 * 24 * 60 * 60 * 1000));
  }

  function initTutorListControls() {
    const filterInput = document.getElementById('tutor-filter');
    const sortSelect = document.getElementById('tutor-sort');
    const container = document.getElementById('tutor-cards');
    if (!filterInput || !sortSelect || !container) {
      return;
    }

    const cards = Array.from(container.querySelectorAll('[data-name]'));

    try {
      const savedFilter = localStorage.getItem(FILTER_STORAGE_KEY);
      if (savedFilter !== null) {
        filterInput.value = savedFilter;
      }
      const savedSort = localStorage.getItem(SORT_STORAGE_KEY);
      if (savedSort && Array.from(sortSelect.options).some(opt => opt.value === savedSort)) {
        sortSelect.value = savedSort;
      }
    } catch (err) {
      // ignore storage errors
    }

    const applyFilter = () => {
      const term = filterInput.value.toLowerCase();
      cards.forEach(card => {
        const text = card.textContent.toLowerCase();
        const cpf = (card.dataset.cpf || '').toLowerCase();
        const phone = (card.dataset.phone || '').toLowerCase();
        const matches = text.includes(term) || cpf.includes(term) || phone.includes(term);
        card.style.display = matches ? '' : 'none';
      });
    };

    const applySort = () => {
      const value = sortSelect.value;
      const visible = cards.filter(card => card.style.display !== 'none');
      const hidden = cards.filter(card => card.style.display === 'none');
      visible.sort((a, b) => {
        switch (value) {
          case 'name_desc':
            return b.dataset.name.localeCompare(a.dataset.name);
          case 'date_asc':
            return new Date(a.dataset.date) - new Date(b.dataset.date);
          case 'date_desc':
            return new Date(b.dataset.date) - new Date(a.dataset.date);
          case 'age_asc':
            return getCardAge(a) - getCardAge(b);
          case 'age_desc':
            return getCardAge(b) - getCardAge(a);
          case 'name_asc':
          default:
            return a.dataset.name.localeCompare(b.dataset.name);
        }
      });
      visible.forEach(card => container.appendChild(card));
      hidden.forEach(card => container.appendChild(card));
    };

    filterInput.addEventListener('input', () => {
      try {
        localStorage.setItem(FILTER_STORAGE_KEY, filterInput.value);
      } catch (err) {}
      applyFilter();
      applySort();
    });

    sortSelect.addEventListener('change', () => {
      try {
        localStorage.setItem(SORT_STORAGE_KEY, sortSelect.value);
      } catch (err) {}
      applySort();
    });

    applyFilter();
    applySort();
  }

  function initDobAgeSync() {
    const dobInput = document.getElementById('date_of_birth');
    const ageInput = document.getElementById('age');
    if (!dobInput || !ageInput || typeof flatpickr !== 'function') {
      return;
    }

    const picker = flatpickr(dobInput, {
      locale: 'pt',
      dateFormat: 'Y-m-d',
      altInput: true,
      altFormat: 'd/m/Y',
      allowInput: true,
      onChange(selectedDates) {
        if (!selectedDates.length) {
          return;
        }
        const dob = selectedDates[0];
        const today = new Date();
        let age = today.getFullYear() - dob.getFullYear();
        const monthDiff = today.getMonth() - dob.getMonth();
        if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < dob.getDate())) {
          age -= 1;
        }
        ageInput.value = age;
      }
    });

    ageInput.addEventListener('input', () => {
      const age = parseInt(ageInput.value, 10);
      if (Number.isNaN(age)) {
        return;
      }
      const today = new Date();
      const estimatedDOB = new Date(today.getFullYear() - age, today.getMonth(), today.getDate());
      picker.setDate(estimatedDOB, true);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initTutorQuickSearch();
    initTutorListControls();
    initDobAgeSync();
  });
})();
