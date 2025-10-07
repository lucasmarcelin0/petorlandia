import { fetchAvailableTimes, submitAppointmentUpdate } from './appointments_shared.js';
import { setupAppointmentsCalendarSummary } from './appointments_calendar_summary.js';

const ROOT_SELECTOR = '[data-vet-schedule-root]';
const DEFAULT_TIME_PLACEHOLDER = 'Selecione...';
const DEFAULT_SUCCESS_MESSAGE = 'Agendamento atualizado com sucesso.';

const EXAM_REQUESTER_ROW_SELECTOR = '[data-exam-requester-row]';
const EXAM_REQUESTER_MODAL_ID = 'examRequesterModal';

const TYPE_LABELS = {
  consulta: 'Consulta',
  retorno: 'Retorno',
  banho_tosa: 'Banho e Tosa',
  vacina: 'Vacina'
};

const STATUS_LABELS = {
  scheduled: 'A fazer',
  completed: 'Realizada',
  canceled: 'Cancelada',
  accepted: 'Aceita'
};

function parseLocalDateTime(value) {
  if (!value) {
    return null;
  }
  const [datePart, timePart] = value.split('T');
  if (!datePart || !timePart) {
    return null;
  }
  const [year, month, day] = datePart.split('-').map((part) => Number.parseInt(part, 10));
  const [hour, minute] = timePart.split(':').map((part) => Number.parseInt(part, 10));
  if ([year, month, day, hour, minute].some((num) => Number.isNaN(num))) {
    return null;
  }
  return new Date(year, month - 1, day, hour, minute);
}

function formatLocalDateTimeInput(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
    return '';
  }
  const pad = (value) => value.toString().padStart(2, '0');
  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function formatDateTimeForDisplay(value) {
  const date = value instanceof Date ? value : parseLocalDateTime(value);
  if (!date) {
    return '';
  }
  try {
    return new Intl.DateTimeFormat('pt-BR', {
      dateStyle: 'short',
      timeStyle: 'short'
    }).format(date);
  } catch (error) {
    return date.toLocaleString('pt-BR');
  }
}

function getExamDefaultConfirmHours(root) {
  const resolvedRoot = getRootElement(root);
  const raw = resolvedRoot?.dataset?.examDefaultConfirmHours;
  if (raw === undefined) {
    return null;
  }
  const hours = Number.parseFloat(raw);
  return Number.isFinite(hours) && hours > 0 ? hours : null;
}

function formatHoursText(hours) {
  if (!Number.isFinite(hours)) {
    return '';
  }
  const formatter = new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: Number.isInteger(hours) ? 0 : 1,
    maximumFractionDigits: Number.isInteger(hours) ? 0 : 2
  });
  const formatted = formatter.format(hours);
  const plural = Math.abs(hours - 1) < 1e-9 ? 'hora' : 'horas';
  return `${formatted} ${plural}`;
}

function computeExamDefaultConfirmValue({ root, row }) {
  const defaultHours = getExamDefaultConfirmHours(root);
  if (!defaultHours) {
    return '';
  }
  const requestedAt = row?.dataset?.examRequestedAt
    ? parseLocalDateTime(row.dataset.examRequestedAt)
    : null;
  const scheduledAt = row?.dataset?.examScheduled
    ? parseLocalDateTime(row.dataset.examScheduled)
    : null;
  const reference = requestedAt || scheduledAt || new Date();
  if (!reference) {
    return '';
  }
  const defaultMillis = reference.getTime() + defaultHours * 60 * 60 * 1000;
  return formatLocalDateTimeInput(new Date(defaultMillis));
}

function updateExamRequesterDefaultPreview({ defaultValue, modalEl, row }) {
  const previewEl = document.getElementById('exam-requester-default-preview');
  if (!previewEl) {
    return;
  }
  const requestDisplay = row?.dataset?.examRequestedAtDisplay || modalEl?.dataset?.examRequestedAtDisplay || '';
  const parts = [];
  if (requestDisplay) {
    parts.push(`Solicitação registrada em ${requestDisplay}.`);
  }
  if (defaultValue) {
    const formatted = formatDateTimeForDisplay(defaultValue);
    if (formatted) {
      parts.push(`Prazo sugerido: ${formatted}.`);
    }
  }
  previewEl.textContent = parts.join(' ');
}

