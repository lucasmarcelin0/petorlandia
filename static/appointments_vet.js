import { fetchAvailableTimes, submitAppointmentUpdate } from './appointments_shared.js';

const ROOT_SELECTOR = '[data-vet-schedule-root]';
const DEFAULT_TIME_PLACEHOLDER = 'Selecione...';
const DEFAULT_SUCCESS_MESSAGE = 'Agendamento atualizado com sucesso.';

function getRootElement(root) {
  if (root instanceof HTMLElement) {
    return root;
  }
  if (typeof root === 'string') {
    return document.querySelector(root);
  }
  return document.querySelector(ROOT_SELECTOR);
}

function sanitizeBaseUrl(url) {
  if (!url) {
    return '';
  }
  return url.endsWith('/') ? url.slice(0, -1) : url;
}

function getAppointmentsBaseUrl(root) {
  const base = root?.dataset?.appointmentsBaseUrl || '/appointments';
  return sanitizeBaseUrl(base);
}

function getVetId(root) {
  return root?.dataset?.vetId || '';
}

function getCsrfToken(root) {
  if (root?.dataset?.csrfToken) {
    return root.dataset.csrfToken;
  }
  const tokenInput = document.querySelector('input[name="csrf_token"]');
  return tokenInput ? tokenInput.value : '';
}

function getModalInstance(element) {
  if (!element || typeof window === 'undefined') {
    return null;
  }
  const bootstrapGlobal = window.bootstrap;
  if (!bootstrapGlobal || typeof bootstrapGlobal.Modal?.getOrCreateInstance !== 'function') {
    return null;
  }
  return bootstrapGlobal.Modal.getOrCreateInstance(element);
}

function ensurePlaceholderOption(select, placeholder = DEFAULT_TIME_PLACEHOLDER) {
  if (!select) {
    return;
  }
  select.innerHTML = '';
  const option = document.createElement('option');
  option.value = '';
  option.textContent = placeholder;
  select.appendChild(option);
}

function isEvent(value) {
  return value && typeof value === 'object' && 'target' in value;
}

export function selectDays(mode, selectEl = document.getElementById('schedule-dias_semana')) {
  if (isEvent(mode)) {
    mode.preventDefault();
    return;
  }
  if (!selectEl) {
    return;
  }
  const weekdays = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta'];
  const weekend = ['Sábado', 'Domingo'];
  Array.from(selectEl.options).forEach((option) => {
    if (mode === 'all') {
      option.selected = true;
    } else if (mode === 'weekday') {
      option.selected = weekdays.includes(option.value);
    } else if (mode === 'weekend') {
      option.selected = weekend.includes(option.value);
    } else if (mode === 'clear') {
      option.selected = false;
    }
  });
  selectEl.dispatchEvent(new Event('change'));
}

export function toggleScheduleForm(rootParam) {
  if (isEvent(rootParam)) {
    rootParam.preventDefault();
  }
  const root = getRootElement(rootParam);
  const modalEl = document.getElementById('scheduleModal');
  const form = document.getElementById('schedule-form');
  const daysSelect = document.getElementById('schedule-dias_semana');
  const vetSelect = document.getElementById('schedule-veterinario_id');
  const titleEl = document.getElementById('scheduleModalTitle');
  const modal = getModalInstance(modalEl);
  if (!modal || !form) {
    return;
  }

  form.reset();
  form.action = getAppointmentsBaseUrl(root);

  if (daysSelect) {
    daysSelect.multiple = true;
  }

  const vetId = getVetId(root);
  if (vetSelect && vetId) {
    vetSelect.value = vetId;
  }

  if (titleEl) {
    titleEl.textContent = 'Adicionar Horário';
  }

  modal.show();
}

export function editSchedule(dataset, rootParam) {
  const root = getRootElement(rootParam);
  const modalEl = document.getElementById('scheduleModal');
  const modal = getModalInstance(modalEl);
  const form = document.getElementById('schedule-form');
  const titleEl = document.getElementById('scheduleModalTitle');
  const daysSelect = document.getElementById('schedule-dias_semana');
  const startField = document.getElementById('schedule-hora_inicio');
  const endField = document.getElementById('schedule-hora_fim');
  const intervalStart = document.getElementById('schedule-intervalo_inicio');
  const intervalEnd = document.getElementById('schedule-intervalo_fim');
  if (!modal || !form) {
    return;
  }

  form.reset();
  const scheduleId = dataset?.id;
  const vetId = getVetId(root);
  if (scheduleId) {
    const action = `${getAppointmentsBaseUrl(root)}/${vetId}/schedule/${scheduleId}/edit`;
    form.action = action;
  }

  if (titleEl) {
    titleEl.textContent = 'Editar Horário';
  }

  if (daysSelect) {
    daysSelect.multiple = false;
    const targetDay = dataset?.dia;
    Array.from(daysSelect.options).forEach((option) => {
      option.selected = option.value === targetDay;
    });
  }

  if (startField && dataset?.horaInicio) {
    startField.value = dataset.horaInicio;
  }
  if (endField && dataset?.horaFim) {
    endField.value = dataset.horaFim;
  }
  if (intervalStart) {
    intervalStart.value = dataset?.intervaloInicio || '';
  }
  if (intervalEnd) {
    intervalEnd.value = dataset?.intervaloFim || '';
  }

  modal.show();
}

