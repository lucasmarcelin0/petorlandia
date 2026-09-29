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

  // Sexo masculino: esconde "Gestante" e registra 6 (Não se aplica), o código da própria ficha.
  // Ao voltar para F/I, o campo reaparece com a resposta que estava antes.
  const cartaoGestante = form.querySelector('[data-field-card="gestante"]');
  const sexoRadios = Array.from(form.querySelectorAll('input[name="sexo"]'));
  if (cartaoGestante && sexoRadios.length) {
    const gestanteRadios = Array.from(cartaoGestante.querySelectorAll('input[name="gestante"]'));
    let anterior = null;
    const aplicarSexo = () => {
      const masculino = sexoRadios.some((r) => r.checked && r.value === "M");
      if (masculino && cartaoGestante.style.display !== "none") {
        anterior = gestanteRadios.find((r) => r.checked) || null;
        cartaoGestante.style.display = "none";
        const naoSeAplica = gestanteRadios.find((r) => r.value === "6");
        if (naoSeAplica) naoSeAplica.checked = true;
      } else if (!masculino && cartaoGestante.style.display === "none") {
        cartaoGestante.style.display = "";
        const escolha = anterior;
        gestanteRadios.forEach((r) => { r.checked = r === escolha; });
        anterior = null;
      }
    };
    sexoRadios.forEach((r) => r.addEventListener("change", aplicarSexo));
    aplicarSexo();
  }

  // CEP: ao completar 8 dígitos, consulta /api/cep (mesmo domínio) e preenche logradouro, bairro,
  // município, código IBGE e UF da residência. Só preenche o que está vazio; digitação livre segue valendo.
  const campoCep = document.getElementById("input-cep");
  if (campoCep && typeof fetch === "function") {
    let ultimoCep = "";
    const sugestoesMunicipio = Array.from(document.querySelectorAll("#sugestoes-municipio option"));
    const preencherVazio = (id, valor) => {
      const alvo = document.getElementById(id);
      if (alvo && valor && !alvo.value.trim()) alvo.value = String(valor).slice(0, alvo.maxLength > 0 ? alvo.maxLength : undefined);
    };
    const consultarCep = async () => {
      const cep = campoCep.value.replace(/\D/g, "");
      if (cep.length !== 8 || cep === ultimoCep) return;
      ultimoCep = cep;
      try {
        const resposta = await fetch(`/api/cep/${cep}`, { headers: { Accept: "application/json" } });
        if (!resposta.ok) return;
        const corpo = await resposta.json();
        const d = corpo && corpo.success && corpo.data;
        if (!d) return;
        preencherVazio("input-logradouro", d.logradouro);
        preencherVazio("input-bairro", d.bairro);
        preencherVazio("input-municipio_residencia", d.localidade);
        preencherVazio("input-uf_residencia", (d.uf || "").toUpperCase());
        const conhecida = sugestoesMunicipio.find((o) => o.value.toLowerCase() === String(d.localidade || "").toLowerCase());
        if (conhecida) preencherVazio("input-codigo_municipio_residencia", conhecida.dataset.codigo);
      } catch (erro) {
        ultimoCep = "";
      }
    };
    campoCep.addEventListener("input", consultarCep);
    campoCep.addEventListener("change", consultarCep);
  }

  // Caso autóctone do município de residência (56 = Sim): copia UF, país, município, código IBGE,
  // distrito e bairro da residência para o local provável de infecção. Só preenche campos vazios.
  const autoctone = Array.from(form.querySelectorAll('input[name="caso_autoctone"]'));
  if (autoctone.length) {
    const valor = (nome) => { const el = form.querySelector(`[name="${nome}"]`); return el ? el.value.trim() : ""; };
    const preencherInfeccao = (nome, texto) => {
      const el = form.querySelector(`[name="${nome}"]`);
      if (el && texto && !el.value.trim()) el.value = texto;
    };
    const copiarResidencia = () => {
      if (!autoctone.some((r) => r.checked && r.value === "1")) return;
      preencherInfeccao("uf_local_infeccao", valor("uf_residencia"));
      preencherInfeccao("pais_local_infeccao", valor("pais_residencia") || "Brasil");
      // Município e código IBGE andam juntos: o código só é copiado se o município for o mesmo.
      const municipioLocal = valor("municipio_local_infeccao");
      if (!municipioLocal || municipioLocal.toLowerCase() === valor("municipio_residencia").toLowerCase()) {
        preencherInfeccao("municipio_local_infeccao", valor("municipio_residencia"));
        preencherInfeccao("codigo_municipio_local_infeccao", valor("codigo_municipio_residencia"));
      }
      preencherInfeccao("distrito_local_infeccao", valor("distrito_residencia"));
      preencherInfeccao("bairro_local_infeccao", valor("bairro"));
    };
    autoctone.forEach((r) => r.addEventListener("change", copiarResidencia));
  }

  // Sinais de alarme / dengue grave: com resposta "Não" (2), esconde a lista de sinais e a data de início.
  // O que estava marcado é guardado e limpo (nada contraditório é enviado) e volta se a resposta mudar.
  [["sinais_alarme", "data_inicio_sinais_alarme"], ["dengue_grave", "data_inicio_sinais_gravidade"]].forEach(([chave, chaveData]) => {
    const cartao = form.querySelector(`[data-field-card="${chave}"]`);
    if (!cartao) return;
    const cartaoData = form.querySelector(`[data-field-card="${chaveData}"]`);
    const radios = Array.from(cartao.querySelectorAll(`input[type="radio"][name="${chave}"]`));
    const blocos = Array.from(cartao.querySelectorAll(".matrix-hint, .flag-list, .severity-groups"));
    const alvos = [...blocos, ...(cartaoData ? [cartaoData] : [])];
    const campos = alvos.flatMap((el) => Array.from(el.querySelectorAll("input")));
    let guardado = null;
    const aplicar = () => {
      const nao = radios.some((r) => r.checked && r.value === "2");
      const escondido = alvos[0] && alvos[0].style.display === "none";
      if (nao && !escondido) {
        guardado = campos.map((c) => (c.type === "checkbox" ? c.checked : c.value));
        campos.forEach((c) => { if (c.type === "checkbox") c.checked = false; else c.value = ""; });
        alvos.forEach((el) => { el.style.display = "none"; });
      } else if (!nao && escondido) {
        alvos.forEach((el) => { el.style.display = ""; });
        if (guardado) campos.forEach((c, i) => { if (c.type === "checkbox") c.checked = guardado[i]; else c.value = guardado[i]; });
        guardado = null;
      }
    };
    radios.forEach((r) => r.addEventListener("change", aplicar));
    aplicar();
  });

  form.dataset.ready = "true";
  showStep(0);

  // Erro devolvido pelo servidor: abre a etapa do campo, destaca o cartão, mostra a mensagem ali e foca no campo.
  const campoComErro = form.dataset.errorField;
  if (campoComErro) {
    const controle = form.querySelector(`[name="${window.CSS && CSS.escape ? CSS.escape(campoComErro) : campoComErro}"]`);
    const painel = controle && controle.closest("[data-step-panel]");
    if (controle && painel) {
      const indice = Number(painel.dataset.stepPanel || 0);
      visited.add(indice);
      showStep(indice);
      const cartao = controle.closest("[data-field-card]");
      if (cartao) {
        cartao.classList.add("has-error");
        const aviso = document.createElement("p");
        aviso.className = "field-error";
        aviso.setAttribute("role", "alert");
        aviso.textContent = form.dataset.errorMessage || "Confira este campo.";
        cartao.appendChild(aviso);
        const limpar = () => { cartao.classList.remove("has-error"); aviso.remove(); };
        cartao.addEventListener("input", limpar, { once: true });
        cartao.addEventListener("change", limpar, { once: true });
      }
      window.setTimeout(() => {
        controle.focus({ preventScroll: true });
        (cartao || controle).scrollIntoView({ behavior: "smooth", block: "center" });
      }, 150);
    }
  }
})();
