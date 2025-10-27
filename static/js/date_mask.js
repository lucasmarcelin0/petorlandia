(function (global) {
  const MASK_DIGITS_REGEX = /\D/g;

  function applyDateMask(value) {
    const digits = (value || "").replace(MASK_DIGITS_REGEX, "");
    let formatted = "";

    if (digits.length > 0) {
      formatted = digits.slice(0, 2);
    }
    if (digits.length >= 3) {
      formatted += "/" + digits.slice(2, 4);
    }
    if (digits.length >= 5) {
      formatted += "/" + digits.slice(4, 8);
    }

    return formatted;
  }

  function digitsToIso(digits) {
    if (digits.length !== 8) return null;
    const day = digits.slice(0, 2);
    const month = digits.slice(2, 4);
    const year = digits.slice(4, 8);
    return `${year}-${month}-${day}`;
  }

  function syncMaskedInput(instance, callbacks = {}) {
    if (!instance || !instance.altInput) return () => {};

    const { onDateSync, onClear } = callbacks;
    const alt = instance.altInput;

    const updateFromDigits = (digits) => {
      if (digits.length === 8) {
        const iso = digitsToIso(digits);
        if (!iso) return;
        if (instance.input.value !== iso) {
          const parsed = instance.parseDate(iso, "Y-m-d");
          if (parsed) {
            instance.setDate(parsed, true);
          }
        }
        const date = instance.selectedDates[0];
        if (date) {
          onDateSync?.(date);
        }
      } else if (digits.length === 0) {
        if (instance.input.value) {
          instance.clear();
        }
        onClear?.();
      }
    };

    const handleInput = () => {
      const masked = applyDateMask(alt.value);
      if (masked !== alt.value) {
        alt.value = masked;
        if (document.activeElement === alt) {
          const position = masked.length;
          requestAnimationFrame(() => {
            alt.setSelectionRange(position, position);
          });
        }
      }
      updateFromDigits(masked.replace(MASK_DIGITS_REGEX, ""));
    };

    const confirmInput = () => {
      const digits = alt.value.replace(MASK_DIGITS_REGEX, "");
      updateFromDigits(digits);
    };

    const handleKeyDown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        confirmInput();
        instance.close();
      }
    };

    alt.addEventListener("input", handleInput);
    alt.addEventListener("blur", confirmInput);
    alt.addEventListener("keydown", handleKeyDown);

    return () => {
      alt.removeEventListener("input", handleInput);
      alt.removeEventListener("blur", confirmInput);
      alt.removeEventListener("keydown", handleKeyDown);
    };
  }

  global.DateMaskUtils = {
    applyDateMask,
    syncMaskedInput,
  };
})(window);
