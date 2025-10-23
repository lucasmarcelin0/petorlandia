document.addEventListener('DOMContentLoaded', () => {
  const triggers = Array.from(document.querySelectorAll('.nav-item.dropdown .dropdown-toggle'));

  if (!triggers.length || typeof bootstrap === 'undefined' || !bootstrap.Dropdown) {
    return;
  }

  const closeOtherDropdowns = current => {
    triggers.forEach(trigger => {
      if (trigger === current) {
        return;
      }

      const instance = bootstrap.Dropdown.getInstance(trigger);
      if (instance) {
        instance.hide();
      }
    });
  };

  triggers.forEach(trigger => {
    bootstrap.Dropdown.getOrCreateInstance(trigger);

    trigger.addEventListener('show.bs.dropdown', () => {
      closeOtherDropdowns(trigger);
    });
  });
});
