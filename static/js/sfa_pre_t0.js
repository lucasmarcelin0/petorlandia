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

  // CEP: busca UF, município (com código IBGE), bairro e rua no servidor, que
  // consulta o ViaCEP. Só preenche campos vazios ou preenchidos pela busca
  // anterior, para nunca apagar o que a pessoa digitou.
  const cep = form.querySelector('[name="cep"]');
  const cepStatus = form.querySelector("[data-cep-status]");
  const cepUrl = form.dataset.cepUrl;
  if (cep && cepUrl) {
    let ultimoCep = "";
    const destinos = {
      uf: "uf_residencia",
      municipio: "municipio_residencia",
      codigo_ibge: "codigo_municipio_residencia",
      bairro: "bairro",
      logradouro: "logradouro",
    };
    const avisar = (texto, classe) => {
      if (!cepStatus) return;
      cepStatus.textContent = texto;
      cepStatus.classList.toggle("is-ok", classe === "ok");
      cepStatus.classList.toggle("is-erro", classe === "erro");
    };
    const buscarCep = async () => {
      const digitos = cep.value.replace(/\D/g, "");
      if (digitos.length !== 8 || digitos === ultimoCep) return;
      ultimoCep = digitos;
      avisar("Buscando o endereço do CEP…");
      try {
        const resposta = await fetch(cepUrl.replace("00000000", digitos), { headers: { Accept: "application/json" } });
        const dados = await resposta.json();
        if (!dados.ok) {
          avisar(dados.motivo || "CEP não encontrado.", "erro");
          return;
        }
        const preenchidos = [];
        Object.entries(destinos).forEach(([origem, nome]) => {
          const campo = form.querySelector(`[name="${nome}"]`);
          const valor = dados.endereco[origem] || "";
          if (!campo || !valor) return;
          if (campo.value.trim() && campo.value !== campo.dataset.cepValor) return;
          campo.value = valor;
          campo.dataset.cepValor = valor;
          campo.dispatchEvent(new Event("input", { bubbles: true }));
          preenchidos.push(nome);
        });
        avisar(preenchidos.length
          ? "Endereço preenchido pelo CEP. Confira e complete o número."
          : "CEP encontrado; os campos de endereço já estavam preenchidos.", "ok");
      } catch (erro) {
        ultimoCep = "";
        avisar("Não foi possível consultar o CEP agora. Preencha o endereço à mão.", "erro");
      }
    };
    cep.addEventListener("input", buscarCep);
    cep.addEventListener("change", buscarCep);
  }

  form.dataset.ready = "true";
  showStep(0);
  marcarPendencias();
})();
