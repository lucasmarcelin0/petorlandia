/* Comunicações ficam no IndexedDB até o servidor confirmar o recebimento. */
(function () {
  'use strict';
  var form = document.querySelector('[data-offline-comunicacao]');
  if (!form) return;
  var usuario = form.dataset.usuario, info = document.getElementById('limpeza-pendencias');
  var botao = form.querySelector('button[type=submit]'), aviso = form.querySelector('.limpeza-aviso-foto');
  var foto = null, db, gravando = Promise.resolve(), pendenteEditada = null;
  var textoBotao = botao ? botao.innerHTML : '';
  var acoesPendentes = document.getElementById('limpeza-pendentes-acoes');
  var draftId = 'rascunho:' + usuario;
  function status(msg) { info.textContent = msg; info.classList.remove('d-none'); }
  // O andamento aparece no próprio botão, onde a pessoa está olhando.
  function botaoOcupado(texto) {
    botao.disabled = true;
    botao.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>' + texto;
  }
  function botaoLivre() { botao.disabled = false; botao.innerHTML = textoBotao; }
  function semPendencias() { info.textContent = ''; info.classList.add('d-none'); }
  function parabens(dados) { if (window.limpezaParabens) window.limpezaParabens(dados); }
  function erro(msg) { aviso.textContent = msg; aviso.classList.remove('d-none'); }
  function abrir() { return new Promise(function (resolve, reject) {
    var req = indexedDB.open('petorlandia-limpeza', 1);
    req.onupgradeneeded = function () { req.result.createObjectStore('registros', {keyPath: 'id'}); };
    req.onsuccess = function () { resolve(req.result); }; req.onerror = function () { reject(req.error); };
  }); }
  function operar(modo, funcao) { return new Promise(function (resolve, reject) {
    var tx = db.transaction('registros', modo), req = funcao(tx.objectStore('registros'));
    tx.oncomplete = function () { resolve(req.result); }; tx.onerror = function () { reject(tx.error); }; tx.onabort = function () { reject(tx.error); };
  }); }
  function todos() { return operar('readonly', function (s) { return s.getAll(); }); }
  function salvar(item) { return operar('readwrite', function (s) { return s.put(item); }); }
  function apagar(id) { return operar('readwrite', function (s) { return s.delete(id); }); }
  function dados() {
    var campos = {};
    new FormData(form).forEach(function (v, k) {
      if (k === 'foto' || k === 'csrf_token') return;
      if (k === 'categoria') { (campos[k] || (campos[k] = [])).push(v); } else campos[k] = v;
    });
    return campos;
  }
  function agendarRascunho() {
    if (!db || !foto) return gravando;
    var item = {id: draftId, usuario: usuario, foto: foto, campos: dados(), pendenteEditada: pendenteEditada};
    gravando = gravando.catch(function () {}).then(function () { return salvar(item); }).catch(function () { erro('Não foi possível guardar a foto neste aparelho. Mantenha a tela aberta e verifique o espaço disponível.'); throw new Error('Falha ao guardar no aparelho'); });
    return gravando;
  }
  function restaurar(item) {
    if (!item || !item.foto) return;
    foto = item.foto;
    pendenteEditada = item.pendenteEditada || null;
    Object.keys(item.campos).forEach(function (nome) {
      var valor = item.campos[nome];
      form.querySelectorAll('[name="' + nome + '"]').forEach(function (el) {
        if (el.type === 'checkbox') el.checked = Array.isArray(valor) && valor.indexOf(el.value) >= 0;
        else if (el.type !== 'file') el.value = valor;
      });
    });
    var previa = form.querySelector('.limpeza-previa'); previa.src = URL.createObjectURL(foto); previa.classList.remove('d-none');
    status('Foto e dados recuperados neste aparelho. Termine o preenchimento e toque em salvar.');
  }
  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    var b = crypto.getRandomValues(new Uint8Array(16)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    return Array.from(b, function (x, i) { return ([4, 6, 8, 10].indexOf(i) >= 0 ? '-' : '') + x.toString(16).padStart(2, '0'); }).join('');
  }
  async function atualizarStatus() {
    var itens = (await todos()).filter(function (x) { return x.usuario === usuario && x.id !== draftId; });
    var comErro = itens.filter(function (x) { return x.erro; }).length;
    if (acoesPendentes) acoesPendentes.classList.toggle('d-none', !itens.length);
    if (!itens.length) { semPendencias(); return itens; }
    status(itens.length + ' comunicação(ões) guardada(s) neste celular, aguardando envio' +
      (comErro ? ' (' + comErro + ' precisa(m) de correção: toque em "Editar primeira pendente").' : '.'));
    return itens;
  }
  // Toda espera de rede tem limite: conexão lenta vira "guardada no celular", nunca uma tela parada.
  var LIMITE_PAGINA_MS = 20000, LIMITE_ENVIO_MS = 90000;
  function buscar(url, opcoes, limite) {
    var controle = ('AbortController' in window) ? new AbortController() : null;
    var relogio = controle ? setTimeout(function () { controle.abort(); }, limite) : null;
    if (controle) opcoes.signal = controle.signal;
    return fetch(url, opcoes).catch(function (e) {
      throw new Error(e && e.name === 'AbortError' ? 'A conexão está lenta.' : 'Sem conexão no momento.');
    }).finally(function () { if (relogio) clearTimeout(relogio); });
  }
  function esperar(promessa, limite) {
    return Promise.race([promessa, new Promise(function (r) { setTimeout(r, limite); })]);
  }
  async function enviarPendentes() {
    var enviadas = 0, ultimo = null, recusadas = [];
    try {
      var itens = (await atualizarStatus()).filter(function (item) { return item.id !== pendenteEditada && !item.erro; });
      if (!itens.length) return {enviadas: 0, recusadas: 0, falhou: false};
      status('Enviando ' + itens.length + ' comunicação(ões)…');
      var resposta = await buscar(form.action || location.pathname, {credentials: 'same-origin', cache: 'no-store', headers: {'X-Requested-With': 'XMLHttpRequest'}}, LIMITE_PAGINA_MS);
      if (!resposta.ok || resposta.redirected) throw new Error('Entre novamente na mesma conta para enviar as pendências.');
      var pagina = new DOMParser().parseFromString(await resposta.text(), 'text/html');
      var novoForm = pagina.querySelector('[data-offline-comunicacao]');
      if (!novoForm || novoForm.dataset.usuario !== usuario) throw new Error('Entre na conta que criou as pendências para enviá-las.');
      var token = novoForm.querySelector('[name=csrf_token]').value;
      for (var item of itens) {
        var body = new FormData();
        Object.keys(item.campos).forEach(function (k) { var v = item.campos[k]; (Array.isArray(v) ? v : [v]).forEach(function (x) { body.append(k, x); }); });
        body.set('csrf_token', token); body.set('chave_envio', item.id); body.append('foto', item.foto, item.foto.name || 'foto.jpg');
        var respostaEnvio = await buscar(form.action || location.pathname, {method: 'POST', body: body, credentials: 'same-origin', headers: {'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}}, LIMITE_ENVIO_MS);
        var resultado = await respostaEnvio.json().catch(function () { return {}; });
        if (respostaEnvio.status === 400 && resultado.erro) {
          // Recusada pelo conteúdo (ex.: foto sem localização): fica guardada para correção
          // e não impede o envio das próximas.
          item.erro = resultado.erro; await salvar(item); recusadas.push(resultado.erro); continue;
        }
        if (!respostaEnvio.ok || !resultado.destino) throw new Error(resultado.erro || 'O envio não foi confirmado.');
        await apagar(item.id);
        enviadas += 1; ultimo = resultado;
      }
      await atualizarStatus();
      if (recusadas.length) {
        status(recusadas.length + ' comunicação(ões) precisa(m) de correção: ' + recusadas[0] + ' Toque em "Editar primeira pendente".');
        // Aviso na frente da pessoa, com o caminho para corrigir.
        parabens({tipo: 'erro', texto: recusadas[0]});
      } else if (enviadas) {
        // Confirmado pelo servidor: comemora (com a conquista calculada lá).
        var dados = Object.assign({tipo: 'comunicacao'}, (ultimo && ultimo.parabens) || {});
        dados.enviadas = enviadas;
        if (enviadas === 1 && ultimo && ultimo.numero) dados.numero = ultimo.numero;
        parabens(dados);
      }
      return {enviadas: enviadas, recusadas: recusadas.length, falhou: false};
    } catch (e) {
      await atualizarStatus().catch(function () {});
      status((e.message || 'Sem conexão.') + ' As comunicações continuam guardadas neste celular e serão enviadas sozinhas.');
      return {enviadas: enviadas, recusadas: recusadas.length, falhou: true, motivo: e.message || ''};
    }
  }
  /* Um envio por vez. Quem chega durante um envio espera ele acabar e roda de novo, para a
     comunicação nova não ficar sem resposta. Devolve {enviadas, recusadas, falhou}; null sem internet. */
  var emCurso = null;
  function sincronizar() {
    if (!db || !navigator.onLine) return Promise.resolve(null);
    if (emCurso) return emCurso.then(function () { return sincronizar(); });
    emCurso = enviarPendentes().finally(function () { emCurso = null; });
    return emCurso;
  }
  form.addEventListener('limpeza:foto', function () {
    var campos = form.querySelectorAll('input[type=file][name=foto]');
    for (var campo of campos) if (campo.files && campo.files.length) foto = campo.files[0];
    agendarRascunho().catch(function () {});
  });
  form.addEventListener('input', function (ev) { if (ev.target.type !== 'file') agendarRascunho().catch(function () {}); });
  form.addEventListener('change', function (ev) { if (ev.target.type !== 'file') agendarRascunho().catch(function () {}); });
  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    if (!db) { erro('Armazenamento indisponível. Não foi possível proteger a foto neste aparelho.'); return; }
    if (!form.querySelector('[name=categoria]:checked')) { erro('Marque o que precisa de atenção.'); return; }
    if (form.querySelector('[name=categoria][value=outro]:checked') && !form.querySelector('[name=descricao]').value.trim()) { erro('Descreva o que precisa de atenção quando marcar Outro.'); return; }
    if (!foto) { erro('Tire a foto do local antes de salvar.'); return; }
    botaoOcupado('Registrando a localização…');
    try {
      if (form.limpezaLocalPronto) {
        // Com uma leitura recente do GPS já preenchida, espera pouco pela leitura nova;
        // sem nenhuma, dá mais tempo para o GPS responder.
        var temLocal = !!(form.querySelector('[name=latitude]') || {}).value;
        await esperar(form.limpezaLocalPronto(), temLocal ? 3000 : 20000);
      }
      await agendarRascunho();
      await salvar({id: pendenteEditada || uuid(), usuario: usuario, foto: foto, campos: dados()});  // sem .erro: volta à fila
      await apagar(draftId);
      foto = null; pendenteEditada = null; form.reset(); form.querySelector('.limpeza-previa').classList.add('d-none'); aviso.classList.add('d-none');
      await atualizarStatus();
      var resultado = null;
      if (navigator.onLine) {
        botaoOcupado('Enviando…');
        resultado = await sincronizar();
      }
      // Sem internet (ou o envio falhou): avisa com clareza que ficou guardada e segue sozinha.
      if (!resultado || (resultado.falhou && !resultado.enviadas)) {
        parabens({tipo: 'guardada', motivo: resultado ? resultado.motivo : 'Sem internet agora.'});
      }
    } catch (e) { erro('Não foi possível guardar a comunicação. Sua foto permanece no formulário.'); }
    finally { botaoLivre(); }
  });
  document.getElementById('limpeza-sincronizar').addEventListener('click', sincronizar);
  document.getElementById('limpeza-recuperar').addEventListener('click', async function () {
    if (!db || emCurso) return;
    if (foto) { erro('Salve a foto atual antes de editar uma pendência.'); return; }
    var itens = await atualizarStatus();
    if (!itens.length) { status('Nenhuma comunicação pendente para editar.'); return; }
    var item = itens.filter(function (x) { return x.erro; })[0] || itens[0];
    item.pendenteEditada = item.id;
    restaurar(item);
    await agendarRascunho();
    status((item.erro ? 'Motivo da recusa: ' + item.erro + ' ' : '') +
      'Pendência carregada. Corrija os dados (ou tire a foto de novo) e toque em salvar.');
  });
  window.addEventListener('online', function () { sincronizar(); });
  // Pendências guardadas seguem sozinhas: tenta de novo a cada minuto com a tela aberta.
  setInterval(function () { if (!document.hidden && !emCurso) sincronizar(); }, 60000);
  if ('serviceWorker' in navigator && 'caches' in window) navigator.serviceWorker.ready.then(function () { return caches.open('petorlandia-limpeza-offline-v1'); }).then(function (cache) { return cache.addAll(['/static/js/limpeza_foto.js?v=9', '/static/js/limpeza_offline.js?v=4', '/static/bootstrap.min.css']); }).catch(function () {});
  abrir().then(async function (banco) { db = banco; var r = await operar('readonly', function (s) { return s.get(draftId); }); await atualizarStatus(); if (r) restaurar(r); sincronizar(); }).catch(function () { status('Armazenamento do aparelho indisponível. Verifique o espaço e as configurações do navegador.'); });
})();
