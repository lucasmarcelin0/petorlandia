/**
 * Atualização parcial da agenda.
 *
 * A barra de filtros (período, atalhos e tipo) trocava a página inteira a cada
 * clique: o profissional perdia a aba aberta, a rolagem e os painéis expandidos.
 * Aqui o servidor devolve só o fragmento `#agenda-content` (HTML pronto, vindo
 * do mesmo template Jinja) e trocamos apenas essa parte do DOM.
 *
 * Todos os handlers usam delegação no documento, então continuam valendo depois
 * de cada troca — sem religar nada a cada resposta.
 */

const CONTENT_ID = 'agenda-content';
const PARTIAL_PARAM = 'partial';
const PARTIAL_VALUE = 'agenda';

let activeController = null;

function getContent() {
  return document.getElementById(CONTENT_ID);
}

function setBusy(busy) {
  const content = getContent();
  if (!content) return;
  content.setAttribute('aria-busy', busy ? 'true' : 'false');
  content.classList.toggle('agenda-content--loading', busy);
}

/** URL de navegação (sem o marcador de fragmento, para o histórico ficar limpo). */
function buildUrl(overrides = {}) {
  const url = new URL(window.location.href);
  Object.entries(overrides).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') {
      url.searchParams.delete(key);
    } else {
      url.searchParams.set(key, value);
    }
  });
  url.searchParams.delete(PARTIAL_PARAM);
  return url;
}

async function loadAgenda(url, { push = true } = {}) {
  const content = getContent();
  if (!content) {
    window.location.assign(url.toString());
    return;
  }

  if (activeController) {
    // Cliques rápidos em sequência: só a última resposta interessa.
    activeController.abort();
  }
  activeController = new AbortController();

  const fetchUrl = new URL(url.toString());
  fetchUrl.searchParams.set(PARTIAL_PARAM, PARTIAL_VALUE);

  setBusy(true);
  let html;
  try {
    const response = await fetch(fetchUrl.toString(), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      cache: 'no-store',
      signal: activeController.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    html = await response.text();
  } catch (error) {
    if (error.name === 'AbortError') return;
    // Falhou o caminho rápido: cai para a navegação normal em vez de deixar
    // o profissional olhando para uma agenda desatualizada.
    window.location.assign(url.toString());
    return;
  } finally {
    activeController = null;
    setBusy(false);
  }

  const holder = document.createElement('div');
  holder.innerHTML = html;
  const fresh = holder.querySelector(`#${CONTENT_ID}`) || holder.firstElementChild;
  if (!fresh) {
    window.location.assign(url.toString());
    return;
  }

  content.replaceWith(fresh);
  if (push) {
    window.history.pushState({ agenda: true }, '', url.toString());
  }
  document.dispatchEvent(new CustomEvent('agenda:updated', { detail: { url: url.toString() } }));
}

function currentFilterValues(form) {
  const values = {};
  if (!form) return values;
  const start = form.querySelector('input[name="start"]');
  const end = form.querySelector('input[name="end"]');
  const kind = form.querySelector('[data-agenda-kind-input]');
  if (start) values.start = start.value;
  if (end) values.end = end.value;
  if (kind) values.tipo = kind.value;
  return values;
}

export function setupAgendaAjax() {
  if (document.documentElement.dataset.agendaAjaxBound === 'true') {
    return;
  }
  document.documentElement.dataset.agendaAjaxBound = 'true';

  // Atalhos de período (Hoje / Amanhã / Semana / Mês)
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-agenda-range]');
    if (!button || !getContent()) return;
    event.preventDefault();
    loadAgenda(buildUrl({ start: button.dataset.start, end: button.dataset.end }));
  });

  // Filtro por tipo (Todos / Consultas / Exames / ...)
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-agenda-kind]');
    if (!button || !getContent()) return;
    event.preventDefault();
    loadAgenda(buildUrl({ tipo: button.dataset.agendaKind }));
  });

  // "Aplicar" com datas digitadas à mão
  document.addEventListener('submit', (event) => {
    const form = event.target.closest('#agenda-filter-form');
    if (!form || !getContent()) return;
    event.preventDefault();
    loadAgenda(buildUrl(currentFilterValues(form)));
  });

  // "Limpar" volta ao período padrão sem recarregar
  document.addEventListener('click', (event) => {
    const link = event.target.closest('#agenda-filter-form a[href]');
    if (!link || !getContent()) return;
    event.preventDefault();
    loadAgenda(new URL(link.href, window.location.origin));
  });

  // Aceitar/recusar exame: a rota responde JSON, então atualizamos o fragmento
  // em vez de deixar o JSON cru na tela.
  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-agenda-exam-action]');
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false) {
        window.alert(data.message || 'Não foi possível atualizar o exame.');
        if (button) button.disabled = false;
        return;
      }
      await loadAgenda(buildUrl(), { push: false });
    } catch (error) {
      window.alert('Não foi possível atualizar o exame.');
      if (button) button.disabled = false;
    }
  });

  // Mudar status de um agendamento (Confirmar / Falta / Cancelar) também
  // atualiza só a agenda — a rota redireciona, então pedimos JSON.
  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('form[action*="/status"]');
    if (!form || form.matches('[data-agenda-exam-action]') || !getContent()) return;
    if (!form.closest(`#${CONTENT_ID}`)) return;
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'same-origin',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false) {
        window.alert(data.message || 'Não foi possível atualizar o agendamento.');
        if (button) button.disabled = false;
        return;
      }
      await loadAgenda(buildUrl(), { push: false });
    } catch (error) {
      window.alert('Não foi possível atualizar o agendamento.');
      if (button) button.disabled = false;
    }
  });

  // Voltar/avançar do navegador continuam funcionando.
  window.addEventListener('popstate', () => {
    if (!getContent()) return;
    loadAgenda(new URL(window.location.href), { push: false });
  });
}

if (typeof window !== 'undefined') {
  window.setupAgendaAjax = setupAgendaAjax;
}
