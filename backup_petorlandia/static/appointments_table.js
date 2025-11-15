import { submitAppointmentUpdate } from './appointments_shared.js';

const EMPTY_STATE_HTML = `
  <div class="empty-state">
    <span class="icon-circle bg-secondary text-white"><i class="fa-regular fa-calendar-xmark"></i></span>
    <h3>Nenhum agendamento encontrado</h3>
    <p>Não há agendamentos para exibir no momento.</p>
  </div>
`;

const UPDATE_ERROR_MESSAGE = 'Erro ao salvar. Verifique os dados e tente novamente.';
const UPDATE_SUCCESS_MESSAGE = 'Agendamento atualizado com sucesso.';

function parseHTML(html) {
  if (!html) {
    return null;
  }
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

function findAppointmentsContainer(element) {
  if (!element) {
    return null;
  }
  return element.closest('[data-appointments-container]');
}

function ensureModalAlertContainer(modalBody) {
  if (!modalBody) {
    return null;
  }
  let container = modalBody.querySelector('.modal-feedback');
  if (!container) {
    container = document.createElement('div');
    container.className = 'modal-feedback';
    modalBody.prepend(container);
  }
  return container;
}

function clearModalAlerts(modalBody) {
  const container = ensureModalAlertContainer(modalBody);
  if (container) {
    container.innerHTML = '';
  }
}

function showModalAlert(modalBody, type, message) {
  const container = ensureModalAlertContainer(modalBody);
  if (!container) {
    return;
  }
  const alert = document.createElement('div');
  alert.className = `alert alert-${type} mt-2`;
  alert.textContent = message;
  container.innerHTML = '';
  container.appendChild(alert);
}

function removeEmptyState(container) {
  if (!container) {
    return;
  }
  container.querySelectorAll('.empty-state').forEach((el) => el.remove());
}

function insertBeforeTrailingScript(container, element) {
  if (!container || !element) {
    return;
  }
  const scriptSibling = Array.from(container.children).find((child) => child.tagName === 'SCRIPT');
  if (scriptSibling) {
    container.insertBefore(element, scriptSibling);
  } else {
    container.appendChild(element);
  }
}

function ensureEmptyState(container) {
  if (!container) {
    return;
  }
  const hasAppointments = container.querySelector('.appointments-day-block .appointment-card');
  const hasEmptyState = container.querySelector('.empty-state');
  if (!hasAppointments && !hasEmptyState) {
    const emptyStateEl = parseHTML(EMPTY_STATE_HTML);
    if (emptyStateEl) {
      insertBeforeTrailingScript(container, emptyStateEl);
    }
  }
}

function createDayBlock(day, dayLabel) {
  const wrapper = document.createElement('div');
  wrapper.className = 'appointments-day-block';
  wrapper.dataset.day = day;
  wrapper.dataset.dayLabel = dayLabel;
  wrapper.innerHTML = `
    <div class="day-header d-flex align-items-center gap-2" data-day="${day}" data-day-label="${dayLabel}">
      <span class="icon-circle bg-primary text-white"><i class="fa-solid fa-calendar-day"></i></span>
      ${dayLabel}
    </div>
    <div class="day-appointments"></div>
  `;
  return wrapper;
}

function insertDayBlock(container, block) {
  const day = block.dataset.day;
  const existingBlocks = Array.from(container.querySelectorAll('.appointments-day-block'));
  let inserted = false;
  for (const existing of existingBlocks) {
    if ((existing.dataset.day || '') > day) {
      container.insertBefore(block, existing);
      inserted = true;
      break;
    }
  }
  if (!inserted) {
    insertBeforeTrailingScript(container, block);
  }
  return block;
}

function insertAppointmentRow(container, row) {
  if (!container || !row) {
    return false;
  }
  const day = row.dataset.day;
  if (!day) {
    return false;
  }
  const dayLabel = row.dataset.dayLabel || day;
  removeEmptyState(container);

  let block = container.querySelector(`.appointments-day-block[data-day="${day}"]`);
  if (!block) {
    block = insertDayBlock(container, createDayBlock(day, dayLabel));
  }

  let appointmentsContainer = block.querySelector('.day-appointments');
  if (!appointmentsContainer) {
    appointmentsContainer = document.createElement('div');
    appointmentsContainer.className = 'day-appointments';
    block.appendChild(appointmentsContainer);
  }

  const siblings = Array.from(appointmentsContainer.querySelectorAll('.appointment-card'));
  const newTime = row.dataset.scheduled || '';
  const target = siblings.find((sibling) => {
    const siblingTime = sibling.dataset.scheduled || '';
    return siblingTime && siblingTime > newTime;
  });

  if (target) {
    appointmentsContainer.insertBefore(row, target);
  } else {
    appointmentsContainer.appendChild(row);
  }

  return true;
}

function updateAppointmentRow(existingRow, newRow) {
  if (!existingRow || !newRow) {
    return false;
  }
  const container = findAppointmentsContainer(existingRow);
  if (!container) {
    return false;
  }

  const oldBlock = existingRow.closest('.appointments-day-block');
  existingRow.remove();

  if (oldBlock) {
    const remaining = oldBlock.querySelector('.appointment-card');
    if (!remaining) {
      oldBlock.remove();
    }
  }

  const inserted = insertAppointmentRow(container, newRow);
  if (!inserted) {
    ensureEmptyState(container);
    return false;
  }

  bindAppointmentRowClicks();
  return true;
}

function applyFilterParams(parsedUrl) {
  if (!parsedUrl || !(parsedUrl instanceof URL)) {
    return;
  }
  const currentParams = new URLSearchParams(window.location.search);
  ['start', 'end'].forEach((param) => {
    if (currentParams.has(param)) {
      parsedUrl.searchParams.set(param, currentParams.get(param));
    } else {
      parsedUrl.searchParams.delete(param);
    }
  });
}

function buildPartialUrl(url) {
  try {
    const parsed = new URL(url, window.location.origin);
    applyFilterParams(parsed);
    parsed.searchParams.set('partial', 'appointments_table');
    return parsed.toString();
  } catch (error) {
    return url;
  }
}

async function refreshAppointmentsContainer(container) {
  if (!container) {
    return false;
  }
  let refreshUrl = container.dataset.refreshUrl || window.location.href;
  try {
    const parsedRefreshUrl = new URL(refreshUrl, window.location.origin);
    applyFilterParams(parsedRefreshUrl);
    refreshUrl = parsedRefreshUrl.toString();
    container.dataset.refreshUrl = refreshUrl;
  } catch (error) {
  }
  const targetUrl = buildPartialUrl(refreshUrl);
  try {
    const response = await fetch(targetUrl, {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-Partial': 'appointments_table'
      }
    });
    if (!response.ok) {
      return false;
    }
    const html = await response.text();
    container.innerHTML = html;
    bindAppointmentRowClicks();
    return true;
  } catch (error) {
    console.error('Erro ao atualizar lista de agendamentos', error);
    return false;
  }
}