function humanizeLabel(value) {
  if (!value && value !== 0) {
    return '';
  }
  return value
    .toString()
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function getTypeLabel(type) {
  if (!type && type !== 0) {
    return '';
  }
  const normalized = type.toString().trim().toLowerCase();
  return TYPE_LABELS[normalized] || humanizeLabel(normalized);
}

function getStatusLabel(status) {
  if (!status && status !== 0) {
    return '';
  }
  const normalized = status.toString().trim().toLowerCase();
  return STATUS_LABELS[normalized] || humanizeLabel(normalized);
}

function formatDateToBrazil(value) {
  if (!value) {
    return '';
  }
  const [year, month, day] = value.split('-');
  if (!year || !month || !day) {
    return value;
  }
  return `${day}/${month}/${year}`;
}

function updateTextContent(element, value, fallback = '—') {
  if (!element) {
    return;
  }
  const hasValue = value && value.toString().trim().length > 0;
  element.textContent = hasValue ? value : fallback;
}

function updateModalTypePill(element, type, label) {
  if (!element) {
    return;
  }
  const normalizedType = (type || '').toString().trim().toLowerCase();
  const displayLabel = label || getTypeLabel(normalizedType) || 'Consulta';
  element.className = 'appointment-modal-pill';
  element.hidden = false;
  if (normalizedType) {
    element.classList.add(`appointment-modal-pill--${normalizedType}`);
  }
  updateTextContent(element, displayLabel, 'Consulta');
}

function updateModalStatusBadge(element, status, label) {
  if (!element) {
    return;
  }
  const normalizedStatus = (status || '').toString().trim().toLowerCase();
  const displayLabel = label || getStatusLabel(normalizedStatus) || '';
  if (!displayLabel && !normalizedStatus) {
    element.className = 'status-badge';
    element.textContent = '';
    element.hidden = true;
    return;
  }
  element.hidden = false;
  element.className = 'status-badge';
  if (normalizedStatus) {
    element.classList.add(`status-${normalizedStatus}`);
  }
  updateTextContent(element, displayLabel, '');
}

function updateModalNotesPreview(container, textElement, notes) {
  if (!container || !textElement) {
    return;
  }
  const hasNotes = notes && notes.toString().trim().length > 0;
  if (hasNotes) {
    container.hidden = false;
    textElement.textContent = notes;
  } else {
    container.hidden = true;
    textElement.textContent = '';
  }
}

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

function getModalElementById(id) {
  if (!id) {
    return { element: null, modal: null };
  }
  const element = document.getElementById(id);
  const modal = getModalInstance(element);
  return { element, modal };
}

function getCollapseController(element) {
  const bootstrapGlobal = window?.bootstrap;
  if (!element || !bootstrapGlobal?.Collapse) {
    return null;
  }
  return bootstrapGlobal.Collapse.getOrCreateInstance(element, { toggle: false });
}

function showCollapseElement(element) {
  if (!element) {
    return;
  }
  const controller = getCollapseController(element);
  if (controller) {
    controller.show();
    return;
  }
  element.classList.add('show');
  element.style.height = 'auto';
  element.removeAttribute('aria-hidden');
}

function hideCollapseElement(element) {
  if (!element) {
    return;
  }
  const controller = getCollapseController(element);
  if (controller) {
    controller.hide();
    return;
  }
  element.classList.remove('show');
  element.setAttribute('aria-hidden', 'true');
  element.style.height = '0px';
}

function updateCollapseToggleState(button, expanded) {
  if (!button) {
    return;
  }
  if (expanded) {
    button.classList.remove('collapsed');
  } else {
    button.classList.add('collapsed');
  }
  button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
}

function focusFirstField(container) {
  if (!container) {
    return;
  }
  const focusTarget = container.querySelector('input, select, textarea');
  if (!focusTarget) {
    return;
  }
  window.setTimeout(() => {
    try {
      focusTarget.focus({ preventScroll: false });
    } catch (error) {
      focusTarget.focus();
    }
  }, 150);
}

function scrollIntoViewSmooth(element) {
  if (!element) {
    return;
  }
  window.setTimeout(() => {
    try {
      element.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' });
    } catch (error) {
      const rect = element.getBoundingClientRect();
      const absoluteTop = rect.top + window.pageYOffset;
      window.scrollTo({ top: Math.max(absoluteTop - 24, 0), behavior: 'smooth' });
    }
  }, 200);
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

function bindScheduleModalButton(root) {
  const scheduleButton = document.getElementById('openScheduleModal');
  if (!scheduleButton || scheduleButton.dataset.vetScheduleBound === 'bound') {
    return;
  }
  scheduleButton.dataset.vetScheduleBound = 'bound';
  scheduleButton.addEventListener('click', (event) => {
    event.preventDefault();
    toggleScheduleForm(root);
  });
}

async function populateAppointmentModalTimes({
  root,
  vetId,
  kind,
  dateField,
  timeSelect,
  currentTime
} = {}) {
  if (!timeSelect) {
    return [];
  }

  const placeholderText = timeSelect?.dataset?.placeholder || DEFAULT_TIME_PLACEHOLDER;
  const timeDisplay = document.getElementById('modal-time-display');
  const setDisplay = (value) => {
    if (!timeDisplay) {
      return;
    }
    updateTextContent(timeDisplay, value || '', '--:--');
  };
  const hasDateValue = Boolean(dateField?.value);
  const times = await updateAppointmentTimes({
    root,
    dateInput: dateField,
    timeSelect,
    veterinarianId: vetId,
    kind,
    placeholder: placeholderText
  });

  const placeholderOption = timeSelect.querySelector('option[value=""]');
  if (!hasDateValue) {
    if (placeholderOption) {
      placeholderOption.textContent = placeholderText;
      placeholderOption.selected = true;
    }
    setDisplay('');
    return times;
  }

  if (!Array.isArray(times) || times.length === 0) {
    if (placeholderOption) {
      placeholderOption.textContent = 'Nenhum horário disponível';
      placeholderOption.selected = true;
    }
    setDisplay('');
  } else if (placeholderOption) {
    placeholderOption.textContent = placeholderText;
  }

  const normalizedCurrent = (currentTime || '').trim();
  if (!normalizedCurrent) {
    setDisplay(timeSelect.value || '');
    return times;
  }

  const existingOption = Array
    .from(timeSelect.options || [])
    .find((option) => option.value === normalizedCurrent);
  if (existingOption) {
    existingOption.selected = true;
    setDisplay(existingOption.value);
    return times;
  }

  const fallbackOption = document.createElement('option');
  fallbackOption.value = normalizedCurrent;
  fallbackOption.textContent = `${normalizedCurrent} (atual)`;
  fallbackOption.selected = true;
  timeSelect.appendChild(fallbackOption);
  setDisplay(normalizedCurrent);
  return times;
}

function initScheduleOverview(root) {
  const scheduleContainer = document.getElementById('schedule-overview');
  if (!scheduleContainer) {
    return;
  }

  const dateField = document.getElementById('appointment-date');
  const timeSelect = document.getElementById('appointment-time');
  const summaryBadge = document.querySelector('[data-schedule-summary]');
  const weekLabel = document.querySelector('[data-schedule-week-label]');
  const periodFilter = document.querySelector('[data-schedule-period-filter]');
  const collapseEl = document.getElementById('scheduleOverviewCollapse');
  const toggleBtn = document.querySelector('[data-bs-target="#scheduleOverviewCollapse"]');
  const prevBtn = document.querySelector('[data-schedule-week-prev]');
  const nextBtn = document.querySelector('[data-schedule-week-next]');
  const todayBtn = document.querySelector('[data-schedule-week-today]');
  const scheduleTitleEl = document.querySelector('[data-schedule-title]');
  const scheduleTitleVetNameEl = scheduleTitleEl
    ? scheduleTitleEl.querySelector('[data-schedule-vet-name]')
    : document.querySelector('[data-schedule-vet-name]');
  const vetSelectElements = Array.from(document.querySelectorAll('[data-schedule-vet-select]'));
  const initialRootVetId = getVetId(root);

  const shortFormatter = new Intl.DateTimeFormat('pt-BR', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit'
  });
  const longFormatter = new Intl.DateTimeFormat('pt-BR', {
    weekday: 'long',
    day: '2-digit',
    month: 'long'
  });

  const state = {
    vetId: (initialRootVetId || '').trim(),
    period: (periodFilter && periodFilter.value) || 'all',
    currentStart: '',
    days: [],
    selectedSlotKey: '',
    todayIso: new Date().toISOString().split('T')[0]
  };

  function resolveInitialVetId() {
    const datasetId = (root?.dataset?.vetId || '').trim();
    if (datasetId) {
      return datasetId;
    }
    for (const select of vetSelectElements) {
      if (!select) {
        continue;
      }
      const selectValue = (select.value || '').trim();
      if (selectValue) {
        return selectValue;
      }
      const selectedOption = Array.from(select.options || []).find(
        (option) => option.selected && option.value
      );
      if (selectedOption) {
        return (selectedOption.value || '').trim();
      }
    }
    return '';
  }

  if (dateField && timeSelect) {
    const initialTime = (timeSelect.dataset?.currentTime || timeSelect.value || '').trim();
    if (dateField.value && initialTime) {
      state.selectedSlotKey = `${dateField.value}T${initialTime}`;
    }
  }

  if (!state.vetId) {
    state.vetId = resolveInitialVetId();
  }
  if (root) {
    root.dataset.vetId = state.vetId || '';
  }

  function findVetLabelById(value) {
    const normalized = value ? String(value).trim() : '';
    if (!normalized) {
      return '';
    }
    const selects = vetSelectElements.filter(Boolean);
    const rootVetSelect = document.getElementById('schedule-veterinario_id');
    if (rootVetSelect && !selects.includes(rootVetSelect)) {
      selects.unshift(rootVetSelect);
    }
    for (const select of selects) {
      const option = Array.from(select.options || []).find((opt) => String(opt.value).trim() === normalized);
      if (option) {
        return option.textContent.trim();
      }
    }
    return '';
  }

  function setScheduleTitleVetName(vetValue, { label } = {}) {
    if (!scheduleTitleVetNameEl) {
      return;
    }
    const resolvedLabel = (label && label.trim()) || findVetLabelById(vetValue);
    if (resolvedLabel) {
      scheduleTitleVetNameEl.textContent = resolvedLabel;
      scheduleTitleVetNameEl.classList.remove('d-none');
      scheduleTitleVetNameEl.setAttribute('aria-hidden', 'false');
    } else {
      scheduleTitleVetNameEl.textContent = '';
      scheduleTitleVetNameEl.classList.add('d-none');
      scheduleTitleVetNameEl.setAttribute('aria-hidden', 'true');
    }
  }

  setScheduleTitleVetName(state.vetId);

  vetSelectElements.forEach((select) => {
    if (!select || select.dataset.scheduleTitleBound === 'true') {
      return;
    }
    select.dataset.scheduleTitleBound = 'true';
    select.addEventListener('change', () => {
      const newVetId = (select.value || '').trim();
      state.vetId = newVetId;
      if (root) {
        root.dataset.vetId = newVetId;
      }
      vetSelectElements.forEach((other) => {
        if (other && other !== select) {
          other.value = newVetId;
        }
      });
      state.selectedSlotKey = '';
      setScheduleTitleVetName(newVetId);
      if (summaryBadge) {
        summaryBadge.textContent = '';
        summaryBadge.classList.remove('text-bg-success', 'text-bg-warning');
        summaryBadge.classList.add('text-bg-light');
      }
      if (weekLabel) {
        weekLabel.textContent = '';
      }
      state.currentStart = getWeekStart(dateField?.value || state.todayIso);
      loadSchedule({ showLoading: true });
      updateAppointmentTimes({ root, veterinarianId: newVetId, dateInput: dateField, timeSelect });
    });
  });

  function formatIso(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
      return '';
    }
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function getWeekStart(value) {
    const base = value ? new Date(`${value}T00:00:00`) : new Date();
    if (Number.isNaN(base.getTime())) {
      return state.todayIso;
    }
    const day = base.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    const monday = new Date(base);
    monday.setDate(base.getDate() + diff);
    return formatIso(monday);
  }

  function updateToggleButtonLabel() {
    if (!toggleBtn) {
      return;
    }
    const showLabel = toggleBtn.dataset?.showLabel || 'Mostrar agenda';
    const hideLabel = toggleBtn.dataset?.hideLabel || 'Ocultar agenda';
    const expanded = collapseEl ? collapseEl.classList.contains('show') : true;
    toggleBtn.textContent = expanded ? hideLabel : showLabel;
    toggleBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }

  function showScheduleLoading() {
    scheduleContainer.innerHTML = '';
    const col = document.createElement('div');
    col.className = 'col';
    const loader = document.createElement('div');
    loader.className = 'd-flex align-items-center justify-content-center py-5 text-muted gap-3';
    loader.innerHTML = '<div class="spinner-border text-primary" role="status" aria-hidden="true"></div><span>Carregando horários...</span>';
    col.appendChild(loader);
    scheduleContainer.appendChild(col);
  }

  function setScheduleEmptyState(message, tone = 'light') {
    scheduleContainer.innerHTML = '';
    const col = document.createElement('div');
    col.className = 'col';
    const card = document.createElement('div');
    card.className = 'card h-100 border-0';
    card.classList.add(tone === 'danger' ? 'bg-danger-subtle' : 'bg-light-subtle');
    const body = document.createElement('div');
    body.className = 'card-body d-flex align-items-center justify-content-center text-center text-muted';
    body.innerHTML = '<div><i class="bi bi-calendar-x fs-4 d-block mb-2"></i><p class="mb-0">' + message + '</p></div>';
    card.appendChild(body);
    col.appendChild(card);
    scheduleContainer.appendChild(col);
  }

  function getPeriodFromTime(time) {
    if (!time) {
      return 'all';
    }
    const hour = parseInt(String(time).split(':')[0], 10);
    if (Number.isNaN(hour)) {
      return 'all';
    }
    if (hour < 12) {
      return 'morning';
    }
    if (hour < 18) {
      return 'afternoon';
    }
    return 'evening';
  }

  function filterSlotsByPeriod(slots) {
    if (!Array.isArray(slots) || state.period === 'all') {
      return Array.isArray(slots) ? slots : [];
    }
    return slots.filter((slot) => getPeriodFromTime(slot) === state.period);
  }

  function refreshSlotSelection() {
    const buttons = scheduleContainer.querySelectorAll('.schedule-slot[data-schedule-status="available"]');
    buttons.forEach((button) => {
      const key = button.dataset?.scheduleSlotKey || '';
      const isSelected = key === state.selectedSlotKey;
      button.classList.toggle('active', isSelected);
      button.classList.toggle('btn-success', isSelected);
      button.classList.toggle('btn-outline-success', !isSelected);
      button.classList.toggle('text-white', isSelected);
      button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
    });
  }

  function setScheduleSummary(days) {
    if (!summaryBadge) {
      return;
    }
    summaryBadge.classList.remove('text-bg-light', 'text-bg-success', 'text-bg-warning');
    summaryBadge.classList.add('text-bg-light');
    if (!Array.isArray(days) || !days.length) {
      summaryBadge.textContent = 'Sem horários disponíveis para o período selecionado.';
      return;
    }
    const now = new Date();
    let nextSlot = null;
    days.forEach((day) => {
      const availableSlots = Array.isArray(day.available) ? day.available : [];
      availableSlots.forEach((slot) => {
        const slotDate = new Date(`${day.date}T${slot}`);
        if (!nextSlot || (slotDate >= now && slotDate < nextSlot.dateObj)) {
          nextSlot = {
            date: day.date,
            time: slot,
            dateObj: slotDate
          };
        }
      });
    });
    if (!nextSlot) {
      const firstDay = days.find((day) => Array.isArray(day.available) && day.available.length);
      if (firstDay) {
        nextSlot = {
          date: firstDay.date,
          time: firstDay.available[0],
          dateObj: new Date(`${firstDay.date}T${firstDay.available[0]}`)
        };
      }
    }
    if (nextSlot) {
      const formattedDate = longFormatter.format(new Date(`${nextSlot.date}T00:00:00`));
      summaryBadge.textContent = `Próximo horário livre: ${formattedDate} às ${nextSlot.time}`;
      summaryBadge.classList.remove('text-bg-light');
      summaryBadge.classList.add('text-bg-success');
    } else {
      summaryBadge.textContent = 'Sem horários livres nesta semana.';
      summaryBadge.classList.remove('text-bg-light');
      summaryBadge.classList.add('text-bg-warning');
    }
  }

  function setWeekLabel(days) {
    if (!weekLabel) {
      return;
    }
    if (!Array.isArray(days) || !days.length) {
      weekLabel.textContent = 'Agenda indisponível para este período.';
      return;
    }
    const first = shortFormatter.format(new Date(`${days[0].date}T00:00:00`));
    const last = shortFormatter.format(new Date(`${days[days.length - 1].date}T00:00:00`));
    weekLabel.textContent = `Semana de ${first} a ${last}`;
  }

  function createSlotButton(time, status, options = {}) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-sm rounded-pill d-inline-flex align-items-center gap-1 schedule-slot flex-shrink-0';
    button.dataset.scheduleSlot = time;
    button.dataset.scheduleStatus = status;
    if (options.date) {
      button.dataset.scheduleDate = options.date;
      button.dataset.scheduleSlotKey = `${options.date}T${time}`;
    }
    button.dataset.schedulePeriod = getPeriodFromTime(time);
    if (status === 'available') {
      button.classList.add('btn-outline-success');
      button.innerHTML = '<i class="bi bi-check-circle"></i><span>' + time + '</span>';
      button.title = 'Selecionar horário disponível';
      button.addEventListener('click', () => {
        const dateValue = options.date || state.todayIso;
        state.selectedSlotKey = `${dateValue}T${time}`;
        refreshSlotSelection();
        handleSlotSelection(dateValue, time);
      });
    } else if (status === 'booked') {
      button.classList.add('btn-outline-danger', 'opacity-75');
      button.innerHTML = '<i class="bi bi-x-circle"></i><span>' + time + '</span>';
      button.disabled = true;
      button.setAttribute('aria-disabled', 'true');
      button.title = 'Horário indisponível';
    } else {
      button.classList.add('btn-outline-secondary', 'opacity-75');
      button.innerHTML = '<i class="bi bi-slash-circle"></i><span>' + time + '</span>';
      button.disabled = true;
      button.setAttribute('aria-disabled', 'true');
      button.title = 'Fora do expediente';
    }
    return button;
  }

  function renderSchedule(days) {
    scheduleContainer.innerHTML = '';
    if (!Array.isArray(days) || !days.length) {
      setScheduleEmptyState('Nenhum horário cadastrado para o período selecionado.');
      return;
    }

    days.forEach((day) => {
      const availableSlots = Array.isArray(day.available) ? day.available : [];
      const bookedSlots = Array.isArray(day.booked) ? day.booked : [];
      const offSlots = Array.isArray(day.not_working) ? day.not_working : [];
      const availableCount = availableSlots.length;
      const bookedCount = bookedSlots.length;
      const offCount = offSlots.length;

      const col = document.createElement('div');
      col.className = 'col';
      const card = document.createElement('div');
      card.className = 'card h-100 shadow-sm position-relative border-1';
      card.dataset.scheduleDay = day.date;
      if (availableCount > 0) {
        card.classList.add('border-success');
      } else if (bookedCount > 0) {
        card.classList.add('border-danger');
      } else {
        card.classList.add('border-secondary');
      }

      if (day.date === state.todayIso) {
        const todayBadge = document.createElement('span');
        todayBadge.className = 'badge text-bg-primary position-absolute top-0 end-0 translate-middle-y me-3 mt-3';
        todayBadge.textContent = 'Hoje';
        card.appendChild(todayBadge);
      }

      const body = document.createElement('div');
      body.className = 'card-body d-flex flex-column';

      const title = document.createElement('h6');
      title.className = 'card-title fw-bold text-capitalize mb-1';
      title.textContent = shortFormatter.format(new Date(`${day.date}T00:00:00`));
      body.appendChild(title);

      const subtitle = document.createElement('p');
      subtitle.className = 'text-muted small text-capitalize mb-3';
      subtitle.textContent = longFormatter.format(new Date(`${day.date}T00:00:00`));
      body.appendChild(subtitle);

      const statsRow = document.createElement('div');
      statsRow.className = 'd-flex justify-content-between align-items-center text-muted small mb-2';
      statsRow.innerHTML = `<span><i class="bi bi-check-circle-fill text-success me-1"></i>${availableCount} livre(s)</span>`
        + `<span><i class="bi bi-x-circle-fill text-danger me-1"></i>${bookedCount} ocupado(s)</span>`;
      body.appendChild(statsRow);

      if (availableCount + bookedCount > 0) {
        const progress = document.createElement('div');
        progress.className = 'progress bg-light-subtle mb-3';
        const availablePercent = Math.round((availableCount / Math.max(1, availableCount + bookedCount)) * 100);
        const bookedPercent = Math.max(0, 100 - availablePercent);
        const availableBar = document.createElement('div');
        availableBar.className = 'progress-bar bg-success';
        availableBar.style.width = `${availablePercent}%`;
        availableBar.setAttribute('aria-label', `${availableCount} horário(s) livre(s)`);
        progress.appendChild(availableBar);
        if (bookedPercent > 0) {
          const bookedBar = document.createElement('div');
          bookedBar.className = 'progress-bar bg-danger';
          bookedBar.style.width = `${bookedPercent}%`;
          bookedBar.setAttribute('aria-label', `${bookedCount} horário(s) ocupado(s)`);
          progress.appendChild(bookedBar);
        }
        body.appendChild(progress);
      } else if (offCount === 0) {
        const badge = document.createElement('span');
        badge.className = 'badge text-bg-light text-muted align-self-start mb-3';
        badge.textContent = 'Sem horários cadastrados.';
        body.appendChild(badge);
      }

      const slotsWrapper = document.createElement('div');
      slotsWrapper.className = 'd-flex flex-wrap gap-2';
      const filteredAvailable = filterSlotsByPeriod(availableSlots);
      if (filteredAvailable.length) {
        filteredAvailable.forEach((slot) => {
          slotsWrapper.appendChild(createSlotButton(slot, 'available', { date: day.date }));
        });
      } else if (availableSlots.length && state.period !== 'all') {
        const info = document.createElement('div');
        info.className = 'text-muted small fst-italic';
        info.textContent = 'Sem horários no período selecionado.';
        slotsWrapper.appendChild(info);
      }
      bookedSlots.forEach((slot) => {
        slotsWrapper.appendChild(createSlotButton(slot, 'booked', { date: day.date }));
      });
      offSlots.forEach((slot) => {
        slotsWrapper.appendChild(createSlotButton(slot, 'not_working', { date: day.date }));
      });

      if (!slotsWrapper.children.length) {
        const fallback = document.createElement('div');
        fallback.className = 'text-muted small fst-italic';
        fallback.textContent = 'Fora do expediente.';
        slotsWrapper.appendChild(fallback);
      }

      body.appendChild(slotsWrapper);
      card.appendChild(body);
      col.appendChild(card);
      scheduleContainer.appendChild(col);
    });

    refreshSlotSelection();
  }

  async function handleSlotSelection(date, time) {
    if (!dateField || !timeSelect) {
      return;
    }
    dateField.value = date;
    const times = await updateAppointmentTimes({ root, dateInput: dateField, timeSelect });
    const hasTimes = Array.isArray(times) && times.length > 0;
    if (timeSelect.disabled && (hasTimes || time)) {
      timeSelect.disabled = false;
    }
    if (!hasTimes || !times.includes(time)) {
      const existing = Array.from(timeSelect.options).find((option) => option.value === time);
      if (!existing) {
        const option = document.createElement('option');
        option.value = time;
        option.textContent = `${time}`;
        timeSelect.appendChild(option);
      }
    }
    timeSelect.value = time;
    timeSelect.dispatchEvent(new Event('change', { bubbles: true }));
  }

  async function loadSchedule({ showLoading = true } = {}) {
    if (!state.vetId) {
      state.vetId = resolveInitialVetId();
      if (root) {
        root.dataset.vetId = state.vetId || '';
      }
    }
    const activeVetId = (state.vetId || '').trim();
    if (!activeVetId) {
      state.days = [];
      setScheduleEmptyState('Selecione um profissional para visualizar a agenda.');
      if (summaryBadge) {
        summaryBadge.textContent = 'Selecione um profissional para visualizar os horários.';
        summaryBadge.classList.remove('text-bg-success', 'text-bg-warning');
        summaryBadge.classList.add('text-bg-light');
      }
      if (weekLabel) {
        weekLabel.textContent = 'Selecione um profissional para visualizar a agenda.';
      }
      return;
    }
    if (showLoading) {
      showScheduleLoading();
    }
    const start = state.currentStart || getWeekStart(dateField?.value || state.todayIso);
    state.currentStart = start;
    try {
      const response = await fetch(`/api/specialist/${activeVetId}/weekly_schedule?start=${start}`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const days = await response.json();
      state.days = Array.isArray(days) ? days : [];
      renderSchedule(state.days);
      setScheduleSummary(state.days);
      setWeekLabel(state.days);
    } catch (error) {
      console.warn('Não foi possível carregar os horários disponíveis.', error);
      state.days = [];
      setScheduleEmptyState('Não foi possível carregar a agenda no momento. Tente novamente.', 'danger');
      if (summaryBadge) {
        summaryBadge.classList.remove('text-bg-success');
        summaryBadge.classList.add('text-bg-warning');
        summaryBadge.textContent = 'Erro ao carregar agenda.';
      }
      if (weekLabel) {
        weekLabel.textContent = 'Erro ao carregar agenda.';
      }
    }
  }

  function changeWeek(deltaDays) {
    const startDate = new Date(`${state.currentStart || state.todayIso}T00:00:00`);
    if (Number.isNaN(startDate.getTime())) {
      state.currentStart = state.todayIso;
    } else {
      startDate.setDate(startDate.getDate() + deltaDays);
      state.currentStart = formatIso(startDate);
    }
    loadSchedule({ showLoading: collapseEl ? collapseEl.classList.contains('show') : true });
  }

  if (periodFilter && periodFilter.dataset.vetScheduleBound !== 'true') {
    periodFilter.dataset.vetScheduleBound = 'true';
    periodFilter.addEventListener('change', () => {
      state.period = periodFilter.value || 'all';
      renderSchedule(state.days);
    });
  }

  if (prevBtn && prevBtn.dataset.vetScheduleBound !== 'true') {
    prevBtn.dataset.vetScheduleBound = 'true';
    prevBtn.addEventListener('click', () => changeWeek(-7));
  }

  if (nextBtn && nextBtn.dataset.vetScheduleBound !== 'true') {
    nextBtn.dataset.vetScheduleBound = 'true';
    nextBtn.addEventListener('click', () => changeWeek(7));
  }

  if (todayBtn && todayBtn.dataset.vetScheduleBound !== 'true') {
    todayBtn.dataset.vetScheduleBound = 'true';
    todayBtn.addEventListener('click', () => {
      state.currentStart = getWeekStart(state.todayIso);
      loadSchedule({ showLoading: collapseEl ? collapseEl.classList.contains('show') : true });
    });
  }

  if (dateField && dateField.dataset.scheduleOverviewBound !== 'true') {
    dateField.dataset.scheduleOverviewBound = 'true';
    dateField.addEventListener('change', async () => {
      state.currentStart = getWeekStart(dateField.value || state.todayIso);
      const times = await updateAppointmentTimes({ root, dateInput: dateField, timeSelect });
      if (timeSelect) {
        const hasTimes = Array.isArray(times) && times.length > 0;
        timeSelect.disabled = !hasTimes;
      }
      loadSchedule({ showLoading: collapseEl ? collapseEl.classList.contains('show') : true });
    });
  }

  if (timeSelect && timeSelect.dataset.scheduleOverviewBound !== 'true') {
    timeSelect.dataset.scheduleOverviewBound = 'true';
    timeSelect.addEventListener('change', () => {
      if (dateField && dateField.value && timeSelect.value) {
        state.selectedSlotKey = `${dateField.value}T${timeSelect.value}`;
      } else {
        state.selectedSlotKey = '';
      }
      refreshSlotSelection();
    });
  }

  if (collapseEl && typeof collapseEl.addEventListener === 'function') {
    collapseEl.addEventListener('shown.bs.collapse', updateToggleButtonLabel);
    collapseEl.addEventListener('hidden.bs.collapse', updateToggleButtonLabel);
  }
  updateToggleButtonLabel();

  state.currentStart = getWeekStart(dateField?.value || state.todayIso);
  loadSchedule({ showLoading: true });
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

function updateExamRequesterStatusBadge(element, label, badgeClass) {
  if (!element) {
    return;
  }
  const classes = ['badge'];
  if (badgeClass) {
    badgeClass
      .split(/\s+/)
      .filter(Boolean)
      .forEach((cls) => classes.push(cls));
  } else {
    classes.push('bg-secondary');
  }
  element.className = classes.join(' ');
  element.textContent = label && label.trim() ? label : '—';
}

function setExamRequesterFeedback(message = '', variant = 'danger') {
  const feedbackEl = document.getElementById('exam-requester-feedback');
  if (!feedbackEl) {
    return;
  }
  const hasMessage = Boolean(message && message.trim());
  feedbackEl.classList.toggle('d-none', !hasMessage);
  feedbackEl.textContent = hasMessage ? message : '';
  feedbackEl.className = `alert alert-${variant}`;
  feedbackEl.setAttribute('role', 'alert');
}

function openExamRequesterModal(row, root) {
  if (!row) {
    return;
  }
  const { element: modalEl, modal } = getModalElementById(EXAM_REQUESTER_MODAL_ID);
  if (!modalEl || !modal) {
    return;
  }

  const confirmInput = document.getElementById('exam-requester-confirm-by');
  const statusSelect = document.getElementById('exam-requester-status');
  const idInput = document.getElementById('exam-requester-id');
  const animalEl = document.getElementById('exam-requester-animal');
  const specialistEl = document.getElementById('exam-requester-specialist');
  const scheduledEl = document.getElementById('exam-requester-scheduled');
  const statusLabel = document.getElementById('exam-requester-status-label');
  const defaultButton = document.getElementById('exam-requester-apply-default');

  const examId = row.dataset.examId || '';
  const status = row.dataset.examStatus || '';
  const confirmBy = row.dataset.examConfirmBy || '';

  const defaultValue = computeExamDefaultConfirmValue({ root, row });
  const defaultHours = getExamDefaultConfirmHours(root);

  modalEl.dataset.examId = examId;
  modalEl.dataset.examStatus = status;
  modalEl.dataset.examConfirmBy = confirmBy;
  modalEl.dataset.examDefaultConfirmBy = defaultValue || '';
  modalEl.dataset.examDefaultConfirmHours = defaultHours?.toString() || '';
  modalEl.dataset.examRequestedAt = row.dataset.examRequestedAt || '';
  modalEl.dataset.examRequestedAtDisplay = row.dataset.examRequestedAtDisplay || '';

  if (idInput) {
    idInput.value = examId;
  }

  updateTextContent(animalEl, row.dataset.examAnimal || '', '—');
  updateTextContent(specialistEl, row.dataset.examSpecialist || '', '—');
  updateTextContent(scheduledEl, row.dataset.examScheduledDisplay || '', '—');
  updateExamRequesterStatusBadge(
    statusLabel,
    row.dataset.examStatusLabel || '',
    row.dataset.examBadgeClass || ''
  );

  if (confirmInput) {
    if (!confirmBy && defaultValue) {
      confirmInput.value = defaultValue;
    } else {
      confirmInput.value = confirmBy || '';
    }
    confirmInput.disabled = status === 'confirmed';
    confirmInput.dataset.defaultValue = defaultValue || '';
  }

  if (defaultButton) {
    defaultButton.disabled = status === 'confirmed' || !defaultValue;
    defaultButton.dataset.defaultValue = defaultValue || '';
    defaultButton.dataset.defaultHours = defaultHours?.toString() || '';
  }

  updateExamRequesterDefaultPreview({
    defaultValue: defaultValue || confirmInput?.value || '',
    modalEl,
    row
  });

  if (statusSelect) {
    const current = status || 'pending';
    const optionExists = Array.from(statusSelect.options).some((option) => option.value === current);
    if (!optionExists && current) {
      const option = document.createElement('option');
      option.value = current;
      option.textContent = humanizeLabel(current);
      statusSelect.appendChild(option);
    }
    statusSelect.value = current;
    statusSelect.disabled = current === 'confirmed';
  }

  const isConfirmed = status === 'confirmed';
  if (isConfirmed) {
    setExamRequesterFeedback('Este exame já foi confirmado pelo especialista.', 'info');
  } else if (!confirmBy && defaultValue) {
    const hoursLabel = formatHoursText(defaultHours ?? NaN);
    const messageParts = [];
    if (hoursLabel) {
      messageParts.push(`Aplicamos automaticamente o prazo padrão (${hoursLabel}).`);
    } else {
      messageParts.push('Aplicamos automaticamente o prazo padrão.');
    }
    messageParts.push('Confirme ou ajuste o prazo antes de salvar.');
    setExamRequesterFeedback(messageParts.join(' '), 'info');
  } else {
    setExamRequesterFeedback('');
  }

  modal.show();
}

function bindExamRequesterRows(root) {
  if (!root) {
    return;
  }
  const rows = root.querySelectorAll(EXAM_REQUESTER_ROW_SELECTOR);
  rows.forEach((row) => {
    if (row.dataset.vetScheduleBound === 'true') {
      return;
    }
    row.dataset.vetScheduleBound = 'true';
    if (!row.hasAttribute('tabindex')) {
      row.setAttribute('tabindex', '0');
    }
    if (!row.hasAttribute('role')) {
      row.setAttribute('role', 'button');
    }
    row.addEventListener('click', (event) => {
      if (event.target.closest('button, a, input, select, textarea')) {
        return;
      }
      openExamRequesterModal(row, root);
    });
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openExamRequesterModal(row, root);
      }
    });
  });
}

