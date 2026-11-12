/* Comunicações ficam no IndexedDB até o servidor confirmar o recebimento. */
(function () {
  'use strict';
  var form = document.querySelector('[data-offline-comunicacao]');
  if (!form) return;
  var usuario = form.dataset.usuario, info = document.getElementById('limpeza-pendencias');
  var botao = form.querySelector('button[type=submit]'), aviso = form.querySelector('.limpeza-aviso-foto');
  var foto = null, db, enviando = false, gravando = Promise.resolve(), pendenteEditada = null;
  var draftId = 'rascunho:' + usuario;
  function status(msg) { info.textContent = msg; }
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
    status(itens.length ? itens.length + ' comunicação(ões) guardada(s) neste aparelho, aguardando envio' +
      (comErro ? ' (' + comErro + ' precisa(m) de correção: toque em "Editar primeira pendente").' : '.')
      : 'Nenhuma comunicação pendente de envio neste aparelho.');
    return itens;
  }
  async function sincronizar() {
    if (!db || enviando || !navigator.onLine) return;
    enviando = true;
    try {
      var itens = (await atualizarStatus()).filter(function (item) { return item.id !== pendenteEditada && !item.erro; });
      if (!itens.length) return;
      status('Enviando ' + itens.length + ' comunicação(ões) pendente(s)…');
      var resposta = await fetch(form.action || location.pathname, {credentials: 'same-origin', cache: 'no-store', headers: {'X-Requested-With': 'XMLHttpRequest'}});
      if (!resposta.ok || resposta.redirected) throw new Error('Entre novamente na mesma conta para enviar as pendências.');
      var pagina = new DOMParser().parseFromString(await resposta.text(), 'text/html');
      var novoForm = pagina.querySelector('[data-offline-comunicacao]');
      if (!novoForm || novoForm.dataset.usuario !== usuario) throw new Error('Entre na conta que criou as pendências para enviá-las.');
      var token = novoForm.querySelector('[name=csrf_token]').value;
      var recusadas = [];
      for (var item of itens) {
        var body = new FormData();
        Object.keys(item.campos).forEach(function (k) { var v = item.campos[k]; (Array.isArray(v) ? v : [v]).forEach(function (x) { body.append(k, x); }); });
        body.set('csrf_token', token); body.set('chave_envio', item.id); body.append('foto', item.foto, item.foto.name || 'foto.jpg');
        var respostaEnvio = await fetch(form.action || location.pathname, {method: 'POST', body: body, credentials: 'same-origin', headers: {'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}});
        var resultado = await respostaEnvio.json().catch(function () { return {}; });
        if (respostaEnvio.status === 400 && resultado.erro) {
          // Recusada pelo conteúdo (ex.: foto sem localização): fica guardada para correção
          // e não impede o envio das próximas.
          item.erro = resultado.erro; await salvar(item); recusadas.push(resultado.erro); continue;
        }
        if (!respostaEnvio.ok || !resultado.destino) throw new Error(resultado.erro || 'Envio não confirmado. As fotos continuam guardadas neste aparelho.');
        await apagar(item.id);
      }
      await atualizarStatus();
      status(recusadas.length
        ? recusadas.length + ' comunicação(ões) precisa(m) de correção: ' + recusadas[0] + ' Toque em "Editar primeira pendente".'
        : 'Comunicações enviadas e confirmadas pelo servidor.');
    } catch (e) { status((e.message || 'Sem conexão.') + ' Pendências continuam guardadas neste aparelho.'); }
    finally { enviando = false; }
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
    botao.disabled = true;
    try {
      if (form.limpezaLocalPronto) {
        status('Registrando a localização da foto…');
        await form.limpezaLocalPronto();
      }
      await agendarRascunho();
      await salvar({id: pendenteEditada || uuid(), usuario: usuario, foto: foto, campos: dados()});  // sem .erro: volta à fila
      await apagar(draftId);
      foto = null; pendenteEditada = null; form.reset(); form.querySelector('.limpeza-previa').classList.add('d-none'); aviso.classList.add('d-none');
      await atualizarStatus();
      if (navigator.onLine) sincronizar();
    } catch (e) { erro('Não foi possível guardar a comunicação. Sua foto permanece no formulário.'); }
    finally { botao.disabled = false; }
  });
  document.getElementById('limpeza-sincronizar').addEventListener('click', sincronizar);
  document.getElementById('limpeza-recuperar').addEventListener('click', async function () {
    if (!db || enviando) return;
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
  window.addEventListener('online', sincronizar);
  if ('serviceWorker' in navigator && 'caches' in window) navigator.serviceWorker.ready.then(function () { return caches.open('petorlandia-limpeza-offline-v1'); }).then(function (cache) { return cache.addAll(['/static/js/limpeza_foto.js?v=7', '/static/js/limpeza_offline.js?v=2', '/static/bootstrap.min.css']); }).catch(function () {});
  abrir().then(async function (banco) { db = banco; var r = await operar('readonly', function (s) { return s.get(draftId); }); await atualizarStatus(); if (r) restaurar(r); sincronizar(); }).catch(function () { status('Armazenamento do aparelho indisponível. Verifique o espaço e as configurações do navegador.'); });
})();
