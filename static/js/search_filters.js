(function(window, document) {
  'use strict';

  function updateSelection(container, value, label) {
    const input = container.querySelector('[data-sort-input]');
    const labelEl = container.querySelector('[data-sort-label]');
    const items = container.querySelectorAll('[data-sort-option]');

    if (input) {
      input.value = value;
      input.dispatchEvent(new Event('change'));
    }

    if (labelEl) {
      labelEl.textContent = label;
    }

    if (items.length) {
      items.forEach(function(item) {
        item.classList.toggle('active', item.dataset.sortValue === value);
      });
    }

    container.dispatchEvent(
      new CustomEvent('searchfilterchange', {
        detail: { value: value, label: label },
        bubbles: false,
      })
    );
  }

  function initContainer(container) {
    if (!container || container.dataset.searchFilterInitialized === 'true') {
      return;
    }

    container.dataset.searchFilterInitialized = 'true';

    const items = container.querySelectorAll('[data-sort-option]');
    const button = container.querySelector('[data-sort-button]');
    const input = container.querySelector('[data-sort-input]');

    const defaultLabel = button
      ? button.getAttribute('data-sort-default-label') || button.title || ''
      : '';

    const applyInitialSelection = function() {
      const initialValue = input ? input.value : '';
      if (initialValue) {
        const initialItem = Array.prototype.find.call(items, function(item) {
          return item.dataset.sortValue === initialValue;
        });
        if (initialItem) {
          const initialLabel = initialItem.dataset.sortLabel || initialItem.textContent.trim();
          updateSelection(container, initialValue, initialLabel);
          return;
        }
      }
      if (button) {
        const labelEl = container.querySelector('[data-sort-label]');
        if (labelEl && defaultLabel) {
          labelEl.textContent = defaultLabel;
        }
      }
    };

    items.forEach(function(item) {
      item.addEventListener('click', function(event) {
        event.preventDefault();
        const value = item.dataset.sortValue || '';
        const label = item.dataset.sortLabel || item.textContent.trim();
        updateSelection(container, value, label);
      });
    });

    applyInitialSelection();
  }

  function init(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const containers = scope.querySelectorAll('[data-search-filter]');
    containers.forEach(initContainer);
  }

  window.SearchFilters = {
    init: init,
  };

  document.addEventListener('DOMContentLoaded', function() {
    init(document);
  });
})(window, document);