export function toggleAppointmentForm(rootParam) {
  if (isEvent(rootParam)) {
    rootParam.preventDefault();
  }
  const root = getRootElement(rootParam);
  const modalEl = document.getElementById('appointmentModalForm');
  const modal = getModalInstance(modalEl);
  if (!modal) {
    return;
  }
  modal.show();
  updateAppointmentTimes({ root });
}

export async function updateAppointmentTimes(options = {}) {
  if (isEvent(options)) {
    const event = options;
    return updateAppointmentTimes({ dateInput: event.currentTarget || event.target });
  }
  const root = getRootElement(options.root);
  const dateInput = options.dateInput || document.getElementById('appointment-date');
  const timeSelect = options.timeSelect || document.getElementById('appointment-time');
  const placeholder = options.placeholder ?? DEFAULT_TIME_PLACEHOLDER;
  const vetId = options.veterinarianId || getVetId(root);

  if (!timeSelect) {
    return [];
  }

  ensurePlaceholderOption(timeSelect, placeholder);

  if (!dateInput || !vetId || !dateInput.value) {
    return [];
  }

  const times = await fetchAvailableTimes(vetId, dateInput.value, {
    kind: options.kind,
    searchParams: options.searchParams,
    fetchOptions: options.fetchOptions
  });

  if (!Array.isArray(times) || times.length === 0) {
    return [];
  }

  const fragment = document.createDocumentFragment();
  times.forEach((time) => {
    const option = document.createElement('option');
    option.value = time;
    option.textContent = time;
    fragment.appendChild(option);
  });
  timeSelect.appendChild(fragment);
  return times;
}

export function toggleScheduleEdit(rootParam) {
  if (isEvent(rootParam)) {
    rootParam.preventDefault();
  }
  const root = getRootElement(rootParam);
  if (!root) {
    return;
  }
  const actionContainers = root.querySelectorAll('.schedule-actions');
  if (!actionContainers.length) {
    return;
  }
  actionContainers.forEach((container) => container.classList.toggle('d-none'));
  const anyVisible = Array.from(actionContainers).some((container) => !container.classList.contains('d-none'));
  const toggleButton = root.querySelector('[data-schedule-edit-toggle]');
  if (toggleButton) {
    toggleButton.innerHTML = anyVisible
      ? '<i class="fas fa-times me-1"></i>Cancelar Edição'
      : '<i class="fas fa-edit me-1"></i>Editar horários';
  }
}

export async function responderAgendamentoExame(appointmentId, status) {
  if (!appointmentId || !status) {
    return;
  }
  try {
    const response = await fetch(`/exam_appointment/${appointmentId}/status`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json'
      },
      body: JSON.stringify({ status })
    });
    if (!response.ok) {
      throw new Error('Falha ao atualizar agendamento de exame.');
    }
    const data = await response.json();
    if (data?.success) {
      window.location.reload();
    } else {
      alert(data?.message || 'Erro ao atualizar status.');
    }
  } catch (error) {
    console.error('Erro ao atualizar status do exame', error);
    alert('Erro ao atualizar status.');
  }
}

function bindScheduleEditButtons(root) {
  root.querySelectorAll('.edit-btn').forEach((button) => {
    if (button.dataset.vetScheduleBound === 'true') {
      return;
    }
    button.dataset.vetScheduleBound = 'true';
    button.addEventListener('click', (event) => {
      event.preventDefault();
      editSchedule(button.dataset, root);
    });
  });
}

function bindAppointmentItems(root) {
  const modalEl = document.getElementById('appointmentDetailModal');
  const modal = getModalInstance(modalEl);
  root.querySelectorAll('.appointment-item').forEach((item) => {
    if (item.dataset.vetScheduleBound === 'true') {
      return;
    }
    item.dataset.vetScheduleBound = 'true';
    item.addEventListener('click', (event) => {
      if (event.target.closest('.btn')) {
        return;
      }
      const appointmentId = item.dataset.id;
      if (!appointmentId) {
        return;
      }
      const vetField = document.getElementById('modal-vet');
      const tutorField = document.getElementById('modal-tutor');
      const animalField = document.getElementById('modal-animal');
      const dateField = document.getElementById('modal-date');
      const timeField = document.getElementById('modal-time');
      const notesField = document.getElementById('modal-notes');
      const animalLink = document.getElementById('modal-animal-link');
      const tutorLink = document.getElementById('modal-tutor-link');
      const consultaLink = document.getElementById('modal-consulta-link');
      const idField = document.getElementById('modal-appt-id');

      if (idField) {
        idField.value = appointmentId;
      }
      if (vetField) {
        vetField.value = item.dataset.vet || '';
      }
      if (tutorField) {
        tutorField.value = item.dataset.tutor || '';
      }
      if (animalField) {
        animalField.value = item.dataset.animal || '';
      }
      if (dateField) {
        dateField.value = item.dataset.date || '';
      }
      if (timeField) {
        timeField.value = item.dataset.time || '';
      }
      if (notesField) {
        notesField.value = item.dataset.notes || '';
      }
      if (animalLink && item.dataset.animalUrl) {
        animalLink.href = item.dataset.animalUrl;
      }
      if (tutorLink && item.dataset.tutorUrl) {
        tutorLink.href = item.dataset.tutorUrl;
      }
      if (consultaLink && item.dataset.consultaUrl) {
        consultaLink.href = item.dataset.consultaUrl;
      }

      if (modal) {
        modal.show();
      }
    });
  });
}

