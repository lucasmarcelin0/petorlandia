(function(window) {
  function setupTutorSearch(options = {}) {
    const {
      inputId = 'autocomplete-tutor',
      resultsId = 'tutor-results',
      hiddenFieldId = 'tutor_id',
      searchUrl = '/buscar_tutores',
      minChars = 2,
      validationMessageId = null,
    } = options;

    const tutorInput = document.getElementById(inputId);
    const resultsContainer = document.getElementById(resultsId);
    const tutorIdField = document.getElementById(hiddenFieldId);

    if (!tutorInput || !resultsContainer || !tutorIdField) {
      return null;
    }

    const validationMessage = validationMessageId
      ? document.getElementById(validationMessageId)
      : null;

    const normalize = (value) => (value || '').trim().toLowerCase();

    let selectedTutorName = '';

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
      hideValidationMessage();
      closeResults();
    };

    tutorInput.addEventListener('input', async () => {
      enforceSelectionConsistency();
      hideValidationMessage();

      const query = tutorInput.value.trim();
      if (query.length < minChars) {
        closeResults();
        resultsContainer.innerHTML = '';
        return;
      }

      try {
        const response = await fetch(`${searchUrl}?q=${encodeURIComponent(query)}`);
        if (!response.ok) {
          throw new Error('Erro ao buscar tutores');
        }

        const tutors = await response.json();
        resultsContainer.innerHTML = '';

        tutors.forEach((tutor) => {
          const li = document.createElement('li');
          li.className = 'list-group-item list-group-item-action';
          li.textContent = `${tutor.name} (${tutor.email})`;
          li.addEventListener('click', () => handleTutorSelected(tutor));
          resultsContainer.appendChild(li);
        });

        resultsContainer.classList.toggle('d-none', tutors.length === 0);
      } catch (error) {
        console.error(error);
        resultsContainer.innerHTML = '';
        closeResults();
      }
    });

    tutorInput.addEventListener('focus', openResults);
    tutorInput.addEventListener('click', openResults);

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
    };
  }

  window.setupTutorSearch = setupTutorSearch;
})(window);
