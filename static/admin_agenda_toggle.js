/**
 * Alternância do modo multi-agendas para administradores (Easter Egg no ícone da agenda).
 * Permite ativar ou desativar o carregamento de outras agendas sob demanda.
 */

export function initAdminAgendaToggle() {
  const toggles = document.querySelectorAll('[data-admin-other-agendas-toggle]');
  if (!toggles.length) {
    return;
  }

  async function handleToggle(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    const toggleEl = event.currentTarget || document.querySelector('[data-admin-other-agendas-toggle]');
    const isCurrentlyActive = toggleEl && toggleEl.getAttribute('data-active') === 'true';
    const newActive = !isCurrentlyActive;

    // Atualiza cookie imediatamente
    if (newActive) {
      document.cookie = 'admin_other_agendas=1; path=/; max-age=86400; SameSite=Lax';
    } else {
      document.cookie = 'admin_other_agendas=0; path=/; max-age=0; SameSite=Lax';
    }

    // Tenta chamada assíncrona ao backend
    try {
      const csrfMeta = document.querySelector('meta[name="csrf-token"]') || document.querySelector('[data-csrf-token]');
      const csrfToken = csrfMeta ? (csrfMeta.content || csrfMeta.dataset.csrfToken) : '';
      await fetch('/api/admin/toggle_other_agendas', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken || '',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ active: newActive }),
      });
    } catch (error) {
      console.debug('Erro na chamada assíncrona de toggle:', error);
    }

    // Notificação visual Toast
    const toastMessage = newActive
      ? 'Modo multi-agendas ativado! 🔓 Carregando agendas...'
      : 'Modo agenda pessoal ativado! 🔒 Retornando à sua agenda...';
    if (typeof window.showToastMessage === 'function') {
      window.showToastMessage(toastMessage, newActive ? 'success' : 'info');
    }

    // Redirecionamento limpo
    const url = new URL(window.location.href);
    url.searchParams.set('other_agendas', newActive ? '1' : '0');
    if (!newActive) {
      url.searchParams.delete('colaborador_id');
      url.searchParams.delete('veterinario_id');
      url.searchParams.delete('view_as');
    }
    setTimeout(() => {
      window.location.href = url.toString();
    }, 200);
  }

  toggles.forEach((toggle) => {
    toggle.removeEventListener('click', handleToggle);
    toggle.addEventListener('click', handleToggle);
    toggle.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleToggle(e);
      }
    });
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAdminAgendaToggle);
} else {
  initAdminAgendaToggle();
}
