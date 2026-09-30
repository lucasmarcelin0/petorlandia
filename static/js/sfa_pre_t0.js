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

  // ---- Conferência por etapa: erros aparecem no cartão do campo e num aviso no topo da etapa ----
  const campoEscondido = (el) => {
    for (let n = el; n && n !== form; n = n.parentElement) if (n.style && n.style.display === "none") return true;
    return false;
  };
  const nomeDoCampo = (cartao) => {
    const titulo = cartao.querySelector(".question-title > span:not(.question-number):not(.required-mark)");
    return titulo ? titulo.textContent.trim() : "Campo";
  };

  function errosDoCartao(cartao) {
    const erros = [];
    const gruposVistos = new Set();
    cartao.querySelectorAll("input, select, textarea").forEach((c) => {
      if (c.type === "hidden" || c.disabled || c.type === "checkbox") return;
      if (c.type === "radio") {
        if (gruposVistos.has(c.name)) return;
        gruposVistos.add(c.name);
        const grupo = Array.from(cartao.querySelectorAll(`input[type="radio"]`)).filter((r) => r.name === c.name);
        if (grupo.some((r) => r.required) && !grupo.some((r) => r.checked)) erros.push({ controle: c, mensagem: "Escolha uma das opções." });
        return;
      }
      const valor = c.value.trim();
      if (c.type === "date" && !valor && c.validity && c.validity.badInput) { erros.push({ controle: c, mensagem: "Data inválida." }); return; }
      if (c.required && !valor) { erros.push({ controle: c, mensagem: "Preencha este campo." }); return; }
      if (!valor) return;
      if (c.hasAttribute("data-numeric") && !/^\d+$/.test(valor)) erros.push({ controle: c, mensagem: "Use somente números." });
      else if (c.minLength > 0 && valor.length < c.minLength) erros.push({ controle: c, mensagem: `Informe pelo menos ${c.minLength} dígitos.` });
    });
    const idade = cartao.querySelector("#input-idade_valor");
    const unidade = cartao.querySelector("#input-idade_unidade");
    if (idade && unidade && idade.value.trim() && !unidade.value) erros.push({ controle: unidade, mensagem: "Selecione a unidade da idade." });
    return erros;
  }

  function errosDaEtapa(indice) {
    const erros = [];
    panels[indice].querySelectorAll("[data-field-card]").forEach((cartao) => {
      if (campoEscondido(cartao)) return;
      errosDoCartao(cartao).forEach((erro) => erros.push({ ...erro, cartao }));
    });
    return erros;
  }

  function limparErros(painel) {
    painel.querySelectorAll(".has-error").forEach((c) => c.classList.remove("has-error"));
    painel.querySelectorAll(".field-error, .step-alert").forEach((e) => e.remove());
  }

  function conferirEtapa(indice) {
    const painel = panels[indice];
    limparErros(painel);
    const erros = errosDaEtapa(indice);
    if (!erros.length) return true;
    erros.forEach(({ cartao, mensagem }) => {
      cartao.classList.add("has-error");
      if (cartao.querySelector(".field-error")) return;
      const aviso = document.createElement("p");
      aviso.className = "field-error";
      aviso.setAttribute("role", "alert");
      aviso.textContent = mensagem;
      cartao.appendChild(aviso);
    });
    const alerta = document.createElement("div");
    alerta.className = "step-alert";
    alerta.setAttribute("role", "alert");
    const titulo = document.createElement("strong");
    titulo.textContent = erros.length === 1 ? "Falta corrigir 1 campo nesta etapa" : `Faltam corrigir ${erros.length} campos nesta etapa`;
    const lista = document.createElement("ul");
    erros.forEach(({ cartao, mensagem }) => {
      const item = document.createElement("li");
      item.textContent = `${nomeDoCampo(cartao)}: ${mensagem}`;
      lista.appendChild(item);
    });
    alerta.append(titulo, lista);
    const cabecalho = painel.querySelector(".section-heading");
    if (cabecalho) cabecalho.insertAdjacentElement("afterend", alerta); else painel.prepend(alerta);
    const primeiro = erros[0];
    window.setTimeout(() => {
      primeiro.controle.focus({ preventScroll: true });
      primeiro.cartao.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 60);
    return false;
  }

  // Corrigiu o campo: o aviso dele some (e o aviso da etapa some quando não sobra nenhum).
  const aoEditar = (evento) => {
    const cartao = evento.target.closest && evento.target.closest("[data-field-card]");
    if (!cartao || !cartao.classList.contains("has-error")) return;
    cartao.classList.remove("has-error");
    cartao.querySelectorAll(".field-error").forEach((e) => e.remove());
    const painel = cartao.closest("[data-step-panel]");
    if (painel && !painel.querySelector(".has-error")) painel.querySelectorAll(".step-alert").forEach((e) => e.remove());
  };
  form.addEventListener("input", aoEditar);
  form.addEventListener("change", aoEditar);

  // Campos numéricos: separadores (traço, ponto, espaço, barra, parênteses) inseridos pelo preenchimento
  // automático ou pela digitação são descartados na hora, em vez de travar a etapa.
  form.querySelectorAll("[data-numeric]").forEach((campo) => {
    const limpar = () => {
      const limpo = campo.value.replace(/[\s.\-–—/()]/g, "");
      if (limpo !== campo.value) campo.value = limpo;
    };
    ["input", "change", "blur"].forEach((tipo) => campo.addEventListener(tipo, limpar));
    limpar();
  });

  previous?.addEventListener("click", () => showStep(current - 1, true));
  const notaEtapa = form.querySelector(".step-actions-note");
  const notaPadrao = notaEtapa ? notaEtapa.textContent : "";
  next?.addEventListener("click", () => {
    if (!conferirEtapa(current)) return;
    if (notaEtapa) notaEtapa.textContent = `✓ Etapa ${current + 1} conferida`;
    visited.add(current);
    visited.add(current + 1);
    showStep(current + 1, true);
  });
  previous?.addEventListener("click", () => { if (notaEtapa) notaEtapa.textContent = notaPadrao; });
  dots.forEach((dot) => dot.addEventListener("click", () => {
    const target = Number(dot.dataset.stepTarget);
    if (Number.isInteger(target)) {
      visited.add(target);
      showStep(target, true);
    }
  }));

  form.addEventListener("submit", (event) => {
    const primeiraComErro = panels.findIndex((_painel, indice) => errosDaEtapa(indice).length > 0);
    if (primeiraComErro >= 0) {
      event.preventDefault();
      visited.add(primeiraComErro);
      showStep(primeiraComErro);
      conferirEtapa(primeiraComErro);
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

  // Perguntas que só valem para certas respostas. Ao esconder, o que estava preenchido é guardado e limpo
  // (nada contraditório é enviado); se a resposta mudar, o conteúdo volta.
  function esconderQuando(nomeRadio, valoresQueEscondem, alvos) {
    const radios = Array.from(form.querySelectorAll(`input[type="radio"][name="${nomeRadio}"]`));
    alvos = alvos.filter(Boolean);
    if (!radios.length || !alvos.length) return;
    const campos = alvos.flatMap((el) => Array.from(el.querySelectorAll("input, select, textarea")));
    const marcavel = (c) => c.type === "checkbox" || c.type === "radio";
    let guardado = null;
    const aplicar = () => {
      const deve = radios.some((r) => r.checked && valoresQueEscondem.includes(r.value));
      const escondido = alvos[0].style.display === "none";
      if (deve && !escondido) {
        guardado = campos.map((c) => (marcavel(c) ? c.checked : c.value));
        campos.forEach((c) => { if (marcavel(c)) c.checked = false; else c.value = ""; });
        alvos.forEach((el) => { el.style.display = "none"; });
      } else if (!deve && escondido) {
        alvos.forEach((el) => { el.style.display = ""; });
        if (guardado) campos.forEach((c, i) => { if (marcavel(c)) c.checked = guardado[i]; else c.value = guardado[i]; });
        guardado = null;
      }
    };
    radios.forEach((r) => r.addEventListener("change", aplicar));
    aplicar();
  }
  const cartaoDe = (chave) => form.querySelector(`[data-field-card="${chave}"]`);
  const partesDe = (chave, seletor) => Array.from((cartaoDe(chave) || document.createElement("div")).querySelectorAll(seletor));
  esconderQuando("sinais_alarme", ["2"], [...partesDe("sinais_alarme", ".matrix-hint, .flag-list"), cartaoDe("data_inicio_sinais_alarme")]);
  esconderQuando("dengue_grave", ["2"], [...partesDe("dengue_grave", ".severity-groups"), cartaoDe("data_inicio_sinais_gravidade")]);
  esconderQuando("hospitalizacao", ["2"], ["data_internacao", "uf_hospital", "municipio_hospital", "nome_hospital", "telefone_hospital"].map(cartaoDe));
  esconderQuando("evolucao_caso", ["1"], [cartaoDe("data_obito")]);

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
