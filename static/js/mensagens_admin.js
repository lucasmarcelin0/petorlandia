const HIDDEN_CLASS = 'd-none';

function parseHTML(html) {
  if (!html) {
    return [];
  }
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  return Array.from(template.content.children);
}

function toggleLoading(element, show) {
  if (!element) {
    return;
  }
  element.classList.toggle(HIDDEN_CLASS, !show);
}

function updateEmptyState(section) {
  if (!section.empty || !section.list) {
    return;
  }
  const hasItems = section.list.children.length > 0;
  section.empty.classList.toggle(HIDDEN_CLASS, hasItems);
}

function updateLoadMore(section) {
  if (!section.loadMore) {
    return;
  }
  if (section.nextPage) {
    section.loadMore.classList.remove(HIDDEN_CLASS);
    section.loadMore.disabled = false;
  } else {
    section.loadMore.classList.add(HIDDEN_CLASS);
    section.loadMore.disabled = true;
  }
}

function createSection(element) {
  return {
    element,
    kind: element.dataset.threadKind,
    list: element.querySelector('[data-list]'),
    empty: element.querySelector('[data-empty]'),
    loadMore: element.querySelector('[data-load-more]'),
    loadingIndicator: element.querySelector('[data-loading]'),
    nextPage: element.dataset.nextPage ? parseInt(element.dataset.nextPage, 10) : null,
    isLoading: false,
  };
}

function initAdminMessages() {
  const root = document.querySelector('[data-admin-messages]');
  if (!root) {
    return;
  }

  const fetchUrl = root.dataset.fetchUrl;
  const pollInterval = parseInt(root.dataset.pollInterval || '0', 10);
  const perPage = parseInt(root.dataset.perPage || '10', 10);
  const sections = Array.from(root.querySelectorAll('[data-thread-kind]')).map(createSection);

  async function fetchThreads(section, { page = 1, append = false } = {}) {
    if (!fetchUrl || section.isLoading) {
      return { success: false };
    }
    section.isLoading = true;
    toggleLoading(section.loadingIndicator, true);
    const url = new URL(fetchUrl, window.location.origin);
    url.searchParams.set('kind', section.kind);
    url.searchParams.set('page', page);
    url.searchParams.set('per_page', perPage);

    try {
      const response = await fetch(url.toString(), {
        headers: {
          Accept: 'application/json',
        },
      });
      if (!response.ok) {
        throw new Error('Erro ao carregar as conversas.');
      }
      const data = await response.json();
      if (!data.success) {
        throw new Error(data.message || 'Erro ao carregar as conversas.');
      }
      if (!append && section.list) {
        section.list.innerHTML = '';
      }
      if (section.list && data.html) {
        parseHTML(data.html).forEach((item) => section.list.appendChild(item));
      }
      section.nextPage = data.next_page || null;
      section.element.dataset.nextPage = section.nextPage ? String(section.nextPage) : '';
      updateLoadMore(section);
      updateEmptyState(section);
      return { success: true };
    } catch (error) {
      if (section.list && !append) {
        section.list.innerHTML = `<li class="list-group-item text-danger">${error.message}</li>`;
      }
      throw error;
    } finally {
      section.isLoading = false;
      toggleLoading(section.loadingIndicator, false);
    }
  }

    sections.forEach((section) => {
      updateLoadMore(section);
      updateEmptyState(section);
      if (section.loadMore) {
        section.loadMore.addEventListener('click', () => {
          if (!section.nextPage) return;

          const run = () => fetchThreads(section, { page: section.nextPage, append: true });

          if (window.FormFeedback?.runActionWithFeedback) {
            window.FormFeedback.runActionWithFeedback(section.loadMore, run, {
              loadingText: 'Carregando...',
              successDelay: 700,
              errorMessage: 'Erro ao carregar as conversas.',
            }).catch(() => {});
          } else {
            run();
          }
        });
      }
    });

  if (pollInterval > 0) {
    window.setInterval(() => {
      sections.forEach((section) => {
        fetchThreads(section, { page: 1, append: false });
      });
    }, pollInterval);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAdminMessages);
} else {
  initAdminMessages();
}
