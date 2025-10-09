(function(window) {
  function setupTutorSearch(options = {}) {
    const {
      inputId = 'autocomplete-tutor',
      resultsId = 'tutor-results',
      hiddenFieldId = 'tutor_id',
      searchUrl = '/buscar_tutores',
      minChars = 2,
      validationMessageId = null,
      sortFieldId = null,
      emptyStateMessage = 'Nenhum tutor encontrado.',
      onSelect = null,
      onClear = null,
    } = options;

    const tutorInput = document.getElementById(inputId);
    const resultsContainer = document.getElementById(resultsId);
    const tutorIdField = document.getElementById(hiddenFieldId);
    const sortField = sortFieldId ? document.getElementById(sortFieldId) : null;
    const sortContainer = sortField ? sortField.closest('[data-search-filter]') : null;

    if (!tutorInput || !resultsContainer || !tutorIdField) {
      return null;
    }

    const resolvedEmptyMessage = (
      resultsContainer.dataset && resultsContainer.dataset.emptyMessage
    )
      ? resultsContainer.dataset.emptyMessage
      : emptyStateMessage;

    if (resultsContainer.dataset && !resultsContainer.dataset.emptyMessage && resolvedEmptyMessage) {
      resultsContainer.dataset.emptyMessage = resolvedEmptyMessage;
    }

    const validationMessage = validationMessageId
      ? document.getElementById(validationMessageId)
      : null;

    const normalize = (value) => (value || '').trim().toLowerCase();

    let selectedTutorName = '';
    let currentTutor = null;

    const dispatchTutorSelectionChange = (tutor) => {
      if (!tutorIdField) {
        return;
      }
      const detail = tutor ? { tutor: { ...tutor } } : { tutor: null };
      tutorIdField.dispatchEvent(
        new CustomEvent('tutorselectionchange', {
          detail,
          bubbles: true,
        })
      );
      tutorIdField.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const hideValidationMessage = () => {
      if (validationMessage) {
        validationMessage.classList.add('d-none');
      }
    };

    const showValidationMessage = () => {
      if (validationMessage) {
        validationMessage.classList.remove('d-none');
      }
    };

    const clearTutorSelection = () => {
      tutorIdField.value = '';
      selectedTutorName = '';
      currentTutor = null;
      hideValidationMessage();
      if (typeof onClear === 'function') {
        onClear();
      }
      dispatchTutorSelectionChange(null);
    };

    const closeResults = () => {
      resultsContainer.classList.add('d-none');
    };

    const enforceSelectionConsistency = () => {
      if (tutorIdField.value && normalize(tutorInput.value) !== selectedTutorName) {
        clearTutorSelection();
      }
    };

    const openResults = () => {
      enforceSelectionConsistency();
      if (resultsContainer.children.length > 0) {
        resultsContainer.classList.remove('d-none');
      }
    };

    const handleTutorSelected = (tutor) => {
      selectedTutorName = normalize(tutor.name);
      tutorInput.value = tutor.name;
      tutorIdField.value = tutor.id;
      currentTutor = { ...tutor };
      hideValidationMessage();
      closeResults();
      if (typeof onSelect === 'function') {
        onSelect(tutor);
      }
      dispatchTutorSelectionChange(tutor);
    };

    let activeSearchController = null;
    let lastQueryId = 0;

    tutorInput.addEventListener('input', async () => {
      enforceSelectionConsistency();
      hideValidationMessage();

      const query = tutorInput.value.trim();
      if (query.length < minChars) {
        closeResults();
        resultsContainer.innerHTML = '';
        return;
      }

      if (activeSearchController) {
        activeSearchController.abort();
      }

      const currentQueryId = ++lastQueryId;
      activeSearchController = new AbortController();

      try {
        const url = new URL(searchUrl, window.location.origin);
        url.searchParams.set('q', query);
        if (sortField && sortField.value) {
          url.searchParams.set('sort', sortField.value);
        }

        const response = await fetch(url.toString(), {
          signal: activeSearchController.signal,
        });
        if (!response.ok) {
          throw new Error('Erro ao buscar tutores');
        }

        const tutors = await response.json();
        if (currentQueryId !== lastQueryId) {
          return;
        }
        resultsContainer.innerHTML = '';

        tutors.forEach((tutor) => {
          const li = document.createElement('li');
          li.className = 'list-group-item list-group-item-action';

          const nameLine = document.createElement('div');
          nameLine.className = 'fw-semibold';
          nameLine.textContent = tutor.name || 'Tutor sem nome';
          li.appendChild(nameLine);

          const detailsLine = tutor.details || [
            tutor.email,
            tutor.phone,
            tutor.cpf ? `CPF: ${tutor.cpf}` : null,
            tutor.rg ? `RG: ${tutor.rg}` : null,
            tutor.worker,
          ]
            .filter(Boolean)
            .join(' • ');

          if (detailsLine) {
            const detailsEl = document.createElement('div');
            detailsEl.className = 'small text-muted';
            detailsEl.textContent = detailsLine;
            li.appendChild(detailsEl);
          }

          if (tutor.address_summary) {
            const addressEl = document.createElement('div');
            addressEl.className = 'small text-muted';
            addressEl.textContent = tutor.address_summary;
            li.appendChild(addressEl);
          }

          li.addEventListener('click', () => handleTutorSelected(tutor));
          resultsContainer.appendChild(li);
        });

        const hasResults = tutors.length > 0;
        if (!hasResults && resolvedEmptyMessage) {
          const emptyItem = document.createElement('li');
          emptyItem.className = 'list-group-item text-muted';
          emptyItem.textContent = resolvedEmptyMessage;
          resultsContainer.appendChild(emptyItem);
        }

        resultsContainer.classList.toggle('d-none', !hasResults && !resolvedEmptyMessage);
      } catch (error) {
        if (error.name === 'AbortError') {
          return;
        }
        console.error(error);
        resultsContainer.innerHTML = '';
        closeResults();
      }
    });

    tutorInput.addEventListener('focus', openResults);
    tutorInput.addEventListener('click', openResults);

    if (sortContainer) {
      sortContainer.addEventListener('searchfilterchange', () => {
        if (normalize(tutorInput.value).length >= minChars) {
          tutorInput.dispatchEvent(new Event('input'));
        }
      });
    }

    document.addEventListener('click', (event) => {
      if (!resultsContainer.contains(event.target) && event.target !== tutorInput) {
        closeResults();
      }
    });

    return {
      clearTutorSelection,
      hideValidationMessage,
      showValidationMessage,
      hasSelection: () => Boolean(tutorIdField.value),
      getTypedValue: () => tutorInput.value.trim(),
      getSelectedTutor: () => currentTutor,
    };
  }

  window.setupTutorSearch = setupTutorSearch;
})(window);
