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

  // Sugestões (município, unidade notificante, hospital): ao escolher uma opção da lista,
  // completa código, UF e telefone apenas se estiverem vazios. A digitação livre continua valendo.
  form.querySelectorAll("[data-sugestao]").forEach((campo) => {
    const opcoes = Array.from(document.querySelectorAll(`#${campo.getAttribute("list")} option`));
    campo.addEventListener("change", () => {
      const escolhida = opcoes.find((o) => o.value.toLowerCase() === campo.value.trim().toLowerCase());
      if (!escolhida) return;
      campo.value = escolhida.value;
      const preencher = (id, valor) => {
        const alvo = id && document.getElementById(id);
        if (alvo && valor && !alvo.value.trim()) alvo.value = valor;
      };
      preencher(campo.dataset.codigoAlvo, escolhida.dataset.codigo);
      preencher(campo.dataset.telefoneAlvo, escolhida.dataset.telefone);
      if (escolhida.dataset.uf) {
        const uf = form.querySelector(`[name="${campo.name.replace("municipio_", "uf_")}"]`);
        if (uf && !uf.value.trim()) uf.value = escolhida.dataset.uf;
      }
    });
  });

  // Data de nascimento <-> idade: preencher um atualiza o outro (vale o último campo editado).
  // A data derivada da idade é só uma estimativa e vem sinalizada para o usuário corrigir.
  const nascimento = document.getElementById("input-data_nascimento");
  const idadeValor = document.getElementById("input-idade_valor");
  const idadeUnidade = document.getElementById("input-idade_unidade");
  if (nascimento && idadeValor && idadeUnidade) {
    const aviso = document.createElement("p");
    aviso.className = "field-hint";
    aviso.hidden = true;
    aviso.textContent = "Data estimada a partir da idade. Corrija se souber a data real.";
    nascimento.insertAdjacentElement("afterend", aviso);
    const pad = (n) => String(n).padStart(2, "0");
    const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const hoje = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()); };

    const idadeDaData = () => {
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(nascimento.value);
      if (!m) return;
      const nasc = new Date(+m[1], +m[2] - 1, +m[3]);
      const ref = hoje();
      if (nasc > ref) return;
      let anos = ref.getFullYear() - nasc.getFullYear();
      if (ref.getMonth() < nasc.getMonth() || (ref.getMonth() === nasc.getMonth() && ref.getDate() < nasc.getDate())) anos -= 1;
      if (anos >= 1) { idadeValor.value = anos; idadeUnidade.value = "4"; return; }
      let meses = (ref.getFullYear() - nasc.getFullYear()) * 12 + ref.getMonth() - nasc.getMonth();
      if (ref.getDate() < nasc.getDate()) meses -= 1;
      if (meses >= 1) { idadeValor.value = meses; idadeUnidade.value = "3"; return; }
      idadeValor.value = Math.round((ref - nasc) / 86400000);
      idadeUnidade.value = "2";
    };

    const dataDaIdade = () => {
      const n = parseInt(idadeValor.value, 10);
      const un = idadeUnidade.value;
      if (!Number.isFinite(n) || n < 0 || !un) return;
      const d = hoje();
      if (un === "4") d.setFullYear(d.getFullYear() - n);
      else if (un === "3") d.setMonth(d.getMonth() - n);
      else if (un === "2") d.setDate(d.getDate() - n);
      nascimento.value = iso(d);
      aviso.hidden = false;
    };

    nascimento.addEventListener("change", () => { aviso.hidden = true; idadeDaData(); });
    idadeValor.addEventListener("input", dataDaIdade);
    idadeUnidade.addEventListener("change", dataDaIdade);
  }

  form.dataset.ready = "true";
  showStep(0);
})();