function bindExamRequesterDefaultButton(root) {
  const button = document.getElementById('exam-requester-apply-default');
  if (!button || button.dataset.vetScheduleBound === 'true') {
    return;
  }
  button.dataset.vetScheduleBound = 'true';
  button.addEventListener('click', () => {
    const { element: modalEl } = getModalElementById(EXAM_REQUESTER_MODAL_ID);
    const confirmInput = document.getElementById('exam-requester-confirm-by');
    if (!modalEl || !confirmInput || confirmInput.disabled) {
      return;
    }
    const defaultValue = button.dataset.defaultValue || modalEl.dataset.examDefaultConfirmBy || '';
    if (!defaultValue) {
      return;
    }
    confirmInput.value = defaultValue;
    confirmInput.dispatchEvent(new Event('input', { bubbles: true }));
    confirmInput.dispatchEvent(new Event('change', { bubbles: true }));

    const defaultHoursRaw = button.dataset.defaultHours || modalEl.dataset.examDefaultConfirmHours || '';
    const defaultHours = Number.parseFloat(defaultHoursRaw);
    const hoursLabel = formatHoursText(defaultHours);
    if (hoursLabel) {
      setExamRequesterFeedback(`Prazo padrão (${hoursLabel}) aplicado.`, 'info');
    } else {
      setExamRequesterFeedback('Prazo padrão aplicado.', 'info');
    }

    updateExamRequesterDefaultPreview({
      defaultValue,
      modalEl,
      row: null
    });
  });
}