function bindAppointmentModalSave(root) {
  const saveButton = document.getElementById('modal-save-btn');
  if (!saveButton || saveButton.dataset.vetScheduleBound === 'true') {
    return;
  }
  saveButton.dataset.vetScheduleBound = 'true';
  saveButton.addEventListener('click', async () => {
    const idField = document.getElementById('modal-appt-id');
    const dateField = document.getElementById('modal-date');
    const timeField = document.getElementById('modal-time');
    const notesField = document.getElementById('modal-notes');
    const appointmentId = idField?.value;
    if (!appointmentId) {
      return;
    }
    const updateUrl = `${getAppointmentsBaseUrl(root)}/${appointmentId}/edit`;
    const payload = {
      date: dateField?.value || '',
      time: timeField?.value || '',
      veterinario_id: getVetId(root),
      notes: notesField?.value || ''
    };
    const result = await submitAppointmentUpdate(updateUrl, payload, getCsrfToken(root), {
      successMessage: DEFAULT_SUCCESS_MESSAGE
    });
    if (result.success) {
      window.location.reload();
    } else {
      alert(result.message || 'Erro ao salvar');
    }
  });
}

function bindAppointmentDateWatcher(root) {
  const dateInput = document.getElementById('appointment-date');
  if (!dateInput || dateInput.dataset.vetScheduleBound === 'true') {
    return;
  }
  dateInput.dataset.vetScheduleBound = 'true';
  dateInput.addEventListener('change', (event) => updateAppointmentTimes({ root, dateInput: event.currentTarget || event.target }));
}

function bindPastToggle(root) {
  const toggleButton = document.getElementById('toggle-past');
  const pastList = document.getElementById('past-list');
  if (!toggleButton || !pastList || toggleButton.dataset.vetScheduleBound === 'true') {
    return;
  }
  toggleButton.dataset.vetScheduleBound = 'true';
  toggleButton.addEventListener('click', () => {
    pastList.classList.toggle('d-none');
    const isHidden = pastList.classList.contains('d-none');
    toggleButton.innerHTML = isHidden
      ? '<i class="fas fa-chevron-down me-1"></i>Mostrar'
      : '<i class="fas fa-chevron-up me-1"></i>Ocultar';
  });
}

function animateCards(root) {
  const cards = root.querySelectorAll('.card');
  cards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    setTimeout(() => {
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, 100 + (index * 100));
  });
}

export function initVetSchedulePage(options = {}) {
  const root = getRootElement(options.root);
  if (!root || root.dataset.vetScheduleInitialized === 'true') {
    return root;
  }
  root.dataset.vetScheduleInitialized = 'true';

  bindScheduleEditButtons(root);
  bindAppointmentItems(root);
  bindAppointmentModalSave(root);
  bindAppointmentDateWatcher(root);
  bindPastToggle(root);
  animateCards(root);

  const dateInput = document.getElementById('appointment-date');
  if (dateInput && dateInput.value) {
    updateAppointmentTimes({ root, dateInput });
  }

  return root;
}

if (typeof window !== 'undefined') {
  window.selectDays = (mode) => selectDays(mode);
  window.toggleScheduleForm = (root) => toggleScheduleForm(root);
  window.toggleAppointmentForm = (root) => toggleAppointmentForm(root);
  window.updateAppointmentTimes = (options) => updateAppointmentTimes(options);
  window.toggleScheduleEdit = (root) => toggleScheduleEdit(root);
  window.responderAgendamentoExame = responderAgendamentoExame;
  window.initVetSchedulePage = (options) => initVetSchedulePage(options);
}

document.addEventListener('DOMContentLoaded', () => {
  initVetSchedulePage();
});

export default {
  selectDays,
  toggleScheduleForm,
  editSchedule,
  toggleAppointmentForm,
  updateAppointmentTimes,
  toggleScheduleEdit,
  responderAgendamentoExame,
  initVetSchedulePage
};
