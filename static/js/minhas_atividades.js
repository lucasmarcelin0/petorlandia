(() => {
  'use strict';

  const navigation = document.querySelector('[data-activities-navigation]');
  if (!navigation || navigation.dataset.ajaxReady === 'true') return;
  navigation.dataset.ajaxReady = 'true';

  const status = navigation.querySelector('[data-activities-status]');
  let controller = null;

  const contentPanel = () => document.querySelector('[data-activities-content]');

  function setLoading(loading) {
    const panel = contentPanel();
    navigation.querySelectorAll('[data-activities-tab]').forEach((tab) => {
      tab.classList.toggle('disabled', loading);
      tab.setAttribute('aria-disabled', loading ? 'true' : 'false');
    });
    status?.classList.toggle('d-none', !loading);
    if (panel) {
      panel.setAttribute('aria-busy', loading ? 'true' : 'false');
      panel.style.opacity = loading ? '0.55' : '';
    }
  }

  function updateActiveTab(url) {
    const target = new URL(url, window.location.href);
    navigation.querySelectorAll('[data-activities-tab]').forEach((tab) => {
      const active = new URL(tab.href, window.location.href).pathname === target.pathname;
      tab.classList.toggle('active', active);
      tab.classList.toggle('bg-white', !active);
      tab.classList.toggle('border', !active);
      tab.classList.toggle('text-body', !active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) tab.setAttribute('aria-current', 'page');
      else tab.removeAttribute('aria-current');
    });
  }

  async function loadActivity(url, { push = true, focus = true } = {}) {
    controller?.abort();
    controller = new AbortController();
    setLoading(true);

    try {
      const response = await fetch(url, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const html = await response.text();
      const page = new DOMParser().parseFromString(html, 'text/html');
      const nextPanel = page.querySelector('[data-activities-content]');
      const panel = contentPanel();
      if (!nextPanel || !panel) throw new Error('Painel de atividades ausente');

      panel.replaceWith(nextPanel);
      updateActiveTab(response.url || url);
      if (push) history.pushState({ activitiesAjax: true }, '', response.url || url);
      if (page.title) document.title = page.title;
      if (focus) nextPanel.focus({ preventScroll: true });
    } catch (error) {
      if (error.name === 'AbortError') return;
      window.location.assign(url);
    } finally {
      setLoading(false);
    }
  }

  navigation.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-activities-tab]');
    if (!tab || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    loadActivity(tab.href);
  });

  window.addEventListener('popstate', () => {
    loadActivity(window.location.href, { push: false, focus: false });
  });
})();