function bindExamRequesterSave(root) {
  const saveButton = document.getElementById('exam-requester-save');
  if (!saveButton || saveButton.dataset.vetScheduleBound === 'true') {
    return;
  }
  saveButton.dataset.vetScheduleBound = 'true';
  saveButton.addEventListener('click', async () => {
    const { element: modalEl, modal } = getModalElementById(EXAM_REQUESTER_MODAL_ID);
    if (!modalEl) {
      return;
    }
    const examId = modalEl.dataset.examId || '';
    if (!examId) {
      return;
    }
    const confirmInput = document.getElementById('exam-requester-confirm-by');
    const statusSelect = document.getElementById('exam-requester-status');
    const originalConfirm = modalEl.dataset.examConfirmBy || '';
    const originalStatus = modalEl.dataset.examStatus || '';
    const currentConfirm = confirmInput?.value || '';
    const currentStatus = statusSelect?.value || '';

    if (confirmInput?.disabled && statusSelect?.disabled) {
      modal?.hide();
      return;
    }

    if (currentConfirm === originalConfirm && currentStatus === originalStatus) {
      modal?.hide();
      return;
    }

    const payload = {};
    if (confirmInput && !confirmInput.disabled) {
      payload.confirm_by = confirmInput.value || null;
    }
    if (statusSelect && !statusSelect.disabled) {
      payload.status = statusSelect.value || null;
    }

    setExamRequesterFeedback('');
    saveButton.disabled = true;
    const originalText = saveButton.innerHTML;
    saveButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Salvando...';
    try {
      const response = await fetch(`/exam_appointment/${examId}/requester_update`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-CSRFToken': getCsrfToken(root)
        },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        const message = errorData?.message || 'Não foi possível atualizar o exame.';
        setExamRequesterFeedback(message, 'danger');
        return;
      }
      const data = await response.json();
      if (!data?.success) {
        setExamRequesterFeedback(data?.message || 'Não foi possível atualizar o exame.', 'danger');
        return;
      }
      if (modal) {
        modal.hide();
      }
      window.location.reload();
    } catch (error) {
      console.error('Erro ao atualizar solicitação de exame', error);
      setExamRequesterFeedback('Erro inesperado ao salvar alterações.', 'danger');
    } finally {
      saveButton.disabled = false;
      saveButton.innerHTML = originalText;
    }
  });
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
      const vetNameEl = document.getElementById('modal-vet-name');
      const tutorNameEl = document.getElementById('modal-tutor-name');
      const animalNameEl = document.getElementById('modal-animal-name');
      const createdByText = document.getElementById('modal-created-by-text');
      const createdAtText = document.getElementById('modal-created-at-text');
      const dateDisplay = document.getElementById('modal-date-display');
      const timeDisplay = document.getElementById('modal-time-display');
      const kindLabelEl = document.getElementById('modal-kind-label');
      const statusLabelEl = document.getElementById('modal-status-label');
      const notesPreviewContainer = document.getElementById('modal-notes-display');
      const notesPreviewText = document.getElementById('modal-notes-text');
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
      updateTextContent(vetNameEl, item.dataset.vet || '', '—');
      updateTextContent(tutorNameEl, item.dataset.tutor || '', '—');
      updateTextContent(animalNameEl, item.dataset.animal || '', '—');
      updateTextContent(createdByText, item.dataset.createdBy || '', 'Não informado');
      updateTextContent(createdAtText, item.dataset.createdAt || '', 'Não informado');

      const dateValue = item.dataset.date || '';
      if (dateField) {
        dateField.value = dateValue;
      }
      updateTextContent(
        dateDisplay,
        item.dataset.dateLabel || formatDateToBrazil(dateValue),
        '--/--/----'
      );

      if (timeField) {
        ensurePlaceholderOption(timeField, timeField?.dataset?.placeholder || DEFAULT_TIME_PLACEHOLDER);
      }
      const timeValue = item.dataset.time || '';
      updateTextContent(timeDisplay, timeValue, '--:--');

      if (notesField) {
        notesField.value = item.dataset.notes || '';
      }
      updateModalNotesPreview(notesPreviewContainer, notesPreviewText, item.dataset.notes || '');
      updateModalTypePill(kindLabelEl, item.dataset.type || '', item.dataset.typeLabel || '');
      updateModalStatusBadge(statusLabelEl, item.dataset.status || '', item.dataset.statusLabel || '');

      if (animalLink && item.dataset.animalUrl) {
        animalLink.href = item.dataset.animalUrl;
      }
      if (tutorLink && item.dataset.tutorUrl) {
        tutorLink.href = item.dataset.tutorUrl;
      }
      if (consultaLink && item.dataset.consultaUrl) {
        consultaLink.href = item.dataset.consultaUrl;
      }

      if (modalEl) {
        modalEl.dataset.vetId = item.dataset.vetId || getVetId(root) || '';
        modalEl.dataset.kind = item.dataset.type || '';
        modalEl.dataset.currentTime = item.dataset.time || '';
      }

      if (modal) {
        modal.show();
      }

      if (timeField) {
        const populateResult = populateAppointmentModalTimes({
          root,
          vetId: modalEl?.dataset?.vetId || getVetId(root),
          kind: modalEl?.dataset?.kind || '',
          dateField,
          timeSelect: timeField,
          currentTime: modalEl?.dataset?.currentTime || ''
        });
        if (populateResult && typeof populateResult.then === 'function') {
          populateResult.then(() => {
            updateTextContent(
              timeDisplay,
              timeField.value || modalEl?.dataset?.currentTime || '',
              '--:--'
            );
          });
        }
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
    const modalEl = document.getElementById('appointmentDetailModal');
    const appointmentId = idField?.value;
    if (!appointmentId) {
      return;
    }
    const updateUrl = `${getAppointmentsBaseUrl(root)}/${appointmentId}/edit`;
    const vetId = modalEl?.dataset?.vetId || getVetId(root);
    const payload = {
      date: dateField?.value || '',
      time: timeField?.value || '',
      veterinario_id: vetId,
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

function bindAppointmentEditDateWatcher(root) {
  const modalEl = document.getElementById('appointmentDetailModal');
  const dateInput = document.getElementById('modal-date');
  const timeSelect = document.getElementById('modal-time');
  if (!modalEl || !dateInput || !timeSelect || dateInput.dataset.vetScheduleBound === 'true') {
    return;
  }
  dateInput.dataset.vetScheduleBound = 'true';
  dateInput.addEventListener('change', () => {
    const vetId = modalEl.dataset?.vetId || getVetId(root);
    const kind = modalEl.dataset?.kind || '';
    modalEl.dataset.currentTime = '';
    updateTextContent(
      document.getElementById('modal-date-display'),
      dateInput.value ? formatDateToBrazil(dateInput.value) : '',
      '--/--/----'
    );
    populateAppointmentModalTimes({
      root,
      vetId,
      kind,
      dateField: dateInput,
      timeSelect,
      currentTime: ''
    });
  });
}

function bindAppointmentEditTimeWatcher() {
  const modalEl = document.getElementById('appointmentDetailModal');
  const timeSelect = document.getElementById('modal-time');
  if (!modalEl || !timeSelect || timeSelect.dataset.vetScheduleBound === 'true') {
    return;
  }
  timeSelect.dataset.vetScheduleBound = 'true';
  timeSelect.addEventListener('change', () => {
    modalEl.dataset.currentTime = timeSelect.value || '';
    updateTextContent(
      document.getElementById('modal-time-display'),
      timeSelect.value || '',
      '--:--'
    );
  });
}

function bindAppointmentNotesWatcher() {
  const notesField = document.getElementById('modal-notes');
  const notesPreviewContainer = document.getElementById('modal-notes-display');
  const notesPreviewText = document.getElementById('modal-notes-text');
  if (!notesField || notesField.dataset.vetScheduleBound === 'true') {
    return;
  }
  notesField.dataset.vetScheduleBound = 'true';
  notesField.addEventListener('input', () => {
    updateModalNotesPreview(notesPreviewContainer, notesPreviewText, notesField.value || '');
  });
}

async function applyCalendarSlotToNewAppointment(root, detail) {
  const dateField = document.getElementById('appointment-date');
  const timeSelect = document.getElementById('appointment-time');
  if (!dateField) {
    return;
  }

  const targetDate = (detail.date || '').trim();
  const targetTime = (detail.time || '').trim();

  if (targetDate) {
    const previousValue = dateField.value;
    dateField.value = targetDate;
    if (dateField.value !== previousValue) {
      dateField.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      dateField.dispatchEvent(new Event('input', { bubbles: true }));
      dateField.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  if (!timeSelect) {
    return;
  }

  const availableTimes = await updateAppointmentTimes({ root, dateInput: dateField, timeSelect });
  const hasTimes = Array.isArray(availableTimes) && availableTimes.length > 0;
  if (timeSelect.disabled && (hasTimes || targetTime)) {
    timeSelect.disabled = false;
  }

  if (!targetTime) {
    timeSelect.dataset.currentTime = '';
    return;
  }

  let option = Array.from(timeSelect.options).find((item) => item.value === targetTime);
  if (!option) {
    option = document.createElement('option');
    option.value = targetTime;
    option.textContent = targetTime;
    timeSelect.appendChild(option);
  }
  timeSelect.value = targetTime;
  timeSelect.dataset.currentTime = targetTime;
  timeSelect.dispatchEvent(new Event('change', { bubbles: true }));
}

function bindCalendarSlotHandler(root) {
  if (!root || root.dataset.calendarSlotHandlerBound === 'true') {
    return;
  }

  const calendarCollapseId = root.dataset?.calendarCollapseId || '';
  const calendarCollapseEl = calendarCollapseId
    ? document.getElementById(calendarCollapseId)
    : null;
  const calendarToggleBtn = calendarCollapseId
    ? document.querySelector(`[data-bs-target="#${calendarCollapseId}"]`)
    : null;
  const newAppointmentCollapseEl = document.getElementById('newAppointmentForm');
  const newAppointmentToggleBtn = document.querySelector('[data-bs-target="#newAppointmentForm"]');

  const handler = async (event) => {
    const detail = event.detail || {};
    if (!detail.date) {
      return;
    }
    const eventTarget = event.target;
    if (eventTarget instanceof Node && !root.contains(eventTarget)) {
      return;
    }

    if (calendarCollapseEl) {
      hideCollapseElement(calendarCollapseEl);
      updateCollapseToggleState(calendarToggleBtn, false);
    }

    showCollapseElement(newAppointmentCollapseEl);
    updateCollapseToggleState(newAppointmentToggleBtn, true);

    try {
      await applyCalendarSlotToNewAppointment(root, detail);
    } catch (error) {
      console.warn('Não foi possível preencher o formulário com o horário selecionado.', error);
    }

    focusFirstField(newAppointmentCollapseEl);
    scrollIntoViewSmooth(newAppointmentCollapseEl);
  };

  document.addEventListener('calendarSlotChosen', handler);
  root.dataset.calendarSlotHandlerBound = 'true';
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
  setupAppointmentsCalendarSummary({ waitForDomContentLoaded: false });
  if (!root || root.dataset.vetScheduleInitialized === 'true') {
    return root;
  }
  root.dataset.vetScheduleInitialized = 'true';

  bindScheduleEditButtons(root);
  bindAppointmentItems(root);
  bindAppointmentModalSave(root);
  bindAppointmentDateWatcher(root);
  bindAppointmentEditDateWatcher(root);
  bindAppointmentEditTimeWatcher();
  bindAppointmentNotesWatcher();
  bindExamRequesterRows(root);
  bindExamRequesterDefaultButton(root);
  bindExamRequesterSave(root);
  bindPastToggle(root);
  bindScheduleModalButton(root);
  bindCalendarSlotHandler(root);
  initScheduleOverview(root);
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

function onDocumentReady(callback) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', callback, { once: true });
    return;
  }
  callback();
}

onDocumentReady(() => {
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
