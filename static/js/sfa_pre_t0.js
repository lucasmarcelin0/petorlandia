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

  // Etapas com campo obrigatório ainda vazio ganham um aviso na barra, para
  // ninguém descobrir só no fim qual passo faltou.
  const dotLabels = dots.map((dot) => dot.getAttribute("aria-label") || "");
  function marcarPendencias() {
    panels.forEach((panel, position) => {
      const dot = dots[position];
      if (!dot) return;
      const pendente = Array.from(panel.querySelectorAll("input, select, textarea"))
        .some((control) => control.required && control.willValidate && !control.checkValidity());
      dot.classList.toggle("has-pending", pendente);
      dot.setAttribute("aria-label", pendente ? `${dotLabels[position]} (campo obrigatório pendente)` : dotLabels[position]);
      dot.title = pendente ? "Esta etapa tem campo obrigatório pendente" : "";
    });
  }
  form.addEventListener("input", marcarPendencias);
  form.addEventListener("change", marcarPendencias);

  // Exames: só os coletados mostram data e resultado.
  const escolha = form.querySelector("[data-exames-escolha]");
  if (escolha) {
    const caixas = Array.from(escolha.querySelectorAll('input[name="exames_realizados"]'));
    const nenhum = escolha.querySelector("[data-exame-nenhum]");
    const cartoes = Array.from(form.querySelectorAll("[data-exames]"));
    const aplicarExames = () => {
      const marcados = new Set(caixas.filter((caixa) => caixa.checked && caixa !== nenhum).map((caixa) => caixa.value));
      cartoes.forEach((cartao) => {
        cartao.hidden = !cartao.dataset.exames.split(" ").some((id) => marcados.has(id));
      });
    };
    escolha.addEventListener("change", (event) => {
      if (event.target === nenhum && nenhum.checked) {
        caixas.forEach((caixa) => { if (caixa !== nenhum) caixa.checked = false; });
      } else if (event.target !== nenhum && event.target.checked && nenhum) {
        nenhum.checked = false;
      }
      aplicarExames();
    });
    aplicarExames();
  }

  form.dataset.ready = "true";
  showStep(0);
  marcarPendencias();
})();
