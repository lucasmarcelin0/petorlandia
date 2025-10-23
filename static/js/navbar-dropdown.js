document.addEventListener('DOMContentLoaded', () => {
  const triggers = Array.from(document.querySelectorAll('.nav-item.dropdown .dropdown-toggle'));

  const closeAllDropdowns = () => {
    triggers.forEach(trigger => {
      const instance = bootstrap.Dropdown.getInstance(trigger);
      if (instance) {
        instance.hide();
      }
    });
  };

  triggers.forEach(trigger => {
    trigger.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();

      const instance = bootstrap.Dropdown.getOrCreateInstance(trigger);
      const isExpanded = trigger.getAttribute('aria-expanded') === 'true';

      closeAllDropdowns();

      if (!isExpanded) {
        instance.show();
      }
    });
  });

  document.addEventListener('click', event => {
    if (!event.target.closest('.nav-item.dropdown')) {
      closeAllDropdowns();
    }
  });
});
