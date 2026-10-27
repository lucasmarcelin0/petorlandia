/*
 * Ficha do tutor (templates/animais/tutor_detail.html).
 *
 * - Cadastro de animais em sequência: depois de salvar, o modal oferece
 *   "Cadastrar outro animal" com o formulário zerado de verdade (data, foto e
 *   enquadramento inclusos; antes o segundo animal herdava a data do primeiro).
 * - Envio com XMLHttpRequest para mostrar o progresso da foto e não cortar o
 *   upload aos 10 s (era o que deixava animais com nome "None").
 * - Erros ficam dentro do modal, com os dados preservados para tentar de novo.
 * - Remoção com confirmação e restauração; lista atualizada sem recarregar.
 */
(function () {
  'use strict';

  const page = document.querySelector('.tutor-page');
  if (!page) return;

  const LISTA_URL = page.dataset.listaUrl;
  const TEMPO_LIMITE_UPLOAD = 120000;
  const TEMPO_LIMITE = 45000;
  const cadastradosAgora = [];
  let precisaRecarregar = false;

  // ---------------------------------------------------------------- utilidades

  function bootstrapModal(el) {
    if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
    return window.bootstrap.Modal.getOrCreateInstance(el);
  }

  function normalizar(texto) {
    return String(texto || '')
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .trim();
  }

  function toast(mensagem, categoria) {
    if (typeof window.showToast === 'function') {
      window.showToast(mensagem, categoria || 'success');
    }
  }

  function csrfToken(form) {
    const campo = form && form.querySelector('input[name="csrf_token"]');
    if (campo && campo.value) return campo.value;
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') || '' : '';
  }

  function aplicarCsrf(token) {
    if (!token) return;
    document.querySelectorAll('input[name="csrf_token"]').forEach((campo) => { campo.value = token; });
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) meta.setAttribute('content', token);
  }

  async function renovarCsrf() {
    try {
      const resp = await fetch('/csrf-token', {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!resp.ok) return null;
      const data = await resp.json();
      if (data && data.csrf_token) {
        aplicarCsrf(data.csrf_token);
        return data.csrf_token;
      }
    } catch (_err) { /* sem rede: quem chamou mostra o erro */ }
    return null;
  }

  function ehFalhaCsrf(status, data) {
    if (status !== 400 || !data) return false;
    return String(data.error || '').toLowerCase().includes('csrf') || Boolean(data.errors && data.errors.csrf_token);
  }

  function temArquivo(form) {
    if (window.PetPhoto && typeof window.PetPhoto.formHasFile === 'function') {
      return window.PetPhoto.formHasFile(form);
    }
    return Array.prototype.some.call(form.querySelectorAll('input[type="file"]'), (input) =>
      input.files && input.files.length > 0 && input.files[0].size > 0);
  }

  function novoId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  }

  // Um id por animal cadastrado. Reenviar o mesmo animal (a conexão caiu
  // depois de salvar) usa o mesmo id e o servidor devolve o que já existe.
  function renovarEnvioId(form) {
    const campo = form && form.querySelector('[data-envio-id]');
    if (campo) campo.value = novoId();
  }

  function garantirEnvioId(form) {
    const campo = form && form.querySelector('[data-envio-id]');
    if (campo && !campo.value) campo.value = novoId();
  }

  function spinner(texto) {
    return `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span><span>${texto}</span>`;
  }

  // -------------------------------------------------------------- avisos

  function caixaDeAviso(container) {
    return container ? container.querySelector('[data-form-alert]') : null;
  }

  function esconderAviso(container) {
    const caixa = caixaDeAviso(container);
    if (!caixa) return;
    caixa.className = 'tutor-form-alert d-none';
    caixa.textContent = '';
  }

  function mostrarAviso(container, mensagem, nivel, acoes) {
    const caixa = caixaDeAviso(container);
    if (!caixa) {
      toast(mensagem, nivel === 'warning' ? 'warning' : 'danger');
      return;
    }
    caixa.className = `tutor-form-alert tutor-form-alert--${nivel || 'danger'}`;
    caixa.textContent = mensagem;
    if (acoes && acoes.length) {
      const linha = document.createElement('div');
      linha.className = 'tutor-form-alert__acoes';
      acoes.forEach((acao) => linha.appendChild(acao));
      caixa.appendChild(linha);
    }
    // O aviso fica no topo do modal: leva a rolagem até ele inteiro.
    const corpo = caixa.closest('.modal-body');
    if (corpo) {
      corpo.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
      caixa.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }

  function limparErrosDeCampo(form) {
    form.querySelectorAll('.is-invalid').forEach((campo) => campo.classList.remove('is-invalid'));
  }

  function marcarCampo(form, nome) {
    if (!nome) return;
    const alvo = nome === 'date_of_birth'
      ? form.querySelector('[data-dob]')
      : form.querySelector(`[name="${nome}"]:not([type="hidden"])`);
    if (!alvo) return;
    alvo.classList.add('is-invalid');
    alvo.addEventListener('input', () => alvo.classList.remove('is-invalid'), { once: true });
    if (typeof alvo.focus === 'function') alvo.focus({ preventScroll: true });
    alvo.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  // ------------------------------------------------------- lista de animais

  function atualizarContadores(totalAtivos) {
    if (typeof totalAtivos !== 'number') {
      const lista = document.getElementById('tutor-animais-lista');
      totalAtivos = lista ? Number(lista.dataset.ativos || 0) : 0;
    }
    document.querySelectorAll('[data-contador-animais]').forEach((el) => { el.textContent = String(totalAtivos); });
    document.querySelectorAll('[data-hero-contagem]').forEach((el) => {
      el.textContent = `${totalAtivos} ${totalAtivos === 1 ? 'animal' : 'animais'}`;
    });
    const busca = document.querySelector('[data-busca-animais]');
    const campoBusca = document.getElementById('animal-search');
    if (busca) {
      const temTermo = campoBusca && campoBusca.value.trim();
      busca.classList.toggle('d-none', totalAtivos <= 4 && !temTermo);
    }
  }

  function aplicarBusca() {
    const campo = document.getElementById('animal-search');
    const termo = normalizar(campo ? campo.value : '');
    const cards = document.querySelectorAll('#tutor-animais-lista .tutor-animal');
    let visiveis = 0;
    cards.forEach((card) => {
      const nome = normalizar(card.dataset.animalName || 'sem nome');
      const mostra = !termo || nome.includes(termo);
      card.classList.toggle('d-none', !mostra);
      if (mostra) visiveis += 1;
    });
    const semResultado = document.querySelector('[data-sem-resultado]');
    if (semResultado) semResultado.classList.toggle('d-none', !(termo && cards.length && !visiveis));
  }

  function destacarCard(id) {
    const card = document.getElementById(`animal-card-${id}`);
    if (!card) return;
    card.classList.add('is-destaque');
    card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    window.setTimeout(() => card.classList.remove('is-destaque'), 2600);
  }

  async function atualizarLista(opcoes = {}) {
    if (!LISTA_URL) {
      precisaRecarregar = true;
      return false;
    }
    try {
      const resp = await fetch(LISTA_URL, {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      const data = await resp.json();
      if (!data || !data.html) throw new Error('resposta sem html');
      const atual = document.getElementById('tutor-animais-lista');
      const molde = document.createElement('template');
      molde.innerHTML = data.html.trim();
      const nova = molde.content.firstElementChild;
      if (!atual || !nova) throw new Error('lista não encontrada');
      atual.replaceWith(nova);
      if (typeof window.initAvatarTransforms === 'function') window.initAvatarTransforms();
      atualizarContadores(typeof data.ativos === 'number' ? data.ativos : undefined);
      aplicarBusca();
      if (opcoes.destacar) destacarCard(opcoes.destacar);
      return true;
    } catch (err) {
      // A lista na tela ficou para trás; ao fechar o modal a página recarrega.
      console.warn('Não foi possível atualizar a lista de animais.', err);
      precisaRecarregar = true;
      return false;
    }
  }

  // ------------------------------------------------------- espécie → raças

  function popularRacas(selectEspecie, manterSelecao = true) {
    const alvo = document.getElementById(selectEspecie.dataset.breedTarget || '');
    if (!alvo) return;
    const especie = selectEspecie.value;
    const racas = (window.TUTOR_BREED_MAP || {})[especie] || [];
    const anterior = manterSelecao ? alvo.value : '';
    alvo.innerHTML = '';
    alvo.add(new Option(especie ? 'Não informada' : 'Escolha a espécie primeiro', ''));
    racas.forEach((raca) => alvo.add(new Option(raca.name, String(raca.id))));
    alvo.disabled = !especie;
    if (anterior && racas.some((raca) => String(raca.id) === anterior)) {
      alvo.value = anterior; // SRD continua escolhido ao trocar de espécie
    }
  }

  document.addEventListener('change', (ev) => {
    const select = ev.target.closest && ev.target.closest('.tutor-animal-form [data-species-select]');
    if (select) popularRacas(select);
  });

  // ------------------------------------------------------- envio do animal

  function enviar(form, aoProgredir) {
    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      const comArquivo = temArquivo(form);
      xhr.open('POST', form.action, true);
      xhr.timeout = comArquivo ? TEMPO_LIMITE_UPLOAD : TEMPO_LIMITE;
      xhr.setRequestHeader('Accept', 'application/json');
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      const token = csrfToken(form);
      if (token) xhr.setRequestHeader('X-CSRFToken', token);
      if (comArquivo && xhr.upload && aoProgredir) {
        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable && ev.total > 0) aoProgredir(ev.loaded / ev.total);
        };
        xhr.upload.onload = () => aoProgredir(1);
      }
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (_err) { data = null; }
        resolve({ tipo: 'resposta', status: xhr.status, ok: xhr.status >= 200 && xhr.status < 300, data });
      };
      xhr.onerror = () => resolve({ tipo: 'rede', status: 0, ok: false, data: null });
      xhr.ontimeout = () => resolve({ tipo: 'tempo', status: 0, ok: false, data: null });
      xhr.onabort = () => resolve({ tipo: 'cancelado', status: 0, ok: false, data: null });
      xhr.send(new FormData(form));
    });
  }

  function travarModal(modalEl, travar) {
    if (!modalEl) return;
    if (travar) {
      modalEl.dataset.travado = '1';
    } else {
      delete modalEl.dataset.travado;
    }
    modalEl.querySelectorAll('[data-bs-dismiss="modal"]').forEach((botao) => { botao.disabled = travar; });
  }

  async function salvarAnimal(form) {
    if (form.dataset.salvando === '1') return;
    esconderAviso(form);
    limparErrosDeCampo(form);

    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      mostrarAviso(form, 'Confira os campos destacados em vermelho.', 'danger');
      const primeiro = form.querySelector(':invalid');
      if (primeiro) {
        primeiro.focus({ preventScroll: true });
        primeiro.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
      return;
    }

    const modalEl = form.closest('.modal');
    const botao = form.querySelector('[data-save-button]');
    const textoOriginal = botao ? botao.innerHTML : '';
    const rotulo = (texto) => { if (botao) botao.innerHTML = spinner(texto); };

    form.dataset.salvando = '1';
    garantirEnvioId(form);
    travarModal(modalEl, true);
    if (botao) botao.disabled = true;
    rotulo(temArquivo(form) ? 'Preparando foto…' : 'Salvando…');

    try {
      if (window.PetPhoto && typeof window.PetPhoto.waitForm === 'function') {
        await window.PetPhoto.waitForm(form, 8000);
      }
      const comArquivo = temArquivo(form);
      rotulo(comArquivo ? 'Enviando foto…' : 'Salvando…');
      const progresso = (fracao) => rotulo(fracao < 1 ? `Enviando foto… ${Math.round(fracao * 100)}%` : 'Salvando…');

      let resultado = await enviar(form, progresso);
      if (!resultado.ok && ehFalhaCsrf(resultado.status, resultado.data) && await renovarCsrf()) {
        resultado = await enviar(form, progresso);
      }
      // O envio terminou: o modal precisa poder fechar (sucesso da edição).
      travarModal(modalEl, false);
      if (botao) {
        botao.disabled = false;
        botao.innerHTML = textoOriginal;
      }
      await tratarResultado(form, resultado);
    } catch (err) {
      console.error('Falha ao salvar o animal', err);
      mostrarAviso(form, 'Algo deu errado ao salvar. Seus dados continuam aqui: tente de novo.', 'danger');
    } finally {
      delete form.dataset.salvando;
      travarModal(modalEl, false);
      if (botao) {
        botao.disabled = false;
        botao.innerHTML = textoOriginal;
      }
    }
  }

  async function tratarResultado(form, resultado) {
    const data = resultado.data || {};
    if (resultado.ok && resultado.data && data.success !== false) {
      if (form.dataset.animalForm === 'novo') {
        await sucessoCadastro(form, data);
      } else {
        await sucessoEdicao(form, data);
      }
      return;
    }

    if (resultado.tipo === 'rede') {
      mostrarAviso(form, 'A internet caiu durante o envio. Seus dados continuam aqui: confira a conexão e toque em Salvar de novo.', 'danger');
      return;
    }
    if (resultado.tipo === 'tempo') {
      mostrarAviso(form, 'O envio demorou demais e foi interrompido. Seus dados continuam aqui: tente de novo, de preferência com uma internet melhor.', 'danger');
      return;
    }
    if (resultado.ok && !resultado.data) {
      mostrarAviso(form, 'Não deu para confirmar o salvamento (a sessão pode ter expirado). Recarregue a página e confira a lista.', 'warning');
      return;
    }
    if (resultado.status === 409 && data.duplicate) {
      mostrarDuplicado(form, data);
      return;
    }
    if (resultado.status === 413) {
      mostrarAviso(form, 'A foto é grande demais para enviar. Escolha outra foto ou tire uma nova.', 'danger');
      return;
    }
    if (resultado.status === 401 || resultado.status === 403 || resultado.status === 404) {
      mostrarAviso(form, data.message && resultado.status === 403
        ? data.message
        : 'Este cadastro não está disponível para você ou foi alterado em outra tela. Recarregue a página.', 'danger');
      return;
    }
    const padrao = resultado.status >= 500
      ? 'O servidor não conseguiu salvar agora. Seus dados continuam aqui: tente de novo em instantes.'
      : 'Não foi possível salvar. Confira os dados e tente de novo.';
    mostrarAviso(form, data.message || padrao, data.category === 'warning' ? 'warning' : 'danger');
    marcarCampo(form, data.field);
  }

  function mostrarDuplicado(form, data) {
    const confirmar = document.createElement('button');
    confirmar.type = 'button';
    confirmar.className = 'btn btn-sm btn-warning';
    confirmar.textContent = 'Cadastrar mesmo assim';
    confirmar.addEventListener('click', () => {
      const campo = form.querySelector('[data-confirmar-duplicado]');
      if (campo) campo.value = '1';
      salvarAnimal(form);
    });
    const acoes = [confirmar];
    if (data.redirect) {
      const ver = document.createElement('a');
      ver.className = 'btn btn-sm btn-light border';
      ver.href = data.redirect;
      ver.textContent = 'Ver o cadastro existente';
      acoes.push(ver);
    }
    mostrarAviso(form, data.message || 'Já existe um animal igual para este tutor.', 'warning', acoes);
  }

  // ------------------------------------------- cadastro: sucesso e próximo

  const modalNovo = document.getElementById('modalNovoAnimal');
  const formNovo = document.getElementById('new-animal-form');

  function mostrarPainelSucesso(mostrar) {
    if (!modalNovo) return;
    const painel = modalNovo.querySelector('[data-novo-sucesso]');
    const campos = modalNovo.querySelector('[data-novo-campos]');
    const rodape = modalNovo.querySelector('[data-novo-rodape]');
    if (painel) painel.classList.toggle('d-none', !mostrar);
    if (campos) campos.classList.toggle('d-none', mostrar);
    if (rodape) rodape.classList.toggle('d-none', mostrar);
    const corpo = modalNovo.querySelector('.modal-body');
    if (corpo) corpo.scrollTop = 0;
    if (mostrar && painel) painel.focus({ preventScroll: true });
  }

  async function sucessoCadastro(form, data) {
    const animal = data.animal || {};
    const nome = (animal.name || 'Animal').trim();
    if (!data.already_existed || !cadastradosAgora.includes(nome)) cadastradosAgora.push(nome);

    const titulo = modalNovo && modalNovo.querySelector('[data-novo-sucesso-titulo]');
    if (titulo) {
      if (data.already_existed) {
        titulo.textContent = `O cadastro de ${nome} já estava salvo`;
      } else if (animal.sex === 'Fêmea') {
        titulo.textContent = `${nome} foi cadastrada!`;
      } else if (animal.sex === 'Macho') {
        titulo.textContent = `${nome} foi cadastrado!`;
      } else {
        titulo.textContent = `Cadastro de ${nome} salvo!`;
      }
    }
    const lista = modalNovo && modalNovo.querySelector('[data-novo-sucesso-lista]');
    if (lista) {
      lista.innerHTML = '';
      if (cadastradosAgora.length > 1) {
        cadastradosAgora.forEach((item) => {
          const li = document.createElement('li');
          li.textContent = item;
          lista.appendChild(li);
        });
      }
    }
    const campoDuplicado = form.querySelector('[data-confirmar-duplicado]');
    if (campoDuplicado) campoDuplicado.value = '';
    mostrarPainelSucesso(true);
    if (data.already_existed && data.message) toast(data.message, 'info');
    await atualizarLista({ destacar: animal.id });
  }

  function prepararNovoCadastro() {
    if (!formNovo) return;
    formNovo.reset(); // data, foto e enquadramento voltam ao início (listeners de "reset")
    formNovo.classList.remove('was-validated');
    limparErrosDeCampo(formNovo);
    esconderAviso(formNovo);
    const campoDuplicado = formNovo.querySelector('[data-confirmar-duplicado]');
    if (campoDuplicado) campoDuplicado.value = '';
    renovarEnvioId(formNovo);
    mostrarPainelSucesso(false);
    window.setTimeout(() => {
      const nome = formNovo.querySelector('[name="name"]');
      if (nome) nome.focus({ preventScroll: true });
    }, 50);
  }

  if (formNovo) {
    formNovo.addEventListener('reset', () => {
      window.setTimeout(() => {
        const especie = formNovo.querySelector('[data-species-select]');
        if (especie) popularRacas(especie, false);
      }, 0);
    });
  }

  if (modalNovo) {
    modalNovo.addEventListener('show.bs.modal', () => {
      // Voltando depois de um cadastro concluído: começa um animal novo.
      // Se a pessoa só fechou no meio do preenchimento, os dados ficam.
      const painel = modalNovo.querySelector('[data-novo-sucesso]');
      if (painel && !painel.classList.contains('d-none')) prepararNovoCadastro();
    });
    modalNovo.addEventListener('shown.bs.modal', () => {
      if (window.matchMedia && window.matchMedia('(pointer: fine)').matches) {
        const nome = modalNovo.querySelector('[data-novo-campos]:not(.d-none) [name="name"]');
        if (nome) nome.focus({ preventScroll: true });
      }
    });
    const outro = modalNovo.querySelector('[data-cadastrar-outro]');
    if (outro) outro.addEventListener('click', prepararNovoCadastro);
  }

  // -------------------------------------------------------- edição: sucesso

  async function sucessoEdicao(form, data) {
    const animal = data.animal || {};
    const nome = (animal.name || data.animal_name || '').trim();
    const modalEl = form.closest('.modal');
    // Reabrir este modal recarrega a página: os campos e a foto vêm do banco.
    form.dataset.desatualizado = '1';
    const titulo = modalEl && modalEl.querySelector('[data-modal-nome]');
    if (titulo && nome) titulo.textContent = nome;
    const modal = bootstrapModal(modalEl);
    if (modal) modal.hide();
    toast(nome ? `Dados de ${nome} salvos.` : 'Dados do animal salvos.', 'success');
    (data.messages || []).forEach((item) => {
      if (item && item.message) toast(item.message, item.category || 'warning');
    });
    await atualizarLista({ destacar: animal.id || form.dataset.animalId });
  }

  document.addEventListener('submit', (ev) => {
    const form = ev.target;
    if (!(form instanceof HTMLFormElement) || !form.matches('.tutor-animal-form')) return;
    ev.preventDefault();
    salvarAnimal(form);
  });

  // ------------------------------------------------- abrir edição do animal

  function abrirEdicao(id) {
    const modalEl = document.getElementById(`modalEditarAnimal${id}`);
    const form = modalEl && modalEl.querySelector('form');
    if (!modalEl || !form || form.dataset.desatualizado === '1') return false;
    const modal = bootstrapModal(modalEl);
    if (!modal) return false;
    modal.show();
    return true;
  }

  document.addEventListener('click', (ev) => {
    const link = ev.target.closest && ev.target.closest('[data-edit-animal]');
    if (!link) return;
    // Sem o modal na página (animal recém-cadastrado) ou com o modal
    // desatualizado, o link recarrega a ficha já abrindo a edição.
    if (abrirEdicao(link.dataset.editAnimal)) ev.preventDefault();
  });

  // ----------------------------------------------- remover e restaurar

  const modalRemover = document.getElementById('modalRemoverAnimal');
  let remocao = null;

  async function postarAcao(url) {
    const corpo = new FormData();
    corpo.append('csrf_token', csrfToken());
    const resp = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrfToken() },
      credentials: 'same-origin',
      body: corpo,
    });
    let data = null;
    try { data = await resp.json(); } catch (_err) { data = null; }
    return { ok: resp.ok && data !== null && data.success !== false, status: resp.status, data };
  }

  document.addEventListener('click', (ev) => {
    const botao = ev.target.closest && ev.target.closest('[data-remove-animal]');
    if (!botao || !modalRemover) return;
    ev.preventDefault();
    remocao = {
      id: botao.dataset.removeAnimal,
      url: botao.dataset.removeUrl,
      nome: botao.dataset.animalLabel || 'este animal',
    };
    const alvoNome = modalRemover.querySelector('[data-remover-nome]');
    if (alvoNome) alvoNome.textContent = remocao.nome;
    esconderAviso(modalRemover);
    const modal = bootstrapModal(modalRemover);
    if (modal) modal.show();
  });

  if (modalRemover) {
    const confirmar = modalRemover.querySelector('[data-confirmar-remocao]');
    if (confirmar) {
      confirmar.addEventListener('click', async () => {
        if (!remocao || confirmar.disabled) return;
        const original = confirmar.innerHTML;
        confirmar.disabled = true;
        confirmar.innerHTML = spinner('Removendo…');
        try {
          const resultado = await postarAcao(remocao.url);
          if (resultado.ok) {
            const modal = bootstrapModal(modalRemover);
            if (modal) modal.hide();
            const nome = remocao.nome;
            await atualizarLista();
            toast(`${nome} saiu da lista. Dá para restaurar em “Removidos”.`, 'success');
          } else {
            const mensagem = (resultado.data && resultado.data.message) || 'Não foi possível remover agora. Tente de novo.';
            mostrarAviso(modalRemover, mensagem, 'danger');
          }
        } catch (_err) {
          mostrarAviso(modalRemover, 'A internet caiu. Confira a conexão e tente de novo.', 'danger');
        } finally {
          confirmar.disabled = false;
          confirmar.innerHTML = original;
        }
      });
    }
  }

  document.addEventListener('click', async (ev) => {
    const botao = ev.target.closest && ev.target.closest('[data-restore-animal]');
    if (!botao || botao.disabled) return;
    ev.preventDefault();
    const original = botao.innerHTML;
    botao.disabled = true;
    botao.innerHTML = spinner('Restaurando…');
    try {
      const resultado = await postarAcao(botao.dataset.restoreUrl);
      if (resultado.ok) {
        const id = botao.dataset.restoreAnimal;
        await atualizarLista({ destacar: id });
        toast((resultado.data && resultado.data.message) || 'Animal restaurado.', 'success');
        return;
      }
      toast((resultado.data && resultado.data.message) || 'Não foi possível restaurar agora.', 'danger');
    } catch (_err) {
      toast('A internet caiu. Confira a conexão e tente de novo.', 'danger');
    }
    if (botao.isConnected) {
      botao.disabled = false;
      botao.innerHTML = original;
    }
  });

  // --------------------------------------------------- modais em geral

  document.querySelectorAll('.tutor-modal').forEach((modalEl) => {
    modalEl.addEventListener('hide.bs.modal', (ev) => {
      // Durante o envio o modal não fecha (o envio continuaria sem a pessoa
      // ver o resultado).
      if (modalEl.dataset.travado === '1') ev.preventDefault();
    });
    modalEl.addEventListener('hidden.bs.modal', () => {
      if (precisaRecarregar && !document.querySelector('.modal.show')) {
        const url = new URL(window.location.href);
        url.searchParams.delete('editar');
        url.hash = 'animais';
        window.location.replace(url.toString());
        return;
      }
      // Backdrop esquecido trava a página no celular.
      window.setTimeout(() => {
        if (document.querySelector('.modal.show')) return;
        document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('padding-right');
        document.body.style.removeProperty('overflow');
      }, 250);
    });
  });

  // --------------------------------------------------------------- abas

  function ativarAba(nome) {
    const botao = document.getElementById(`${nome}-tab`);
    if (!botao || !window.bootstrap || !window.bootstrap.Tab) return null;
    window.bootstrap.Tab.getOrCreateInstance(botao).show();
    return botao;
  }

  document.querySelectorAll('#tutorTabs [data-bs-toggle="tab"]').forEach((botao) => {
    botao.addEventListener('shown.bs.tab', () => {
      const alvo = botao.getAttribute('data-bs-target');
      if (alvo && window.history && window.history.replaceState) {
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${alvo}`);
      }
    });
  });

  // Atalho sem telefone/endereço: leva ao campo certo em "Dados do tutor".
  document.addEventListener('click', (ev) => {
    const botao = ev.target.closest && ev.target.closest('[data-ir-para-campo]');
    if (!botao) return;
    ev.preventDefault();
    const campo = document.getElementById(botao.dataset.irParaCampo);
    const focar = () => {
      if (!campo) return;
      campo.scrollIntoView({ block: 'center', behavior: 'smooth' });
      campo.focus({ preventScroll: true });
    };
    const aba = document.getElementById('dados-tab');
    if (aba && !aba.classList.contains('active')) {
      aba.addEventListener('shown.bs.tab', focar, { once: true });
      ativarAba('dados');
    } else {
      focar();
    }
  });

  // ----------------------------------------- dados do tutor salvos

  async function atualizarCabecalho() {
    try {
      const resp = await fetch(`${window.location.pathname}${window.location.search}`, {
        headers: { Accept: 'text/html' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!resp.ok) return;
      const doc = new DOMParser().parseFromString(await resp.text(), 'text/html');
      const novo = doc.getElementById('tutor-hero');
      const atual = document.getElementById('tutor-hero');
      if (novo && atual) {
        atual.replaceWith(document.importNode(novo, true));
        if (typeof window.initAvatarTransforms === 'function') window.initAvatarTransforms();
        atualizarContadores();
      }
    } catch (_err) { /* o cabeçalho antigo continua válido até recarregar */ }
  }

  document.addEventListener('form-sync-success', (ev) => {
    const detalhe = ev.detail || {};
    if (!detalhe.form || detalhe.form.id !== 'tutor-form') return;
    const data = detalhe.data || {};
    if (!(detalhe.response && detalhe.response.ok) || data.success === false) return;
    // Telefone e endereço mudam os atalhos de WhatsApp e mapa.
    atualizarCabecalho();
  });

  // --------------------------------------------------------------- início

  const campoBusca = document.getElementById('animal-search');
  if (campoBusca) campoBusca.addEventListener('input', aplicarBusca);
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest || !ev.target.closest('[data-limpar-busca]')) return;
    if (campoBusca) {
      campoBusca.value = '';
      aplicarBusca();
      campoBusca.focus();
    }
  });

  if (window.location.hash === '#dados') ativarAba('dados');

  const editarAoAbrir = page.dataset.editarAnimal;
  if (editarAoAbrir) {
    const abrir = () => {
      abrirEdicao(editarAoAbrir);
      if (window.history && window.history.replaceState) {
        const url = new URL(window.location.href);
        url.searchParams.delete('editar');
        window.history.replaceState(null, '', url.toString());
      }
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', abrir, { once: true });
    } else {
      abrir();
    }
  }
})();
