export function setupAppointmentsCalendarSummary(options = {}) {
  const {
    waitForDomContentLoaded = true,
    summaryPanelSelector = '[data-calendar-summary-panel]',
    summaryToggleSelector = '[data-calendar-summary-toggle]',
    summaryColumnSelector = '[data-calendar-summary-column]',
    mainColumnSelector = '[data-calendar-main-column]',
    calendarTabsSelector = '[data-calendar-tabs]',
  } = options;

  const initialize = () => {
    const calendarSummaryPanel = document.querySelector(summaryPanelSelector);
    const calendarSummaryToggleButton = document.querySelector(summaryToggleSelector);
    const calendarSummaryColumn = document.querySelector(summaryColumnSelector);
    const calendarMainColumn = document.querySelector(mainColumnSelector);
    if (calendarSummaryToggleButton && !calendarSummaryColumn) {
      calendarSummaryToggleButton.classList.add('d-none');
    }
    if (!calendarSummaryPanel) {
      return;
    }
    if (calendarSummaryPanel.dataset.calendarSummaryInitialized === 'true') {
      return;
    }
    calendarSummaryPanel.dataset.calendarSummaryInitialized = 'true';

    const calendarSummaryList = calendarSummaryPanel.querySelector('[data-calendar-summary-list]');
    const calendarSummaryFilters = calendarSummaryPanel.querySelector('[data-calendar-summary-filters]');
    const calendarSummaryEmpty = calendarSummaryPanel.querySelector('[data-calendar-summary-empty]');
    const calendarSummaryTotalBadge = calendarSummaryPanel.querySelector('[data-calendar-summary-total]');
    const calendarSummaryOverview = calendarSummaryPanel.querySelector('[data-calendar-summary-overview]');
    const calendarSummaryOverviewToday = calendarSummaryPanel.querySelector('[data-calendar-summary-overview-today]');
    const calendarSummaryOverviewWeek = calendarSummaryPanel.querySelector('[data-calendar-summary-overview-week]');
    const calendarSummaryLoading = calendarSummaryPanel.querySelector('[data-calendar-summary-loading]');
    const calendarSummaryToggleLabel = calendarSummaryToggleButton
      ? calendarSummaryToggleButton.querySelector('[data-calendar-summary-toggle-label]')
      : null;
    const calendarSummaryToggleIcon = calendarSummaryToggleButton
      ? calendarSummaryToggleButton.querySelector('[data-calendar-summary-toggle-icon]')
      : null;
    const calendarTabsElement = document.querySelector(calendarTabsSelector);
    const calendarTabButtons = calendarTabsElement
      ? calendarTabsElement.querySelectorAll('[data-bs-toggle="tab"]')
      : document.querySelectorAll('#appointments-calendar-tabs [data-bs-toggle="tab"]');

    const calendarSummaryCollapsedStorageKey = (() => {
      if (!calendarSummaryPanel) {
        return 'appointmentsCalendarSummaryCollapsed';
      }
      const rawKey = calendarSummaryPanel.getAttribute('data-calendar-summary-storage-key');
      if (typeof rawKey === 'string') {
        const trimmed = rawKey.trim();
        if (trimmed) {
          return trimmed;
        }
      }
      return 'appointmentsCalendarSummaryCollapsed';
    })();
    const calendarActiveTabStorageKey = 'appointmentsCalendarActiveTab';
    const calendarMainColumnVisibleClasses = ['col-xl-8', 'col-xxl-9'];
    const calendarMainColumnFullWidthClasses = ['col-xl-12', 'col-xxl-12'];
    const calendarSummaryWeekdays = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

    let calendarSummaryTabVisible = true;
    let isCalendarSummaryCollapsed = getStoredCalendarSummaryCollapsed();
    let activeCalendarSummaryVetId = null;

    function applyCalendarSummaryVisibilityState() {
      const shouldDisplay = calendarSummaryTabVisible && !isCalendarSummaryCollapsed;
      if (calendarSummaryColumn) {
        calendarSummaryColumn.classList.toggle('d-none', !shouldDisplay);
        calendarSummaryColumn.setAttribute('aria-hidden', shouldDisplay ? 'false' : 'true');
      }
      if (calendarMainColumn) {
        calendarMainColumnVisibleClasses.forEach((className) => {
          calendarMainColumn.classList.toggle(className, shouldDisplay);
        });
        calendarMainColumnFullWidthClasses.forEach((className) => {
          calendarMainColumn.classList.toggle(className, !shouldDisplay);
        });
      }
      if (calendarSummaryPanel) {
        calendarSummaryPanel.setAttribute('aria-hidden', shouldDisplay ? 'false' : 'true');
      }
      if (calendarSummaryToggleButton) {
        calendarSummaryToggleButton.setAttribute('aria-expanded', shouldDisplay ? 'true' : 'false');
      }
    }

    function updateCalendarSummaryToggleButtonState() {
      if (!calendarSummaryToggleButton) {
        return;
      }
      const showLabel = (calendarSummaryToggleButton.dataset && calendarSummaryToggleButton.dataset.showLabel)
        || calendarSummaryToggleButton.getAttribute('data-show-label')
        || 'Mostrar resumo';
      const hideLabel = (calendarSummaryToggleButton.dataset && calendarSummaryToggleButton.dataset.hideLabel)
        || calendarSummaryToggleButton.getAttribute('data-hide-label')
        || 'Ocultar resumo';
      const label = isCalendarSummaryCollapsed ? showLabel : hideLabel;
      if (calendarSummaryToggleLabel) {
        calendarSummaryToggleLabel.textContent = label;
      } else {
        calendarSummaryToggleButton.textContent = label;
      }
      if (calendarSummaryToggleIcon) {
        calendarSummaryToggleIcon.classList.remove('bi-layout-sidebar', 'bi-layout-sidebar-inset');
        calendarSummaryToggleIcon.classList.add(isCalendarSummaryCollapsed ? 'bi-layout-sidebar' : 'bi-layout-sidebar-inset');
      }
      calendarSummaryToggleButton.setAttribute('aria-pressed', isCalendarSummaryCollapsed ? 'true' : 'false');
      calendarSummaryToggleButton.setAttribute('title', label);
      const isAvailable = calendarSummaryTabVisible && !!calendarSummaryColumn;
      calendarSummaryToggleButton.disabled = !isAvailable;
      calendarSummaryToggleButton.setAttribute('aria-disabled', isAvailable ? 'false' : 'true');
      calendarSummaryToggleButton.classList.toggle('disabled', !isAvailable);
    }

    function updateCalendarSummaryVisibilityFromTarget(targetSelector) {
      const normalized = typeof targetSelector === 'string' ? targetSelector.trim() : '';
      calendarSummaryTabVisible = normalized === '#calendar-pane-experimental'
        || normalized === 'calendar-pane-experimental'
        || normalized === '';
      applyCalendarSummaryVisibilityState();
      updateCalendarSummaryToggleButtonState();
    }

    function normalizeCalendarTabTarget(value) {
      if (typeof value !== 'string') {
        return '';
      }
      return value.trim();
    }

    function getStoredCalendarSummaryCollapsed() {
      if (typeof window === 'undefined' || !window.localStorage) {
        return false;
      }
      try {
        const stored = window.localStorage.getItem(calendarSummaryCollapsedStorageKey);
        if (stored === null) {
          return false;
        }
        if (stored === '1' || stored === 'true') {
          return true;
        }
        if (stored === '0' || stored === 'false') {
          return false;
        }
        return stored === 'collapsed';
      } catch (error) {
        return false;
      }
    }

    function storeCalendarSummaryCollapsed(collapsed) {
      if (typeof window === 'undefined' || !window.localStorage) {
        return;
      }
      try {
        if (collapsed) {
          window.localStorage.setItem(calendarSummaryCollapsedStorageKey, '1');
        } else {
          window.localStorage.removeItem(calendarSummaryCollapsedStorageKey);
        }
      } catch (error) {
        // Ignorado intencionalmente.
      }
    }

    function setCalendarSummaryCollapsed(collapsed, options = {}) {
      const shouldStore = options.store !== false;
      const normalized = !!collapsed;
      const stateChanged = isCalendarSummaryCollapsed !== normalized;
      isCalendarSummaryCollapsed = normalized;
      if (shouldStore && stateChanged) {
        storeCalendarSummaryCollapsed(isCalendarSummaryCollapsed);
      }
      updateCalendarSummaryToggleButtonState();
      applyCalendarSummaryVisibilityState();
    }

    if (calendarSummaryToggleButton) {
      calendarSummaryToggleButton.addEventListener('click', () => {
        if (!calendarSummaryTabVisible || !calendarSummaryColumn) {
          return;
        }
        setCalendarSummaryCollapsed(!isCalendarSummaryCollapsed);
      });
    }

    function getStoredCalendarActiveTab() {
      if (typeof window === 'undefined' || !window.localStorage) {
        return '';
      }
      try {
        const storedValue = window.localStorage.getItem(calendarActiveTabStorageKey);
        return normalizeCalendarTabTarget(storedValue || '');
      } catch (error) {
        return '';
      }
    }

    function storeCalendarActiveTab(target) {
      if (typeof window === 'undefined' || !window.localStorage) {
        return;
      }
      const normalized = normalizeCalendarTabTarget(target);
      try {
        if (normalized) {
          window.localStorage.setItem(calendarActiveTabStorageKey, normalized);
        } else {
          window.localStorage.removeItem(calendarActiveTabStorageKey);
        }
      } catch (error) {
        // Ignorado intencionalmente.
      }
    }

    function showCalendarTab(button) {
      if (!button) {
        return false;
      }
      let bootstrapNamespace = null;
      if (typeof window !== 'undefined'
        && window.bootstrap
        && window.bootstrap.Tab
        && typeof window.bootstrap.Tab.getOrCreateInstance === 'function') {
        bootstrapNamespace = window.bootstrap;
      } else if (typeof bootstrap !== 'undefined'
        && bootstrap
        && bootstrap.Tab
        && typeof bootstrap.Tab.getOrCreateInstance === 'function') {
        bootstrapNamespace = bootstrap;
      }
      if (bootstrapNamespace) {
        const tabInstance = bootstrapNamespace.Tab.getOrCreateInstance(button);
        if (tabInstance && typeof tabInstance.show === 'function') {
          tabInstance.show();
          return true;
        }
      }
      if (typeof button.click === 'function') {
        button.click();
        return true;
      }
      return false;
    }

    const calendarTabButtonsArray = Array.prototype.slice.call(calendarTabButtons || []);
    if (calendarTabButtonsArray.length > 0) {
      const storedCalendarTabTarget = getStoredCalendarActiveTab();

      calendarTabButtonsArray.forEach((button) => {
        button.addEventListener('shown.bs.tab', (event) => {
          const target = event && event.target
            ? event.target.getAttribute('data-bs-target')
            : '';
          const normalizedTarget = normalizeCalendarTabTarget(target);
          updateCalendarSummaryVisibilityFromTarget(normalizedTarget);
          storeCalendarActiveTab(normalizedTarget);
        });
      });

      if (storedCalendarTabTarget) {
        const storedButton = calendarTabButtonsArray.find((button) => {
          return normalizeCalendarTabTarget(button.getAttribute('data-bs-target')) === storedCalendarTabTarget;
        });
        if (storedButton) {
          if (!storedButton.classList.contains('active')) {
            const wasShown = showCalendarTab(storedButton);
            if (!wasShown) {
              updateCalendarSummaryVisibilityFromTarget(storedCalendarTabTarget);
            }
          } else {
            updateCalendarSummaryVisibilityFromTarget(storedCalendarTabTarget);
          }
        } else {
          storeCalendarActiveTab('');
        }
      }
    }

    const activeCalendarTab = (calendarTabsElement
      ? calendarTabsElement.querySelector('.nav-link.active[data-bs-target]')
      : document.querySelector('#appointments-calendar-tabs .nav-link.active[data-bs-target]'));
    if (activeCalendarTab) {
      updateCalendarSummaryVisibilityFromTarget(activeCalendarTab.getAttribute('data-bs-target'));
    } else if (calendarTabButtonsArray.length > 0) {
      const defaultTarget = normalizeCalendarTabTarget(
        calendarTabButtonsArray[0].getAttribute('data-bs-target') || '#calendar-pane-experimental',
      );
      updateCalendarSummaryVisibilityFromTarget(defaultTarget);
    } else {
      updateCalendarSummaryVisibilityFromTarget('#calendar-pane-experimental');
    }

    function padNumber(value) {
      return String(value).padStart(2, '0');
    }

    function startOfDay(date) {
      if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return null;
      }
      return new Date(date.getFullYear(), date.getMonth(), date.getDate());
    }

    function parseSummaryDate(value) {
      if (!value) {
        return null;
      }
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return null;
      }
      return parsed;
    }

    function normalizeSummaryVetId(value) {
      if (typeof window !== 'undefined'
        && window.calendarVetColorManager
        && typeof window.calendarVetColorManager.normalize === 'function') {
        return window.calendarVetColorManager.normalize(value);
      }
      if (value === undefined || value === null) {
        return null;
      }
      if (typeof value === 'number' && Number.isFinite(value)) {
        return String(value);
      }
      const normalized = String(value).trim();
      return normalized || null;
    }

    function normalizeSummaryClinicId(value) {
      if (value === undefined || value === null) {
        return null;
      }
      if (typeof value === 'number' && Number.isFinite(value)) {
        return String(value);
      }
      const normalized = String(value).trim();
      return normalized || null;
    }

    function normalizeSummaryNumber(value) {
      if (typeof value === 'number' && Number.isFinite(value)) {
        return value;
      }
      if (typeof value === 'string' && value.trim()) {
        const parsed = Number(value);
        if (!Number.isNaN(parsed)) {
          return parsed;
        }
      }
      return 0;
    }

    function parseCalendarSummaryAttributeJSON(attributeName) {
      if (!calendarSummaryPanel || !attributeName) {
        return null;
      }
      const rawValue = calendarSummaryPanel.getAttribute(attributeName);
      if (!rawValue) {
        return null;
      }
      try {
        return JSON.parse(rawValue);
      } catch (error) {
        return null;
      }
    }

    function extractSummaryIds(attributeName, normalizer) {
      if (typeof normalizer !== 'function') {
        return [];
      }
      const parsed = parseCalendarSummaryAttributeJSON(attributeName);
      const source = Array.isArray(parsed)
        ? parsed
        : (parsed === undefined || parsed === null ? [] : [parsed]);
      const results = [];
      source.forEach((item) => {
        const normalized = normalizer(item);
        if (Array.isArray(normalized)) {
          normalized.forEach((value) => {
            if (value) {
              results.push(value);
            }
          });
        } else if (normalized) {
          results.push(normalized);
        }
      });
      return results;
    }

    const calendarSummaryAllowedVetIds = (() => {
      const ids = extractSummaryIds('data-calendar-summary-vets', (entry) => {
        if (entry && typeof entry === 'object') {
          const candidate = entry.id
            ?? entry.vetId
            ?? entry.veterinario_id
            ?? entry.veterinarioId
            ?? null;
          return normalizeSummaryVetId(candidate);
        }
        return normalizeSummaryVetId(entry);
      });
      return new Set(ids.filter(Boolean));
    })();

    const calendarSummaryAllowedClinicIds = (() => {
      const ids = extractSummaryIds('data-calendar-summary-clinic-ids', (entry) => {
        if (entry && typeof entry === 'object') {
          const candidate = entry.id
            ?? entry.clinicId
            ?? entry.clinica_id
            ?? entry.clinicaId
            ?? null;
          return normalizeSummaryClinicId(candidate);
        }
        return normalizeSummaryClinicId(entry);
      });
      return new Set(ids.filter(Boolean));
    })();

    function isCalendarSummaryVetAllowed(vetId) {
      const normalized = normalizeSummaryVetId(vetId);
      if (!normalized) {
        return false;
      }
      if (!(calendarSummaryAllowedVetIds instanceof Set) || calendarSummaryAllowedVetIds.size === 0) {
        return true;
      }
      return calendarSummaryAllowedVetIds.has(normalized);
    }

    function isCalendarSummaryClinicAllowed(clinicId) {
      const normalized = normalizeSummaryClinicId(clinicId);
      if (!(calendarSummaryAllowedClinicIds instanceof Set) || calendarSummaryAllowedClinicIds.size === 0) {
        return true;
      }
      if (!normalized) {
        return false;
      }
      return calendarSummaryAllowedClinicIds.has(normalized);
    }

    function formatSummaryDateKey(date) {
      if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return '';
      }
      return [
        date.getFullYear(),
        padNumber(date.getMonth() + 1),
        padNumber(date.getDate()),
      ].join('-');
    }

    function formatSummaryDayLabel(date) {
      if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return '';
      }
      const weekday = calendarSummaryWeekdays[date.getDay()] || '';
      return `${weekday} ${padNumber(date.getDate())}/${padNumber(date.getMonth() + 1)}`;
    }

    function getSummaryVetInitials(name, fallbackId) {
      const normalizedName = typeof name === 'string' ? name.trim() : '';
      if (normalizedName) {
        const parts = normalizedName.split(/\s+/).filter(Boolean);
        if (parts.length === 1) {
          const word = parts[0];
          if (word.length >= 2) {
            return (word[0] + word[1]).toLocaleUpperCase('pt-BR');
          }
          return word.charAt(0).toLocaleUpperCase('pt-BR');
        }
        const first = parts[0] ? parts[0].charAt(0) : '';
        const last = parts[parts.length - 1] ? parts[parts.length - 1].charAt(0) : '';
        const combined = `${first}${last}`.trim();
        if (combined) {
          return combined.toLocaleUpperCase('pt-BR');
        }
      }
      const fallback = fallbackId === undefined || fallbackId === null ? '' : String(fallbackId).trim();
      if (fallback) {
        if (fallback.length >= 2) {
          return fallback.slice(-2).toUpperCase();
        }
        return fallback.toUpperCase();
      }
      return '';
    }

    function deriveSummaryVetName(event, fallbackId) {
      if (!event) {
        return fallbackId ? `Profissional ${fallbackId}` : '';
      }
      const extended = event.extendedProps || {};
      const preferredName = extended.veterinarioNome
        || extended.veterinarioName
        || extended.veterinarianName
        || extended.vetName
        || extended.nomeVeterinario;
      if (preferredName) {
        return preferredName;
      }
      const title = typeof event.title === 'string' ? event.title : '';
      if (title.includes(' - ')) {
        const possibleName = title.split(' - ').pop();
        if (possibleName && possibleName.trim()) {
          return possibleName.trim();
        }
      }
      if (fallbackId) {
        return `Profissional ${fallbackId}`;
      }
      return title || '';
    }

    function resolveSummaryColorClass(vetId) {
      if (!vetId) {
        return null;
      }
      if (typeof window !== 'undefined'
        && window.calendarVetColorManager
        && typeof window.calendarVetColorManager.getClass === 'function') {
        return window.calendarVetColorManager.getClass(vetId);
      }
      return null;
    }

    function decorateSummaryItemWithVet(element, vetId) {
      if (!element) {
        return null;
      }
      const normalizedVetId = normalizeSummaryVetId(vetId);
      if (!normalizedVetId) {
        if (element.dataset) {
          delete element.dataset.veterinarioId;
          delete element.dataset.vetId;
        }
        element.removeAttribute('data-veterinario-id');
        return null;
      }

      let colorClass = null;
      if (typeof window !== 'undefined'
        && window.calendarVetColorManager
        && typeof window.calendarVetColorManager.applyClasses === 'function') {
        colorClass = window.calendarVetColorManager.applyClasses(element, normalizedVetId, {
          assignedClass: null,
          clearWhenInvalid: true,
        });
      } else {
        const classesToRemove = Array.from(element.classList).filter((cls) => (
          cls.startsWith('calendar-vet-color-') || cls.startsWith('calendar-vet-')
        ));
        classesToRemove.forEach((cls) => element.classList.remove(cls));
        element.classList.add(`calendar-vet-${normalizedVetId}`);
        colorClass = resolveSummaryColorClass(normalizedVetId);
        if (colorClass) {
          element.classList.add(colorClass);
        }
        if (element.dataset) {
          element.dataset.veterinarioId = normalizedVetId;
        }
        element.setAttribute('data-veterinario-id', normalizedVetId);
      }

      if (element.dataset) {
        element.dataset.vetId = normalizedVetId;
      }

      return colorClass;
    }

    function computeSummaryMetrics(events) {
      const summaryMap = new Map();
      const today = startOfDay(new Date());
      const todayKey = formatSummaryDateKey(today);
      const startOfWeek = today ? new Date(today) : null;
      if (startOfWeek) {
        const weekDayIndex = (startOfWeek.getDay() + 6) % 7;
        startOfWeek.setDate(startOfWeek.getDate() - weekDayIndex);
      }
      const endOfWeek = startOfWeek ? new Date(startOfWeek) : null;
      if (endOfWeek) {
        endOfWeek.setDate(endOfWeek.getDate() + 7);
      }

      (Array.isArray(events) ? events : []).forEach((event) => {
        if (!event || !event.extendedProps) {
          return;
        }
        const vetId = normalizeSummaryVetId(
          event.extendedProps.veterinarioId
          || event.extendedProps.vetId
          || event.extendedProps.veterinarianId
          || event.extendedProps.specialistId
          || event.extendedProps.specialist_id,
        );
        if (!vetId) {
          return;
        }
        if (!isCalendarSummaryVetAllowed(vetId)) {
          return;
        }
        const eventClinicId = event.extendedProps.clinicId
          || event.extendedProps.clinic_id
          || event.extendedProps.clinicaId
          || event.extendedProps.clinica_id;
        if (!isCalendarSummaryClinicAllowed(eventClinicId)) {
          return;
        }
        const name = deriveSummaryVetName(event, vetId);
        const eventDate = startOfDay(parseSummaryDate(event.start || event.startStr || event.date || null));
        const dateKey = formatSummaryDateKey(eventDate);
        const summaryEntry = summaryMap.get(vetId) || {
          vetId,
          vetName: name,
          total: 0,
          today: 0,
          thisWeek: 0,
          days: new Map(),
        };
        summaryEntry.total += 1;
        if (dateKey === todayKey) {
          summaryEntry.today += 1;
        }
        if (eventDate && startOfWeek && endOfWeek && eventDate >= startOfWeek && eventDate < endOfWeek) {
          summaryEntry.thisWeek += 1;
        }
        if (eventDate) {
          const key = formatSummaryDateKey(eventDate);
          const current = summaryEntry.days.get(key) || { date: eventDate, count: 0 };
          current.count += 1;
          summaryEntry.days.set(key, current);
        }
        summaryMap.set(vetId, summaryEntry);
      });

      const rows = Array.from(summaryMap.values()).map((entry) => {
        const days = Array.from(entry.days.values());
        days.sort((a, b) => (a.date && b.date ? a.date - b.date : 0));
        return {
          vetId: entry.vetId,
          vetName: entry.vetName,
          total: entry.total,
          today: entry.today,
          thisWeek: entry.thisWeek,
          days,
        };
      });

      rows.sort((a, b) => {
        if (b.total !== a.total) {
          return b.total - a.total;
        }
        return (a.vetName || '').localeCompare(b.vetName || '', 'pt-BR');
      });

      let totalEvents = 0;
      let totalToday = 0;
      let totalThisWeek = 0;
      rows.forEach((entry) => {
        totalEvents += normalizeSummaryNumber(entry.total);
        totalToday += normalizeSummaryNumber(entry.today);
        totalThisWeek += normalizeSummaryNumber(entry.thisWeek);
      });

      const filters = rows.map((entry) => ({
        vetId: entry.vetId,
        vetName: entry.vetName,
      }));

      return {
        rows,
        totalEvents,
        totalToday,
        totalThisWeek,
        filters,
      };
    }

    function getUpcomingSummaryDays(entry, limit = 3) {
      const days = Array.isArray(entry?.days) ? entry.days.filter(Boolean) : [];
      days.sort((a, b) => a.date - b.date);
      const today = startOfDay(new Date());
      const future = today ? days.filter((item) => item.date >= today) : days;
      const source = future.length ? future : days;
      return source.slice(0, limit);
    }

    function refreshCalendarSummaryActiveState() {
      if (!calendarSummaryList) {
        return;
      }
      const items = calendarSummaryList.querySelectorAll('.calendar-summary-item');
      items.forEach((element) => {
        const elementVetId = normalizeSummaryVetId(
          element && element.dataset ? element.dataset.vetId : null,
        );
        if (activeCalendarSummaryVetId && elementVetId === activeCalendarSummaryVetId) {
          element.classList.add('is-active');
        } else {
          element.classList.remove('is-active');
        }
      });
      if (calendarSummaryFilters) {
        const filterButtons = calendarSummaryFilters.querySelectorAll('[data-vet-id]');
        filterButtons.forEach((button) => {
          const buttonVetId = normalizeSummaryVetId(
            button && button.dataset ? button.dataset.vetId : null,
          );
          const isActive = Boolean(
            activeCalendarSummaryVetId
            && buttonVetId
            && buttonVetId === activeCalendarSummaryVetId,
          );
          button.classList.toggle('is-active', isActive);
          button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
      }
    }

    function setActiveCalendarSummaryItem(vetId) {
      activeCalendarSummaryVetId = vetId ? normalizeSummaryVetId(vetId) : null;
      refreshCalendarSummaryActiveState();
    }

    function handleCalendarSummarySelection(rawVetId) {
      const normalizedVetId = normalizeSummaryVetId(rawVetId);
      const isCurrentlyActive = Boolean(
        activeCalendarSummaryVetId !== null
        && normalizedVetId !== null
        && normalizedVetId === activeCalendarSummaryVetId,
      );
      const nextActiveVetId = isCurrentlyActive ? null : normalizedVetId;
      setActiveCalendarSummaryItem(nextActiveVetId);
      if (typeof window.updateCalendarVetSelection === 'function') {
        window.updateCalendarVetSelection(nextActiveVetId, { activate: true, refetch: true });
      }
    }

    function setCalendarSummaryLoadingState(isLoading) {
      if (!calendarSummaryPanel) {
        return;
      }
      const shouldActivate = !!isLoading;
      calendarSummaryPanel.classList.toggle('is-loading', shouldActivate);
      calendarSummaryPanel.setAttribute('aria-busy', shouldActivate ? 'true' : 'false');
      if (calendarSummaryLoading) {
        calendarSummaryLoading.classList.toggle('d-none', !shouldActivate);
      }
      if (calendarSummaryList) {
        calendarSummaryList.classList.toggle('is-disabled', shouldActivate);
      }
      if (calendarSummaryOverview) {
        calendarSummaryOverview.classList.toggle('is-disabled', shouldActivate);
      }
      if (shouldActivate && calendarSummaryEmpty) {
        calendarSummaryEmpty.classList.add('d-none');
      }
      if (calendarSummaryFilters) {
        calendarSummaryFilters.classList.toggle('is-disabled', shouldActivate);
        const filterButtons = calendarSummaryFilters.querySelectorAll('button');
        filterButtons.forEach((button) => {
          button.disabled = shouldActivate;
        });
      }
    }

    function clearCalendarSummaryFilters() {
      if (!calendarSummaryFilters) {
        return;
      }
      calendarSummaryFilters.innerHTML = '';
      calendarSummaryFilters.classList.add('d-none');
    }

    function renderCalendarSummaryFilters(rows) {
      if (!calendarSummaryFilters) {
        return;
      }
      calendarSummaryFilters.innerHTML = '';
      const entries = Array.isArray(rows) ? rows.filter(Boolean) : [];
      if (!entries.length) {
        calendarSummaryFilters.classList.add('d-none');
        return;
      }
      calendarSummaryFilters.classList.remove('d-none');
      calendarSummaryFilters.classList.remove('is-disabled');
      entries.forEach((entry) => {
        const filterButton = document.createElement('button');
        filterButton.type = 'button';
        filterButton.classList.add('calendar-summary-filter');
        decorateSummaryItemWithVet(filterButton, entry.vetId);
        const normalizedId = normalizeSummaryVetId(entry.vetId);
        if (normalizedId) {
          filterButton.dataset.vetId = normalizedId;
        }
        const vetLabel = entry.vetName || `Profissional ${entry.vetId}`;
        filterButton.setAttribute('aria-label', `Filtrar agenda por ${vetLabel}`);
        filterButton.setAttribute('title', vetLabel);
        filterButton.setAttribute('aria-pressed', 'false');
        filterButton.disabled = false;

        const icon = document.createElement('span');
        icon.classList.add('calendar-summary-filter-icon');
        icon.setAttribute('aria-hidden', 'true');
        const initials = getSummaryVetInitials(vetLabel, entry.vetId);
        icon.textContent = initials || '•';
        filterButton.appendChild(icon);

        const srLabel = document.createElement('span');
        srLabel.classList.add('visually-hidden');
        srLabel.textContent = vetLabel;
        filterButton.appendChild(srLabel);

        calendarSummaryFilters.appendChild(filterButton);
      });
    }

    function renderCalendarSummary(events) {
      if (!calendarSummaryPanel || !calendarSummaryList) {
        return;
      }
      const { rows, totalEvents, totalToday, totalThisWeek, filters } = computeSummaryMetrics(events);
      setCalendarSummaryLoadingState(false);
      if (calendarSummaryTotalBadge) {
        calendarSummaryTotalBadge.textContent = String(totalEvents);
      }
      calendarSummaryList.innerHTML = '';
      if (!rows.length) {
        if (calendarSummaryEmpty) {
          calendarSummaryEmpty.classList.remove('d-none');
        }
        calendarSummaryPanel.classList.remove('has-data');
        if (calendarSummaryOverview) {
          calendarSummaryOverview.setAttribute('hidden', 'hidden');
        }
        clearCalendarSummaryFilters();
        return;
      }
      calendarSummaryPanel.classList.add('has-data');
      if (calendarSummaryEmpty) {
        calendarSummaryEmpty.classList.add('d-none');
      }
      if (calendarSummaryOverview) {
        calendarSummaryOverview.removeAttribute('hidden');
        if (calendarSummaryOverviewToday) {
          calendarSummaryOverviewToday.textContent = String(totalToday);
        }
        if (calendarSummaryOverviewWeek) {
          calendarSummaryOverviewWeek.textContent = String(totalThisWeek);
        }
      }

      renderCalendarSummaryFilters(filters);

      rows.forEach((entry) => {
        const item = document.createElement('li');
        item.classList.add('calendar-summary-item');
        decorateSummaryItemWithVet(item, entry.vetId);

        const header = document.createElement('header');
        header.classList.add('calendar-summary-header');

        const nameWrapper = document.createElement('div');
        nameWrapper.classList.add('calendar-summary-name');
        const bullet = document.createElement('span');
        bullet.classList.add('calendar-summary-bullet');
        nameWrapper.appendChild(bullet);
        const nameText = document.createElement('span');
        nameText.textContent = entry.vetName || `Profissional ${entry.vetId}`;
        nameWrapper.appendChild(nameText);
        header.appendChild(nameWrapper);

        const totalBadge = document.createElement('span');
        totalBadge.classList.add('calendar-summary-total');
        const totalLabel = document.createElement('span');
        totalLabel.classList.add('label');
        totalLabel.textContent = 'Total';
        const totalValue = document.createElement('span');
        totalValue.classList.add('value');
        totalValue.textContent = String(entry.total);
        totalBadge.appendChild(totalLabel);
        totalBadge.appendChild(totalValue);
        header.appendChild(totalBadge);

        item.appendChild(header);

        const metrics = document.createElement('ul');
        metrics.classList.add('calendar-summary-metrics');
        metrics.setAttribute('role', 'list');
        const todayMetric = document.createElement('li');
        todayMetric.classList.add('metric');
        todayMetric.append('Hoje: ');
        const todayValue = document.createElement('strong');
        todayValue.textContent = String(entry.today);
        todayMetric.appendChild(todayValue);
        metrics.appendChild(todayMetric);

        const weekMetric = document.createElement('li');
        weekMetric.classList.add('metric');
        weekMetric.append('Semana: ');
        const weekValue = document.createElement('strong');
        weekValue.textContent = String(entry.thisWeek);
        weekMetric.appendChild(weekValue);
        metrics.appendChild(weekMetric);

        item.appendChild(metrics);

        const upcomingDays = getUpcomingSummaryDays(entry);
        if (upcomingDays.length) {
          const dayList = document.createElement('ul');
          dayList.classList.add('calendar-summary-days');
          dayList.setAttribute('role', 'list');
          upcomingDays.forEach((dayInfo) => {
            const dayItem = document.createElement('li');
            dayItem.classList.add('calendar-summary-day');
            const label = document.createElement('span');
            label.classList.add('label');
            label.textContent = formatSummaryDayLabel(dayInfo.date);
            const count = document.createElement('span');
            count.classList.add('count');
            count.textContent = String(dayInfo.count);
            dayItem.appendChild(label);
            dayItem.appendChild(count);
            dayList.appendChild(dayItem);
          });
          item.appendChild(dayList);
        }

        calendarSummaryList.appendChild(item);
      });

      refreshCalendarSummaryActiveState();
    }

    setCalendarSummaryCollapsed(isCalendarSummaryCollapsed, { store: false });

    setCalendarSummaryLoadingState(true);
    const initialEvents = Array.isArray(window.sharedCalendarEvents)
      ? window.sharedCalendarEvents
      : [];
    if (initialEvents.length) {
      renderCalendarSummary(initialEvents);
    }
    document.addEventListener('sharedCalendarEvents', (event) => {
      const items = (event && event.detail && event.detail.events) || [];
      renderCalendarSummary(items);
    });
    document.addEventListener('sharedCalendarEventsLoading', (event) => {
      const isLoading = !!(event && event.detail && event.detail.loading);
      setCalendarSummaryLoadingState(isLoading);
    });

    if (calendarSummaryList) {
      calendarSummaryList.addEventListener('click', (event) => {
        const isTextNode = typeof Node !== 'undefined'
          && event.target
          && event.target.nodeType === Node.TEXT_NODE;
        const origin = isTextNode ? event.target.parentElement : event.target;
        const targetItem = origin && typeof origin.closest === 'function'
          ? origin.closest('.calendar-summary-item')
          : null;
        if (!targetItem || !calendarSummaryList.contains(targetItem)) {
          return;
        }
        const rawVetId = targetItem.dataset ? targetItem.dataset.vetId : null;
        handleCalendarSummarySelection(rawVetId);
      });
    }

    if (calendarSummaryFilters) {
      calendarSummaryFilters.addEventListener('click', (event) => {
        const origin = event.target && typeof event.target.closest === 'function'
          ? event.target.closest('[data-vet-id]')
          : null;
        if (!origin || !calendarSummaryFilters.contains(origin) || origin.disabled) {
          return;
        }
        const rawVetId = origin.dataset ? origin.dataset.vetId : null;
        handleCalendarSummarySelection(rawVetId);
      });
    }
  };

  if (!waitForDomContentLoaded || document.readyState !== 'loading') {
    initialize();
  } else {
    document.addEventListener('DOMContentLoaded', initialize, { once: true });
  }
}

export default setupAppointmentsCalendarSummary;
