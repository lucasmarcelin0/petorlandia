(function(window, document) {
  'use strict';

  const DEFAULT_MIN_CHARS = 2;
  const LOADING_MESSAGE = 'Buscando animais...';
  const EMPTY_MESSAGE_FALLBACK = 'Nenhum animal encontrado.';
  const dateTimeFormatter = (typeof Intl !== 'undefined' && Intl.DateTimeFormat)
    ? new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
    : null;

  function formatDateTime(value) {
    if (!value) {
      return '';
    }
    let dateValue = value instanceof Date ? value : null;
    if (!dateValue) {
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return '';
      }
      dateValue = parsed;
    }
    if (dateTimeFormatter) {
      return dateTimeFormatter.format(dateValue);
    }
    return dateValue.toLocaleString('pt-BR');
  }

  function parsePositiveInt(value) {
    const number = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(number)) {
      return null;
    }
    const truncated = Math.trunc(number);
    return truncated > 0 ? truncated : null;
  }

  function parseInitialAnimal(field) {
    if (!field || !field.dataset || !field.dataset.initialAnimal) {
      return null;
    }
    try {
      const parsed = JSON.parse(field.dataset.initialAnimal);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (error) {
      console.error(error);
      return null;
    }
  }

  function getSpeciesLabel(animal) {
    if (!animal) {
      return '';
    }
    if (animal.species_name) {
      return animal.species_name;
    }
    if (animal.species) {
      return animal.species;
    }
    return '';
  }

  function getAgeValue(animal) {
    if (!animal) {
      return '';
    }
    if (animal.age_display) {
      return animal.age_display;
    }
    if (animal.age) {
      return animal.age;
    }
    return '';
  }

  function getLastAppointmentLabel(animal) {
    if (!animal) {
      return '';
    }
    if (animal.last_appointment_display) {
      return `Último atendimento: ${animal.last_appointment_display}`;
    }
    if (animal.last_appointment) {
      const formatted = formatDateTime(animal.last_appointment);
      if (formatted) {
        return `Último atendimento: ${formatted}`;
      }
    }
    return 'Sem atendimento registrado';
  }

  function buildAnimalMetadataParts(animal, options = {}) {
    const { includeSpecies = false } = options;
    const parts = [];
    if (!animal) {
      return parts;
    }
    if (includeSpecies) {
      const speciesLabel = getSpeciesLabel(animal);
      if (speciesLabel) {
        parts.push(speciesLabel);
      }
    }
    const breedLabel = animal.breed_name || animal.breed;
    if (breedLabel) {
      parts.push(breedLabel);
    }
    const ageValue = getAgeValue(animal);
    if (ageValue) {
      parts.push(`Idade: ${ageValue}`);
    }
    const lastLabel = getLastAppointmentLabel(animal);
    if (lastLabel) {
      parts.push(lastLabel);
    }
    return parts;
  }

  function updateSelectionDisplay(container, animal) {
    if (!container) {
      return;
    }
    container.innerHTML = '';
    if (!animal) {
      return;
    }
    const nameEl = document.createElement('strong');
    nameEl.textContent = animal.name || 'Animal sem nome';
    container.appendChild(nameEl);

    if (animal.tutor_name) {
      const tutorLine = document.createElement('div');
      tutorLine.textContent = `Tutor: ${animal.tutor_name}`;
      container.appendChild(tutorLine);
    }

    const metadataParts = buildAnimalMetadataParts(animal, { includeSpecies: true });
    if (metadataParts.length) {
      const metaLine = document.createElement('div');
      metaLine.textContent = metadataParts.join(' • ');
      container.appendChild(metaLine);
    }
  }

  function createAnimalListItem(animal, onSelect) {
    if (!animal) {
      return null;
    }
    const item = document.createElement('li');
    item.className = 'list-group-item list-group-item-action';
    item.setAttribute('role', 'option');
    item.tabIndex = 0;

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-start gap-2';

    const nameEl = document.createElement('div');
    nameEl.className = 'fw-semibold';
    nameEl.textContent = animal.name || 'Animal sem nome';
    header.appendChild(nameEl);

    const speciesLabel = getSpeciesLabel(animal);
    if (speciesLabel) {
      const badge = document.createElement('span');
      badge.className = 'badge bg-light text-dark border';
      badge.textContent = speciesLabel;
      header.appendChild(badge);
    }

    item.appendChild(header);

    const tutorLine = document.createElement('div');
    tutorLine.className = 'small text-muted';
    tutorLine.textContent = animal.tutor_name
      ? `Tutor: ${animal.tutor_name}`
      : 'Tutor não informado';
    item.appendChild(tutorLine);

    const metadataParts = buildAnimalMetadataParts(animal);
    if (metadataParts.length) {
      const detailsLine = document.createElement('div');
      detailsLine.className = 'small text-muted';
      detailsLine.textContent = metadataParts.join(' • ');
      item.appendChild(detailsLine);
    }

    item.addEventListener('click', () => {
      if (typeof onSelect === 'function') {
        onSelect(animal);
      }
    });

    item.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (typeof onSelect === 'function') {
          onSelect(animal);
        }
      }
    });

    return item;
  }

  function initAppointmentForm(form) {
    if (!(form instanceof HTMLElement)) {
      return;
    }

    const tutorInput = form.querySelector('[data-appointment-tutor-input]');
    const tutorResults = form.querySelector('[data-appointment-tutor-results]');
    const tutorField = form.querySelector('[data-appointment-tutor-field]');
    const tutorSortInput = form.querySelector('[data-appointment-tutor-sort]');

    const animalInput = form.querySelector('[data-appointment-animal-input]');
    const animalResults = form.querySelector('[data-appointment-animal-results]');
    const animalField = form.querySelector('[data-appointment-animal-field]');
    const animalHelper = form.querySelector('[data-appointment-animal-helper]');
    const animalEmpty = form.querySelector('[data-appointment-animal-empty]');
    const animalSelectionDisplay = form.querySelector('[data-appointment-animal-selection]');
    const animalSortInput = form.querySelector('[data-appointment-animal-sort]');
    const animalSortContainer = form.querySelector('[data-search-filter][data-search-target="appointment-animal"]');

    if (!tutorInput || !tutorResults || !tutorField || !animalInput || !animalResults || !animalField) {
      return;
    }

    if (window.SearchFilters && typeof window.SearchFilters.init === 'function') {
      window.SearchFilters.init(form);
    }

    const minTutorChars = parsePositiveInt(tutorInput.dataset && tutorInput.dataset.minChars) || DEFAULT_MIN_CHARS;
    const minAnimalChars = parsePositiveInt(animalInput.dataset && animalInput.dataset.minChars) || DEFAULT_MIN_CHARS;
    const animalSearchUrl = (animalInput.dataset && animalInput.dataset.searchUrl) || '/buscar_animais';

    let selectedTutorId = parsePositiveInt(tutorField.value);
    let selectedTutorName = (tutorField.dataset && tutorField.dataset.initialLabel) || '';

    let selectedAnimal = parseInitialAnimal(animalField);
    let selectedAnimalName = selectedAnimal && selectedAnimal.name
      ? selectedAnimal.name.trim().toLowerCase()
      : '';

    let activeAnimalController = null;
    let lastAnimalQueryId = 0;

    const resultsEmptyMessage = (animalResults.dataset && animalResults.dataset.emptyMessage) || EMPTY_MESSAGE_FALLBACK;

    const setAnimalEmptyState = (visible) => {
      if (animalEmpty) {
        animalEmpty.classList.toggle('d-none', !visible);
      }
    };

    const clearAnimalResults = () => {
      animalResults.innerHTML = '';
      animalResults.classList.add('d-none');
    };

    const showAnimalLoading = () => {
      animalResults.innerHTML = '';
      const loadingItem = document.createElement('li');
      loadingItem.className = 'list-group-item text-muted';
      loadingItem.textContent = LOADING_MESSAGE;
      animalResults.appendChild(loadingItem);
      animalResults.classList.remove('d-none');
    };

    const updateAnimalSelection = (animal) => {
      selectedAnimal = animal || null;
      selectedAnimalName = selectedAnimal && selectedAnimal.name
        ? selectedAnimal.name.trim().toLowerCase()
        : '';
      if (animalField) {
        animalField.value = selectedAnimal && selectedAnimal.id != null
          ? String(selectedAnimal.id)
          : '';
      }
      updateSelectionDisplay(animalSelectionDisplay, selectedAnimal);
    };

    const handleAnimalSelected = (animal) => {
      if (!animal) {
        return;
      }
      updateAnimalSelection(animal);
      animalInput.value = animal.name || '';
      clearAnimalResults();
      setAnimalEmptyState(false);
    };

    const renderAnimalResults = (animals, { showEmptyState = false } = {}) => {
      animalResults.innerHTML = '';
      const hasAnimals = Array.isArray(animals) && animals.length > 0;
      if (!hasAnimals) {
        if (showEmptyState) {
          const message = resultsEmptyMessage;
          if (message) {
            const emptyItem = document.createElement('li');
            emptyItem.className = 'list-group-item text-muted';
            emptyItem.textContent = message;
            animalResults.appendChild(emptyItem);
          }
          animalResults.classList.remove('d-none');
        } else {
          animalResults.classList.add('d-none');
        }
        setAnimalEmptyState(showEmptyState);
        return;
      }

      animals.forEach((animal) => {
        const item = createAnimalListItem(animal, handleAnimalSelected);
        if (!item) {
          return;
        }
        const isSelected = selectedAnimal && String(selectedAnimal.id) === String(animal.id);
        item.classList.toggle('active', Boolean(isSelected));
        item.setAttribute('aria-selected', isSelected ? 'true' : 'false');
        animalResults.appendChild(item);
      });
      animalResults.scrollTop = 0;
      animalResults.classList.remove('d-none');
      setAnimalEmptyState(false);
    };

    const setAnimalInputDisabled = (disabled) => {
      if (disabled) {
        animalInput.value = '';
        animalInput.setAttribute('disabled', 'disabled');
        if (animalHelper) {
          animalHelper.classList.remove('d-none');
          if (animalHelper.id) {
            animalInput.setAttribute('aria-describedby', animalHelper.id);
          }
        }
      } else {
        animalInput.removeAttribute('disabled');
        if (animalHelper) {
          animalHelper.classList.add('d-none');
          if (animalHelper.id && animalInput.getAttribute('aria-describedby') === animalHelper.id) {
            animalInput.removeAttribute('aria-describedby');
          }
        }
      }
    };

    const clearAnimalSelection = ({ keepQuery = false } = {}) => {
      updateAnimalSelection(null);
      if (!keepQuery) {
        animalInput.value = '';
      }
    };

    const fetchAnimalById = async (animalId) => {
      const id = parsePositiveInt(animalId);
      if (!id) {
        return null;
      }
      try {
        const url = new URL(animalSearchUrl, window.location.origin);
        url.searchParams.set('animal_id', id);
        if (selectedTutorId) {
          url.searchParams.set('tutor_id', selectedTutorId);
        }
        if (animalSortInput && animalSortInput.value) {
          url.searchParams.set('sort', animalSortInput.value);
        }
        const response = await fetch(url.toString());
        if (!response.ok) {
          throw new Error('Erro ao buscar animal');
        }
        const payload = await response.json();
        if (Array.isArray(payload) && payload.length) {
          return payload[0];
        }
      } catch (error) {
        console.error(error);
      }
      return null;
    };

    const performAnimalSearch = async (rawQuery) => {
      if (!selectedTutorId) {
        setAnimalInputDisabled(true);
        return;
      }
      const query = String(rawQuery || '');
      const trimmed = query.trim();
      if (trimmed.length < minAnimalChars) {
        clearAnimalResults();
        setAnimalEmptyState(false);
        return;
      }

      if (activeAnimalController) {
        activeAnimalController.abort();
      }

      const controller = new AbortController();
      activeAnimalController = controller;
      const currentQueryId = ++lastAnimalQueryId;

      showAnimalLoading();
      setAnimalEmptyState(false);

      try {
        const url = new URL(animalSearchUrl, window.location.origin);
        url.searchParams.set('q', trimmed);
        url.searchParams.set('tutor_id', selectedTutorId);
        if (animalSortInput && animalSortInput.value) {
          url.searchParams.set('sort', animalSortInput.value);
        }
        const response = await fetch(url.toString(), { signal: controller.signal });
        if (!response.ok) {
          throw new Error('Erro ao buscar animais');
        }
        const payload = await response.json();
        if (currentQueryId !== lastAnimalQueryId) {
          return;
        }
        const animals = Array.isArray(payload) ? payload : [];
        renderAnimalResults(animals, { showEmptyState: true });
      } catch (error) {
        if (error.name === 'AbortError') {
          return;
        }
        console.error(error);
        if (currentQueryId === lastAnimalQueryId) {
          clearAnimalResults();
          setAnimalEmptyState(true);
        }
      } finally {
        if (currentQueryId === lastAnimalQueryId) {
          activeAnimalController = null;
        }
      }
    };

    const handleTutorSelection = (tutor) => {
      const newTutorId = parsePositiveInt(tutor && tutor.id);
      if (!newTutorId) {
        handleTutorCleared();
        return;
      }
      if (selectedTutorId === newTutorId) {
        selectedTutorName = tutor && tutor.name ? tutor.name : selectedTutorName;
        setAnimalInputDisabled(false);
        return;
      }
      selectedTutorId = newTutorId;
      selectedTutorName = tutor && tutor.name ? tutor.name : '';
      setAnimalInputDisabled(false);
      clearAnimalSelection({ keepQuery: true });
      clearAnimalResults();
      setAnimalEmptyState(false);
      if (animalInput.value.trim().length >= minAnimalChars) {
        performAnimalSearch(animalInput.value);
      }
    };

    const handleTutorCleared = () => {
      if (!selectedTutorId && !selectedTutorName) {
        setAnimalInputDisabled(true);
        return;
      }
      selectedTutorId = null;
      selectedTutorName = '';
      setAnimalInputDisabled(true);
      clearAnimalSelection({ keepQuery: false });
      clearAnimalResults();
      setAnimalEmptyState(false);
    };

    if (typeof window.setupTutorSearch === 'function') {
      window.setupTutorSearch({
        inputId: tutorInput.id,
        resultsId: tutorResults.id,
        hiddenFieldId: tutorField.id,
        searchUrl: (tutorInput.dataset && tutorInput.dataset.searchUrl) || '/buscar_tutores',
        minChars: minTutorChars,
        sortFieldId: tutorSortInput ? tutorSortInput.id : null,
        emptyStateMessage: (tutorResults.dataset && tutorResults.dataset.emptyMessage) || 'Nenhum tutor encontrado.',
        onSelect: handleTutorSelection,
        onClear: handleTutorCleared,
      });
    }

    if (tutorField) {
      tutorField.addEventListener('tutorselectionchange', (event) => {
        const tutor = event.detail && event.detail.tutor ? event.detail.tutor : null;
        if (tutor) {
          handleTutorSelection(tutor);
        } else {
          handleTutorCleared();
        }
      });
    }

    if (selectedTutorId) {
      setAnimalInputDisabled(false);
    } else {
      setAnimalInputDisabled(true);
    }

    updateSelectionDisplay(animalSelectionDisplay, selectedAnimal || null);

    if (animalField.value && (!selectedAnimal || !selectedAnimal.last_appointment_display)) {
      fetchAnimalById(animalField.value).then((animal) => {
        if (!animal) {
          return;
        }
        selectedAnimal = animal;
        selectedAnimalName = animal.name ? animal.name.trim().toLowerCase() : '';
        updateSelectionDisplay(animalSelectionDisplay, animal);
        if (!animalInput.value) {
          animalInput.value = animal.name || '';
        }
      });
    }

    animalInput.addEventListener('input', () => {
      const value = animalInput.value || '';
      const normalized = value.trim().toLowerCase();
      if (selectedAnimal && normalized !== selectedAnimalName) {
        clearAnimalSelection({ keepQuery: true });
      }
      if (!selectedTutorId) {
        setAnimalInputDisabled(true);
        return;
      }
      if (normalized.length < minAnimalChars) {
        clearAnimalResults();
        setAnimalEmptyState(false);
        return;
      }
      performAnimalSearch(value);
    });

    animalInput.addEventListener('focus', () => {
      if (animalResults.children.length > 0) {
        animalResults.classList.remove('d-none');
      }
    });

    animalInput.addEventListener('click', () => {
      if (animalResults.children.length > 0) {
        animalResults.classList.remove('d-none');
      }
    });

    animalInput.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        clearAnimalResults();
      }
    });

    if (animalSortContainer) {
      animalSortContainer.addEventListener('searchfilterchange', () => {
        if (animalInput.value.trim().length >= minAnimalChars) {
          performAnimalSearch(animalInput.value);
        }
      });
    }

    document.addEventListener('click', (event) => {
      if (!animalResults.contains(event.target) && event.target !== animalInput) {
        clearAnimalResults();
      }
    });
  }

  function initAllAppointmentForms() {
    const forms = document.querySelectorAll('[data-appointment-form]');
    forms.forEach(initAppointmentForm);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllAppointmentForms);
  } else {
    initAllAppointmentForms();
  }
})(window, document);
