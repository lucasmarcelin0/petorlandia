(function () {
  function safeRead(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      console.warn('Não foi possível ler a preferência da barra de agenda.', error);
      return null;
    }
  }

  function safeWrite(key, value) {
    try {
      if (value) {
        window.localStorage.setItem(key, value);
      } else {
        window.localStorage.removeItem(key);
      }
    } catch (error) {
      console.warn('Não foi possível salvar a preferência da barra de agenda.', error);
    }
  }

  function initialiseToolbar(toolbar, index) {
    if (!toolbar) {
      return;
    }

    const toggleButtons = Array.from(
      toolbar.querySelectorAll('[data-bs-toggle="collapse"][data-bs-target]')
    );

    if (!toggleButtons.length) {
      return;
    }

    const items = toggleButtons
      .map((button) => {
        const targetSelector = button.getAttribute('data-bs-target');
        if (!targetSelector) {
          return null;
        }
        const collapseElement = document.querySelector(targetSelector);
        if (!collapseElement) {
          return null;
        }
        return { button, collapseElement };
      })
      .filter(Boolean);

    if (!items.length) {
      return;
    }

    const firstCollapse = items[0].collapseElement;
    const parentSelector = firstCollapse.getAttribute('data-bs-parent');
    let groupId = null;

    if (parentSelector && parentSelector.trim().startsWith('#')) {
      groupId = parentSelector.trim().slice(1);
    }

    if (!groupId) {
      groupId = toolbar.id || `schedule-toolbar-${index}`;
    }

    const storageKey = `scheduleToolbarState:${groupId}`;

    const closeOthers = (currentCollapse) => {
      items.forEach(({ collapseElement, button }) => {
        if (collapseElement === currentCollapse) {
          return;
        }

        if (collapseElement.classList.contains('show')) {
          const instance = bootstrap.Collapse.getOrCreateInstance(collapseElement, {
            toggle: false,
          });
          instance.hide();
        }

        button.classList.add('collapsed');
        button.setAttribute('aria-expanded', 'false');
      });
    };

    items.forEach(({ button, collapseElement }) => {
      collapseElement.addEventListener('show.bs.collapse', () => {
        closeOthers(collapseElement);
        button.classList.remove('collapsed');
        button.setAttribute('aria-expanded', 'true');
        safeWrite(storageKey, collapseElement.id || '');
      });

      collapseElement.addEventListener('hidden.bs.collapse', () => {
        button.classList.add('collapsed');
        button.setAttribute('aria-expanded', 'false');
        const storedId = safeRead(storageKey);
        if (storedId && storedId === (collapseElement.id || '')) {
          safeWrite(storageKey, '');
        }
      });

      if (collapseElement.classList.contains('show')) {
        button.classList.remove('collapsed');
        button.setAttribute('aria-expanded', 'true');
      } else {
        button.classList.add('collapsed');
        button.setAttribute('aria-expanded', 'false');
      }
    });

    const storedId = safeRead(storageKey);
    if (storedId) {
      const match = items.find(({ collapseElement }) => collapseElement.id === storedId);
      if (match && !match.collapseElement.classList.contains('show')) {
        bootstrap.Collapse.getOrCreateInstance(match.collapseElement, { toggle: false }).show();
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (typeof bootstrap === 'undefined' || !bootstrap.Collapse) {
      return;
    }

    const toolbars = document.querySelectorAll('.schedule-toolbar');
    toolbars.forEach((toolbar, index) => initialiseToolbar(toolbar, index));
  });
})();
