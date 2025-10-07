(function (window, document) {
  'use strict';

  const namespace = window.TutorSearch || (window.TutorSearch = {});
  const DEFAULT_LOADING_MESSAGE = 'Buscando tutores...';
  const DEFAULT_EMPTY_MESSAGE = 'Nenhum tutor encontrado.';
  const DEFAULT_ERROR_MESSAGE = 'Não foi possível carregar os tutores.';

  class TutorSearch {
    constructor(root) {
      this.root = root;
      this.combo = root.querySelector('[data-tutor-search-combobox]');
      this.input = root.querySelector('[data-tutor-search-input]');
      this.list = root.querySelector('[data-tutor-search-list]');
      this.status = root.querySelector('[data-tutor-search-status]');
      this.optionIdPrefix = root.dataset.optionIdPrefix || (this.list ? `${this.list.id}-option-` : 'tutor-option-');
      this.minChars = parseInt(root.dataset.minChars || '2', 10);
      this.searchUrl = root.dataset.searchUrl || '/buscar_tutores';
      this.requiresSelection = root.dataset.requiresSelection === 'true';
      this.redirectTemplate = root.dataset.redirectTemplate || '';
      this.hiddenInput = null;
      const hiddenId = root.dataset.hiddenInputId;
      if (hiddenId) {
        this.hiddenInput = document.getElementById(hiddenId);
      }

      this.abortController = null;
      this.options = [];
      this.activeIndex = -1;
      this.lastQuery = '';
      this.boundDocumentClick = this.handleDocumentClick.bind(this);
      this.boundInputFocus = this.handleInputFocus.bind(this);

      this.bindEvents();
      document.addEventListener('pointerdown', this.boundDocumentClick);
    }

    bindEvents() {
      if (!this.input) {
        return;
      }

      this.input.addEventListener('input', (event) => this.handleInput(event));
      this.input.addEventListener('keydown', (event) => this.handleKeydown(event));
      this.input.addEventListener('blur', () => this.handleBlur());
      this.input.addEventListener('focus', this.boundInputFocus);
    }

    handleInput(event) {
      const value = (event.target.value || '').trim();
      this.lastQuery = value;

      if (this.hiddenInput) {
        this.hiddenInput.value = '';
      }

      if (this.requiresSelection && this.input) {
        if (value) {
          this.input.setAttribute('aria-invalid', 'true');
        } else {
          this.input.removeAttribute('aria-invalid');
        }
      }

      if (!value) {
        this.clearOptions();
        this.closeList();
        this.updateStatus('');
        return;
      }

      if (value.length < this.minChars) {
        this.clearOptions();
        this.closeList();
        this.updateStatus(this.getMinCharsMessage());
        return;
      }

      this.fetchOptions(value);
    }

    handleKeydown(event) {
      if (!this.options.length && !['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) {
        return;
      }

      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          if (!this.options.length) {
            this.fetchOptions(this.lastQuery || this.input.value.trim());
            return;
          }
          this.openList();
          this.setActiveIndex(this.activeIndex + 1);
          break;
        case 'ArrowUp':
          event.preventDefault();
          if (!this.options.length) {
            return;
          }
          this.openList();
          this.setActiveIndex(this.activeIndex - 1);
          break;
        case 'Enter':
          if (this.activeIndex >= 0 && this.options[this.activeIndex]) {
            event.preventDefault();
            this.selectOption(this.activeIndex);
          }
          break;
        case 'Escape':
          if (this.isListOpen()) {
            event.preventDefault();
            this.closeList();
          }
          break;
        case 'Tab':
          this.closeList();
          break;
        default:
          break;
      }
    }

    handleBlur() {
      window.setTimeout(() => {
        if (!this.root.contains(document.activeElement)) {
          this.closeList();
        }
      }, 100);
    }

    handleInputFocus() {
      if (this.options.length) {
        this.openList();
      }
    }

    handleDocumentClick(event) {
      if (!this.root.contains(event.target)) {
        this.closeList();
      }
    }

    async fetchOptions(query) {
      if (!this.list || !this.input) {
        return;
      }

      if (this.abortController) {
        this.abortController.abort();
      }
      this.abortController = new AbortController();

      this.setBusyState(true);
      this.updateStatus(DEFAULT_LOADING_MESSAGE);

      try {
        const url = new URL(this.searchUrl, window.location.origin);
        url.searchParams.set('q', query);
        const response = await fetch(url.toString(), { signal: this.abortController.signal });
        if (!response.ok) {
          throw new Error('Network response was not ok');
        }
        const data = await response.json();
        this.renderOptions(Array.isArray(data) ? data : []);
      } catch (error) {
        if (error.name === 'AbortError') {
          return;
        }
        this.clearOptions();
        this.updateStatus(DEFAULT_ERROR_MESSAGE);
        this.closeList();
        console.error('TutorSearch fetch error:', error);
      } finally {
        this.setBusyState(false);
      }
    }

    renderOptions(items) {
      this.clearOptions();

      if (!items.length) {
        this.updateStatus(DEFAULT_EMPTY_MESSAGE);
        this.closeList();
        return;
      }

      this.options = items.map((item, index) => {
        const optionId = `${this.optionIdPrefix}${index}`;
        const li = document.createElement('li');
        li.className = 'list-group-item list-group-item-action';
        li.id = optionId;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');

        const emailText = item.email ? ` (${item.email})` : '';
        const specialtiesText = item.specialties ? ` – ${item.specialties}` : '';
        const label = `${item.name || ''}${emailText}${specialtiesText}`.trim();
        li.textContent = label || item.name || '';

        li.dataset.tutorId = item.id;
        li.dataset.tutorName = item.name || '';
        li.dataset.tutorEmail = item.email || '';
        li.dataset.tutorSpecialties = item.specialties || '';

        li.addEventListener('mouseenter', () => this.setActiveIndex(index));
        li.addEventListener('mousemove', () => this.setActiveIndex(index));
        li.addEventListener('mousedown', (event) => event.preventDefault());
        li.addEventListener('click', () => this.selectOption(index));

        this.list.appendChild(li);

        return {
          element: li,
          data: {
            id: item.id,
            name: item.name,
            email: item.email,
            specialties: item.specialties,
            label,
          },
        };
      });

      this.updateStatus(this.getResultsMessage(this.options.length));
      this.openList();
      this.activeIndex = -1;
    }

    setActiveIndex(index) {
      if (!this.options.length) {
        return;
      }

      const maxIndex = this.options.length - 1;
      if (index > maxIndex) {
        index = 0;
      } else if (index < 0) {
        index = maxIndex;
      }

      if (this.activeIndex === index) {
        return;
      }

      if (this.activeIndex >= 0) {
        const prev = this.options[this.activeIndex];
        if (prev) {
          prev.element.classList.remove('active');
          prev.element.setAttribute('aria-selected', 'false');
        }
      }

      this.activeIndex = index;
      const current = this.options[this.activeIndex];
      if (!current) {
        return;
      }

      current.element.classList.add('active');
      current.element.setAttribute('aria-selected', 'true');
      if (this.input) {
        this.input.setAttribute('aria-activedescendant', current.element.id);
      }
      this.ensureOptionVisible(current.element);
    }

    ensureOptionVisible(element) {
      if (!element || typeof element.scrollIntoView !== 'function') {
        return;
      }
      element.scrollIntoView({ block: 'nearest' });
    }

    selectOption(index) {
      const option = this.options[index];
      if (!option) {
        return;
      }

      if (this.input) {
        this.input.value = option.data.label || option.data.name || '';
      }
      if (this.hiddenInput) {
        this.hiddenInput.value = option.data.id;
      }

      if (this.requiresSelection && this.input) {
        this.input.setAttribute('aria-invalid', 'false');
      }

      this.updateStatus(`Tutor ${option.data.name || ''} selecionado.`.trim());
      this.closeList();

      const detail = { ...option.data };
      const event = new CustomEvent('tutor-search:selected', { detail });
      this.root.dispatchEvent(event);

      if (this.redirectTemplate) {
        const target = this.buildRedirectUrl(option.data.id);
        if (target) {
          window.location.href = target;
        }
      }
    }

    buildRedirectUrl(id) {
      if (!this.redirectTemplate) {
        return '';
      }

      if (this.redirectTemplate.includes('{id}')) {
        return this.redirectTemplate.replace('{id}', id);
      }

      const separator = this.redirectTemplate.endsWith('/') ? '' : '/';
      return `${this.redirectTemplate}${separator}${id}`;
    }

    clearOptions() {
      if (this.list) {
        this.list.innerHTML = '';
      }
      this.options = [];
      this.activeIndex = -1;
      if (this.input) {
        this.input.removeAttribute('aria-activedescendant');
      }
    }

    openList() {
      if (!this.list) {
        return;
      }
      this.list.classList.remove('d-none');
      if (this.combo) {
        this.combo.setAttribute('aria-expanded', 'true');
      }
    }

    closeList() {
      if (!this.list) {
        return;
      }
      this.list.classList.add('d-none');
      if (this.combo) {
        this.combo.setAttribute('aria-expanded', 'false');
      }
      if (this.activeIndex >= 0 && this.options[this.activeIndex]) {
        const current = this.options[this.activeIndex];
        current.element.classList.remove('active');
        current.element.setAttribute('aria-selected', 'false');
      }
      this.activeIndex = -1;
      if (this.input) {
        this.input.removeAttribute('aria-activedescendant');
      }
    }

    isListOpen() {
      return this.list ? !this.list.classList.contains('d-none') : false;
    }

    setBusyState(isBusy) {
      if (this.combo) {
        this.combo.setAttribute('aria-busy', String(isBusy));
      }
    }

    updateStatus(message) {
      if (!this.status) {
        return;
      }
      this.status.textContent = message;
    }

    getMinCharsMessage() {
      if (this.minChars <= 1) {
        return '';
      }
      return `Digite pelo menos ${this.minChars} caracteres para buscar.`;
    }

    getResultsMessage(total) {
      if (total === 1) {
        return '1 tutor encontrado.';
      }
      return `${total} tutores encontrados.`;
    }
  }

  function initAll(root = document) {
    const elements = Array.from(root.querySelectorAll('[data-module="tutor-search"]'));

    elements.forEach((element) => {
      if (element.dataset.tutorSearchBound === 'true') {
        return;
      }
      element.dataset.tutorSearchBound = 'true';
      const instance = new TutorSearch(element);
      namespace.instances.push(instance);
    });
  }

  namespace.instances = namespace.instances || [];
  namespace.initAll = initAll;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initAll());
  } else {
    initAll();
  }
})(window, document);
