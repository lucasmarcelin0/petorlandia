(function () {
  function formatCnpj(value) {
    const digits = String(value || "").replace(/\D/g, "").slice(0, 14);

    if (digits.length <= 2) return digits;
    if (digits.length <= 5) return `${digits.slice(0, 2)}.${digits.slice(2)}`;
    if (digits.length <= 8) return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5)}`;
    if (digits.length <= 12) {
      return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8)}`;
    }
    return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8, 12)}-${digits.slice(12)}`;
  }

  function applyMask(input) {
    if (!input) {
      return;
    }

    const updateValue = () => {
      input.value = formatCnpj(input.value);
    };

    input.addEventListener("input", updateValue);
    updateValue();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-cnpj-mask]").forEach(applyMask);
  });
})();
