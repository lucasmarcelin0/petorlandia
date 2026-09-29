(() => {
  const form = document.querySelector("[data-step-form]");
  if (!form) return;

  const panels = Array.from(form.querySelectorAll("[data-step-panel]"));
  const dots = Array.from(document.querySelectorAll("[data-step-target]"));
  const previous = form.querySelector("[data-previous]");
  const next = form.querySelector("[data-next]");
  const submit = form.querySelector("[data-submit]");
  const progressFill = document.querySelector("[data-progress-fill]");
  const progressLabel = document.querySelector("[data-progress-label]");
  const progressTrack = document.querySelector("[data-progress-track]");
  const stepLabel = document.querySelector("[data-step-label]");
  if (!panels.length) return;

  const visited = new Set([0]);
  let current = 0;

  function showStep(index, focusHeading = false) {
    current = Math.max(0, Math.min(panels.length - 1, index));
    panels.forEach((panel, position) => {
      const active = position === current;
      panel.hidden = !active;
      panel.setAttribute("aria-hidden", active ? "false" : "true");
    });
    dots.forEach((dot, position) => {
      dot.classList.toggle("is-current", position === current);
      dot.classList.toggle("is-visited", visited.has(position) && position !== current);
      dot.setAttribute("aria-current", position === current ? "step" : "false");
    });
    const percent = panels.length < 2 ? 100 : Math.round((current / (panels.length - 1)) * 100);
    if (progressFill) progressFill.style.width = `${percent}%`;
    if (progressLabel) progressLabel.textContent = `${percent}%`;
    if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(percent));
    if (stepLabel) stepLabel.textContent = `Etapa ${current + 1} de ${panels.length}`;
    if (previous) previous.disabled = current === 0;
    if (next) next.hidden = current === panels.length - 1;
    if (submit) submit.hidden = current !== panels.length - 1;
    if (focusHeading) {
      const heading = panels[current].querySelector("h2");
      heading?.setAttribute("tabindex", "-1");
      heading?.focus({ preventScroll: true });
      panels[current].scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  previous?.addEventListener("click", () => showStep(current - 1, true));
  next?.addEventListener("click", () => {
    visited.add(current);
    visited.add(current + 1);
    showStep(current + 1, true);
  });
  dots.forEach((dot) => dot.addEventListener("click", () => {
    const target = Number(dot.dataset.stepTarget);
    if (Number.isInteger(target)) {
      visited.add(target);
      showStep(target, true);
    }
  }));

  form.addEventListener("submit", (event) => {
    const invalid = Array.from(form.elements).find((control) => control.willValidate && !control.checkValidity());
    if (invalid) {
      event.preventDefault();
      const panel = invalid.closest("[data-step-panel]");
      const index = Number(panel?.dataset.stepPanel || 0);
      visited.add(index);
      showStep(index, true);
      window.setTimeout(() => invalid.reportValidity(), 180);
      return;
    }
    if (submit) {
      submit.disabled = true;
      submit.innerHTML = 'Enviando ficha <span aria-hidden="true">…</span>';
    }
  });

  // Sugestões de município: ao escolher uma opção da lista, completa o código IBGE e a UF
  // apenas se estiverem vazios. A digitação livre continua valendo.
  const sugestoes = Array.from(document.querySelectorAll("#sugestoes-municipio option"));
  form.querySelectorAll("[data-municipio-sugerido]").forEach((campo) => {
    campo.addEventListener("change", () => {
      const escolhida = sugestoes.find((o) => o.value.toLowerCase() === campo.value.trim().toLowerCase());
      if (!escolhida) return;
      campo.value = escolhida.value;
      const codigo = document.getElementById(campo.dataset.codigoAlvo);
      if (codigo && !codigo.value.trim()) codigo.value = escolhida.dataset.codigo;
      const uf = form.querySelector(`[name="${campo.name.replace("municipio_", "uf_")}"]`);
      if (uf && !uf.value.trim()) uf.value = escolhida.dataset.uf;
    });
  });

  form.dataset.ready = "true";
  showStep(0);
})();
