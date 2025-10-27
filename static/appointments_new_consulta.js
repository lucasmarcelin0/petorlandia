function setupTutorFilter(form) {
  if (!(form instanceof HTMLElement)) {
    return;
  }
  const tutorSelect = form.querySelector('[data-appointment-tutor-select]');
  const animalSelect = form.querySelector('[data-appointment-animal-select]');
  if (!tutorSelect || !animalSelect) {
    return;
  }
  const emptyMessage = form.querySelector('[data-appointment-animal-empty]');
  const options = Array.from(animalSelect.options || []);

  function ensureValidSelection(visibleOptions) {
    if (!visibleOptions.length) {
      animalSelect.value = '';
      return;
    }
    const currentValue = animalSelect.value;
    const hasCurrent = visibleOptions.some((option) => option.value === currentValue);
    if (!hasCurrent) {
      animalSelect.value = visibleOptions[0].value;
    }
  }

  function toggleOptions(selectedTutor) {
    const normalizedTutor = selectedTutor === undefined || selectedTutor === null
      ? ''
      : String(selectedTutor);
    const visibleOptions = [];
    options.forEach((option) => {
      const optionTutor = option.dataset?.tutorId ?? '';
      const matches = !normalizedTutor || normalizedTutor === '0' || optionTutor === normalizedTutor;
      option.hidden = !matches;
      option.disabled = !matches;
      if (matches) {
        visibleOptions.push(option);
      }
    });
    const hasVisible = visibleOptions.length > 0;
    animalSelect.disabled = !hasVisible;
    if (emptyMessage) {
      emptyMessage.classList.toggle('d-none', hasVisible);
    }
    if (!hasVisible) {
      animalSelect.value = '';
      return;
    }
    ensureValidSelection(visibleOptions);
  }

  tutorSelect.addEventListener('change', (event) => {
    const { value } = event.target;
    toggleOptions(value);
  });

  toggleOptions(tutorSelect.value);
}

function setupAllTutorFilters() {
  const forms = document.querySelectorAll('[data-appointment-form]');
  forms.forEach((form) => {
    setupTutorFilter(form);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupAllTutorFilters);
} else {
  setupAllTutorFilters();
}

export {};
