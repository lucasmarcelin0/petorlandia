document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("fiscal-settings-form");
  const cnpjInput = document.getElementById("cnpj");
  const ufInput = document.getElementById("uf");

  if (!form) {
    return;
  }

  form.addEventListener("submit", (event) => {
    const cnpjDigits = (cnpjInput?.value || "").replace(/\D/g, "");
    if (cnpjDigits && cnpjDigits.length !== 14) {
      event.preventDefault();
      cnpjInput.focus();
      alert("Informe um CNPJ válido com 14 dígitos.");
      return;
    }

    if (ufInput && ufInput.value && ufInput.value.length !== 2) {
      event.preventDefault();
      ufInput.focus();
      alert("Informe uma UF válida.");
    }
  });
});
