(() => {
  const tabs = [...document.querySelectorAll('[data-profile]')];
  const content = document.getElementById('unified-profile-content');
  const status = document.getElementById('unified-profile-status');
  if (!tabs.length || !content) return;
  let controller;
  let sequence = 0;

  tabs.forEach((tab, index) => {
    tab.addEventListener('keydown', (event) => {
      let target;
      if (event.key === 'ArrowRight') target = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') target = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = tabs.length - 1;
      if (target === undefined) return;
      event.preventDefault();
      tabs[target].focus();
      tabs[target].click();
    });
    tab.addEventListener('click', async (event) => {
      if (!window.fetch || !window.AbortController || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const requestId = ++sequence;
      if (controller) controller.abort();
      controller = new AbortController();
      content.setAttribute('aria-busy', 'true');
      status.textContent = 'Carregando...';
      try {
        const response = await fetch(tab.dataset.profileUrl, {signal: controller.signal, headers: {Accept: 'text/html'}});
        if (!response.ok) throw new Error('profile_failed');
        const html = await response.text();
        if (requestId !== sequence) return;
        content.innerHTML = html;
        const panel = content.querySelector('[data-profile-panel]');
        if (!panel) throw new Error('profile_missing');
        tabs.forEach((item) => {
          const active = item === tab;
          item.classList.toggle('is-active', active);
          item.setAttribute('aria-selected', String(active));
          item.tabIndex = active ? 0 : -1;
        });
        content.setAttribute('aria-labelledby', tab.id);
        document.querySelector('[data-profile-description]').textContent = panel.dataset.description;
        document.querySelector('[data-profile-reassurance]').textContent = panel.dataset.reassurance;
        document.querySelectorAll('[data-profile-primary]').forEach((link) => {
          link.href = panel.dataset.primaryUrl;
          link.querySelector('span').textContent = panel.dataset.primaryLabel;
          link.dataset.cta = 'home_' + tab.dataset.profile + '_primary';
        });
        window.history.replaceState({}, '', tab.href);
        status.textContent = 'Perfil atualizado.';
      } catch (error) {
        if (error.name !== 'AbortError' && requestId === sequence) window.location.assign(tab.href);
      } finally {
        if (requestId === sequence) content.removeAttribute('aria-busy');
      }
    });
  });
})();
