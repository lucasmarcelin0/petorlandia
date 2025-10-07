(function(window) {
  function queryElement(base, selectorOrElement) {
    if (!selectorOrElement) return null;
    if (selectorOrElement instanceof Element) return selectorOrElement;
    if (typeof selectorOrElement === 'string') {
      return base.querySelector(selectorOrElement);
    }
    return null;
  }

  function applyMask(value) {
    const digits = value.replace(/\D/g, '');
    let formatted = '';

    if (digits.length > 0) {
      formatted = digits.slice(0, 2);
    }
    if (digits.length >= 3) {
      formatted += '/' + digits.slice(2, 4);
    }
    if (digits.length >= 5) {
      formatted += '/' + digits.slice(4, 8);
    }

    return formatted;
  }

  function computeYearsFromDate(date) {
    const today = new Date();
    let years = today.getFullYear() - date.getFullYear();
    const monthDiff = today.getMonth() - date.getMonth();

    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < date.getDate())) {
      years--;
    }

    return years;
  }

  function setupDobAgeSync(options = {}) {
    const context = options.context || document;
    const dobInput = options.dobInput || queryElement(context, options.dobSelector);

    if (!dobInput) {
      return null;
    }

    if (typeof window.flatpickr !== 'function') {
      console.warn('setupDobAgeSync: flatpickr is required but was not found on window');
      return null;
    }

    const ageInput = options.ageInput || queryElement(context, options.ageSelector);
    const formatAge = typeof options.formatAge === 'function'
      ? options.formatAge
      : (years) => (years == null ? '' : String(years));
    const onAgeUpdate = typeof options.onAgeUpdate === 'function' ? options.onAgeUpdate : null;
    const allowAgeInput = options.allowAgeInput !== undefined
      ? options.allowAgeInput
      : Boolean(ageInput && !ageInput.disabled && !ageInput.readOnly);
    const clampAge = options.clampAge !== undefined ? options.clampAge : true;

    if (dobInput._flatpickr) {
      dobInput._flatpickr.destroy();
    }

    const updateAge = (date) => {
      const metadata = {
        ageInput,
        date: date || null,
        rawYears: null,
        years: null,
      };

      if (!date) {
        if (ageInput) {
          const formatted = formatAge(null, metadata);
          if (formatted !== undefined) {
            ageInput.value = formatted == null ? '' : String(formatted);
          }
        }
        if (onAgeUpdate) {
          onAgeUpdate(null, metadata);
        }
        return;
      }

      const rawYears = computeYearsFromDate(date);
      const years = clampAge ? Math.max(rawYears, 0) : rawYears;
      metadata.rawYears = rawYears;
      metadata.years = years;

      if (ageInput) {
        const formatted = formatAge(years, metadata);
        if (formatted !== undefined) {
          ageInput.value = formatted == null ? '' : String(formatted);
        }
      }

      if (onAgeUpdate) {
        onAgeUpdate(years, metadata);
      }
    };

    const picker = window.flatpickr(dobInput, {
      locale: options.locale || 'pt',
      dateFormat: options.dateFormat || 'Y-m-d',
      altInput: options.altInput !== undefined ? options.altInput : true,
      altFormat: options.altFormat || 'd/m/Y',
      allowInput: options.allowInput !== undefined ? options.allowInput : true,
      maxDate: options.maxDate !== undefined ? options.maxDate : 'today',
      defaultDate: dobInput.value || options.defaultDate || null,
      disableMobile: options.disableMobile !== undefined ? options.disableMobile : true,
      onReady(selectedDates, _dateStr, instance) {
        const alt = instance.altInput;
        if (alt) {
          alt.inputMode = 'numeric';
          alt.autocomplete = 'off';
          alt.placeholder = options.altPlaceholder || 'dd/mm/aaaa';

          alt.addEventListener('input', () => {
            const masked = applyMask(alt.value);
            if (masked !== alt.value) {
              alt.value = masked;
              const newPosition = masked.length;
              alt.setSelectionRange(newPosition, newPosition);
            }
          });

          const syncTypedDate = () => {
            const digits = alt.value.replace(/\D/g, '');
            if (digits.length === 8) {
              const day = digits.slice(0, 2);
              const month = digits.slice(2, 4);
              const year = digits.slice(4, 8);
              instance.setDate(`${year}-${month}-${day}`, true, 'Y-m-d');
            } else if (digits.length === 0) {
              instance.clear();
            }
          };

          alt.addEventListener('blur', syncTypedDate);
          alt.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              syncTypedDate();
              instance.close();
            }
          });
        }

        if (selectedDates.length) {
          updateAge(selectedDates[0]);
        } else if (dobInput.value) {
          const parsed = instance.parseDate(dobInput.value, instance.config.dateFormat);
          if (parsed) {
            updateAge(parsed);
          }
        } else {
          updateAge(null);
        }
      },
      onChange(selectedDates) {
        updateAge(selectedDates[0] || null);
      },
      onValueUpdate(selectedDates) {
        if (!selectedDates.length) {
          updateAge(null);
        }
      },
      onClose(selectedDates) {
        if (!selectedDates.length && !dobInput.value) {
          updateAge(null);
        }
      },
    });

    if (ageInput && allowAgeInput) {
      ageInput.addEventListener('input', () => {
        const raw = parseInt(ageInput.value, 10);
        if (Number.isNaN(raw)) {
          return;
        }
        const clamped = clampAge ? Math.max(raw, 0) : raw;
        const today = new Date();
        const estimate = new Date(today.getFullYear() - clamped, today.getMonth(), today.getDate());
        picker.setDate(estimate, true);
      });
    }

    return {
      picker,
      updateAge,
      clear() {
        picker.clear();
      },
      destroy() {
        picker.destroy();
      },
    };
  }

  window.setupDobAgeSync = setupDobAgeSync;
})(window);