function bindAppointmentRowClicks() {
  const modalEl = document.getElementById('appointmentEditModal');
  const modalBody = modalEl ? modalEl.querySelector('.modal-body') : null;
  const bsModal = modalEl ? bootstrap.Modal.getOrCreateInstance(modalEl) : null;

  document.querySelectorAll('.appointment-row').forEach((row) => {
    if (row.dataset.boundClick === 'true') {
      return;
    }
    row.dataset.boundClick = 'true';
    row.addEventListener('click', (event) => {
      if (event.target.closest('.btn')) {
        return;
      }
      const url = row.dataset.href;
      if (!url) {
        return;
      }
      if (modalEl && modalBody && bsModal) {
        bsModal.show();
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then((resp) => {
            if (!resp.ok) {
              throw new Error('Erro ao carregar formulário');
            }
            return resp.text();
          })
          .then((html) => {
            modalBody.innerHTML = html;
            clearModalAlerts(modalBody);
            const form = modalBody.querySelector('#edit-appointment-form');
            if (form) {
              attachAppointmentFormHandler(form, { url, row, modalBody, bsModal });
            }
          })
          .catch((error) => {
            console.error('Erro ao carregar o formulário de agendamento', error);
            showModalAlert(modalBody, 'danger', 'Não foi possível carregar o formulário. Tente novamente.');
          });
      } else {
        window.location = url;
      }
    });
  });
}

function attachAppointmentFormHandler(form, { url, row, modalBody, bsModal }) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearModalAlerts(modalBody);

    const payload = {
      date: form.querySelector('#edit-date')?.value,
      time: form.querySelector('#edit-time')?.value,
      veterinario_id: form.querySelector('#edit-vet')?.value
    };
    const notesField = form.querySelector('#edit-notes');
    if (notesField) {
      payload.notes = notesField.value;
    }
    const token = form.querySelector('#csrf_token')?.value || '';
    const submitButton = form.querySelector('[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
    }

    try {
      const result = await submitAppointmentUpdate(url, payload, token, {
        defaultErrorMessage: UPDATE_ERROR_MESSAGE,
        successMessage: UPDATE_SUCCESS_MESSAGE
      });

      if (!result.success || !result.data) {
        showModalAlert(modalBody, 'danger', result.message || UPDATE_ERROR_MESSAGE);
        return;
      }

      const data = result.data;
      showModalAlert(modalBody, 'success', result.message || UPDATE_SUCCESS_MESSAGE);

      let updated = false;
      if (data.card_html) {
        const newRow = parseHTML(data.card_html);
        if (newRow) {
          updated = updateAppointmentRow(row, newRow);
        }
      }
      if (!updated) {
        const container = findAppointmentsContainer(row);
        if (container) {
          updated = await refreshAppointmentsContainer(container);
        }
      }

      if (window.sharedCalendar && typeof window.sharedCalendar.refetchEvents === 'function') {
        try {
          window.sharedCalendar.refetchEvents();
        } catch (calendarError) {
          console.warn('Não foi possível atualizar o calendário compartilhado.', calendarError);
        }
      }

      setTimeout(() => {
        bsModal.hide();
      }, 1500);
    } catch (error) {
      console.error('Erro ao salvar agendamento', error);
      showModalAlert(modalBody, 'danger', 'Erro ao salvar. Tente novamente.');
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
      }
    }
  });
}

if (typeof window !== 'undefined') {
  window.bindAppointmentRowClicks = bindAppointmentRowClicks;
}

document.addEventListener('DOMContentLoaded', bindAppointmentRowClicks);

function activateAnimalTabs() {
  document.querySelectorAll('#animalTabs button[data-bs-toggle="tab"]').forEach(function (triggerEl) {
    triggerEl.addEventListener('click', function (e) {
      e.preventDefault();
      bootstrap.Tab.getOrCreateInstance(triggerEl).show();
    });
  });
}

document.addEventListener('DOMContentLoaded', activateAnimalTabs);
