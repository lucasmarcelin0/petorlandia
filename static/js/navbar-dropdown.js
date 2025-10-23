document.addEventListener('DOMContentLoaded', () => {
  const triggers = Array.from(document.querySelectorAll('.nav-item.dropdown .dropdown-toggle'));

  if (!triggers.length) {
    return;
  }

  const closeAll = (current = null) => {
    triggers.forEach(trigger => {
      if (current && trigger === current) {
        return;
      }

      const parent = trigger.closest('.dropdown');
      const menu = parent ? parent.querySelector('.dropdown-menu') : trigger.nextElementSibling;

      trigger.setAttribute('aria-expanded', 'false');
      if (parent && parent.classList) {
        parent.classList.remove('show');
      }
      if (menu && menu.classList) {
        menu.classList.remove('show');
      }

      if (typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
        const instance = bootstrap.Dropdown.getInstance(trigger);
        if (instance) {
          instance.hide();
        }
      }
    });
  };

  if (typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
    triggers.forEach(trigger => {
      const instance = bootstrap.Dropdown.getOrCreateInstance(trigger);

      trigger.addEventListener('show.bs.dropdown', () => {
        closeAll(trigger);
      });

      trigger.addEventListener('hide.bs.dropdown', () => {
        trigger.setAttribute('aria-expanded', 'false');
      });

      trigger.addEventListener('shown.bs.dropdown', () => {
        trigger.setAttribute('aria-expanded', 'true');
      });

      // Ensure the dropdown starts hidden in case bootstrap failed to initialise earlier
      instance.hide();
    });
  } else {
    // Manual fallback if Bootstrap's dropdown plugin is not available
    triggers.forEach(trigger => {
      trigger.addEventListener('click', event => {
        event.preventDefault();
        const parent = trigger.closest('.dropdown');
        const menu = parent ? parent.querySelector('.dropdown-menu') : trigger.nextElementSibling;
        const isOpen = (parent && parent.classList && parent.classList.contains('show')) ||
          (menu && menu.classList && menu.classList.contains('show'));

        closeAll();

        if (!isOpen) {
          if (parent && parent.classList) {
            parent.classList.add('show');
          }
          if (menu && menu.classList) {
            menu.classList.add('show');
          }
          trigger.setAttribute('aria-expanded', 'true');
        }
      });
    });

    document.addEventListener('click', event => {
      if (!event.target.closest('.nav-item.dropdown')) {
        closeAll();
      }
    });

    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        closeAll();
      }
    });
  }
});
