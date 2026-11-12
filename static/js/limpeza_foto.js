// Limpeza urbana: foto na hora (câmera), galeria, prévia e posição do aparelho
// nos formulários com [data-limpeza-foto].
// O servidor prefere o GPS gravado na própria foto; a posição do aparelho cobre a câmera
// do navegador, que costuma remover o GPS da imagem.
(function () {
  'use strict';
  var celular = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;

  document.querySelectorAll('form[data-limpeza-foto]').forEach(function (form) {
    var arquivos = form.querySelectorAll('input[type=file][name=foto]');
    var campoCamera = form.querySelector('[data-limpeza-arquivo=camera]');
    var campoGaleria = form.querySelector('[data-limpeza-arquivo=galeria]');
    var painel = form.querySelector('.limpeza-camera');
    var video = painel && painel.querySelector('video');
    var previa = form.querySelector('.limpeza-previa');
    var aviso = form.querySelector('.limpeza-aviso-foto');
    var status = form.querySelector('.limpeza-gps');
    var texto = status && status.querySelector('span');
    var lat = form.querySelector('input[name=latitude]');
    var lon = form.querySelector('input[name=longitude]');
    var prec = form.querySelector('input[name=precisao]');
    var botao = form.querySelector('button[type=submit]');
    var melhor = null;
    var fluxo = null;
    var localAtual = null;
    var localFoto = false;

    function avisar(msg) {
      if (!aviso) return;
      aviso.textContent = msg || '';
      aviso.classList.toggle('d-none', !msg);
    }

    function mostrar(msg, tom) {
      if (!status) return;
      status.className = 'limpeza-gps small mt-2 text-' + (tom || 'muted');
      if (texto) texto.textContent = msg;
    }

    // ---- Localização ----
    function guardar(pos) {
      var c = pos.coords;
      melhor = { accuracy: c.accuracy, quando: Date.now() };
      localAtual = { latitude: c.latitude.toFixed(7), longitude: c.longitude.toFixed(7), precisao: Math.round(c.accuracy), quando: pos.timestamp };
      if (localFoto) return;
      var ok = c.accuracy <= 50;
      mostrar('Localização disponível para a próxima foto (precisão de ' + Math.round(c.accuracy) + ' m)' +
        (ok ? '.' : '. Se puder, vá para céu aberto para melhorar.'), ok ? 'success' : 'warning');
    }

    function falhou(erro) {
      if (lat.value) return;
      var msg = erro && erro.code === 1
        ? 'Localização bloqueada. Permita o acesso à localização para este site ou use uma foto com localização gravada.'
        : 'Não foi possível obter a localização agora. Fotos com localização gravada também são aceitas.';
      mostrar(msg, 'danger');
    }

    // O GPS fica ligado enquanto a tela está à vista: em campo a pessoa passa vários
    // minutos nesta página entre uma foto e outra. Com a tela oculta, pausa (bateria).
    var vigia = null;
    function ligarGps() {
      if (vigia !== null || !('geolocation' in navigator) || document.hidden) return;
      vigia = navigator.geolocation.watchPosition(guardar, falhou,
        { enableHighAccuracy: true, maximumAge: 10000, timeout: 30000 });
    }
    function desligarGps() {
      if (vigia !== null) navigator.geolocation.clearWatch(vigia);
      vigia = null;
    }
    if (!('geolocation' in navigator)) {
      mostrar('Este navegador não informa a localização. Use uma foto com localização gravada.', 'danger');
    } else {
      ligarGps();
      document.addEventListener('visibilitychange', function () { if (document.hidden) desligarGps(); else ligarGps(); });
      window.addEventListener('limpeza:saida', desligarGps, { once: true });
    }

    // Posição do instante da captura. Parado no mesmo lugar, o aparelho não manda
    // posição nova sozinho; por isso, ao capturar, pedimos uma leitura agora
    // (no máximo 5 s de idade). A última leitura recente vale até a nova chegar.
    var RESERVA_MS = 60000;
    var localPronto = Promise.resolve();
    function preencher(l, origem) {
      lat.value = l.latitude; lon.value = l.longitude; prec.value = l.precisao;
      mostrar('Localização da foto registrada (' + origem + ', precisão de ' + l.precisao + ' m).',
        l.precisao <= 50 ? 'success' : 'warning');
      // O rascunho guardado no aparelho (limpeza_offline.js) acompanha a posição.
      lat.dispatchEvent(new Event('change', { bubbles: true }));
    }
    function localDaCaptura(horaCaptura) {
      lat.value = lon.value = prec.value = '';
      localFoto = true;
      if (localAtual && horaCaptura - localAtual.quando < RESERVA_MS) preencher(localAtual, 'última leitura do GPS');
      if (!('geolocation' in navigator)) return Promise.resolve();
      mostrar('Registrando a localização desta foto…', 'muted');
      localPronto = new Promise(function (resolve) {
        navigator.geolocation.getCurrentPosition(function (pos) {
          guardar(pos);
          preencher(localAtual, 'GPS no momento da foto');
          resolve();
        }, function (erro) {
          if (!lat.value) falhou(erro);
          resolve();
        }, { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 });
      });
      return localPronto;
    }
    // O envio (aqui ou em limpeza_offline.js) espera a posição da foto ficar pronta.
    form.limpezaLocalPronto = function () { return localPronto; };

    // ---- Foto ----
    function localDaGaleria() {
      // Foto antiga da galeria: o GPS de agora não é o da foto. Vale só o gravado na imagem.
      lat.value = lon.value = prec.value = '';
      localFoto = true;
      localPronto = Promise.resolve();
      mostrar('Foto da galeria: a localização gravada na própria foto será usada. Sem ela, a comunicação é recusada.', 'warning');
    }

    function arquivoEscolhido() {
      for (var i = 0; i < arquivos.length; i++) {
        if (arquivos[i].files && arquivos[i].files.length) return arquivos[i].files[0];
      }
      return null;
    }

    function exibir(arquivo) {
      if (!previa) return;
      if (!arquivo) { previa.classList.add('d-none'); return; }
      try {
        previa.src = URL.createObjectURL(arquivo);
        previa.classList.remove('d-none');
      } catch (e) { /* prévia é só conforto */ }
    }

    // Só um arquivo segue: escolher pela câmera limpa a galeria e vice-versa.
    arquivos.forEach(function (campo) {
      campo.addEventListener('change', function () {
        if (campo.files && campo.files.length) {
          arquivos.forEach(function (outro) { if (outro !== campo) outro.value = ''; });
          avisar('');
          // Câmera nativa: a foto acabou de ser tirada (o arquivo chega ao fechar a câmera).
          // A captura pela câmera da página já cuidou da posição em capturar().
          if (campo === campoCamera && !fluxo) localDaCaptura(Date.now());
          else if (campo !== campoCamera) localDaGaleria();
          if (!fluxo) form.dispatchEvent(new CustomEvent('limpeza:foto', {detail: {hora: Date.now()}}));
        }
        exibir(arquivoEscolhido());
      });
    });

    function fecharCamera() {
      if (fluxo) fluxo.getTracks().forEach(function (t) { t.stop(); });
      fluxo = null;
      if (painel) painel.classList.add('d-none');
    }

    function abrirCameraNaPagina() {
      return navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
        audio: false,
      }).then(function (s) {
        fluxo = s;
        video.srcObject = s;
        painel.classList.remove('d-none');
        return video.play();
      });
    }

    function capturar() {
      if (!video || !video.videoWidth) return;
      var canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);
      var horaCaptura = Date.now();
      localDaCaptura(horaCaptura);
      canvas.toBlob(function (blob) {
        if (!blob) { avisar('Não foi possível capturar a foto. Tente de novo.'); return; }
        try {
          var dt = new DataTransfer();
          dt.items.add(new File([blob], 'foto-' + Date.now() + '.jpg', { type: 'image/jpeg' }));
          campoCamera.files = dt.files;
          campoCamera.dispatchEvent(new Event('change'));
          form.dispatchEvent(new CustomEvent('limpeza:foto', {detail: {hora: horaCaptura}}));
        } catch (e) {
          avisar('Este navegador não conseguiu usar a foto da câmera. Use "Escolher da galeria".');
        }
        fecharCamera();
      }, 'image/jpeg', 0.88);
    }

    form.addEventListener('click', function (ev) {
      var alvo = ev.target.closest('[data-limpeza-acao]');
      if (!alvo) return;
      var acao = alvo.getAttribute('data-limpeza-acao');
      if (acao === 'camera') {
        // Celular: a câmera do próprio aparelho (capture). Computador: câmera dentro da página.
        var temCamera = navigator.mediaDevices && navigator.mediaDevices.getUserMedia && video;
        if (!temCamera) { campoCamera.click(); return; }
        abrirCameraNaPagina().catch(function () {
          fecharCamera();
          avisar('Não foi possível abrir a câmera deste aparelho. Permita o acesso à câmera no navegador ' +
            'ou use o celular.' + (campoGaleria ? ' Você também pode escolher uma foto da galeria.' : ''));
          campoCamera.click();
        });
      } else if (acao === 'galeria' && campoGaleria) {
        campoGaleria.click();
      } else if (acao === 'capturar') {
        capturar();
      } else if (acao === 'fechar') {
        fecharCamera();
      }
    });

    form.addEventListener('submit', async function (ev) {
      if (form.hasAttribute('data-offline-comunicacao')) return;
      ev.preventDefault();
      var categorias = form.querySelectorAll('input[name=categoria]');
      if (categorias.length && !form.querySelector('input[name=categoria]:checked')) {
        avisar('Marque o que precisa ser limpo antes de enviar. Sua foto continua selecionada.');
        categorias[0].focus();
        return;
      }
      var outro = form.querySelector('input[name=categoria][value=outro]:checked');
      var descricao = form.querySelector('[name=descricao]');
      if (outro && descricao && !descricao.value.trim()) {
        avisar('Descreva o que precisa de atenção quando marcar Outro.');
        descricao.focus();
        return;
      }
      if (!arquivoEscolhido()) {
        avisar('Tire a foto do local antes de enviar.');
        return;
      }
      var textoBotao = botao && botao.innerHTML;
      if (botao) {
        botao.disabled = true;
        botao.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Enviando foto…';
      }
      try {
        await localPronto;
        var resposta = await fetch(form.action || window.location.href, {
          method: 'POST', body: new FormData(form), credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }
        });
        var resultado = await resposta.json();
        if (!resposta.ok || !resultado.destino) throw new Error(resultado.erro || 'Não foi possível enviar. Confira os dados e tente novamente.');
        window.location.assign(resultado.destino);
      } catch (erro) {
        avisar((erro.message || 'Falha de conexão. Confira suas comunicações antes de tentar novamente.') + ' Seus dados e sua foto continuam no formulário.');
        if (botao) { botao.disabled = false; botao.innerHTML = textoBotao; }
      }
    });

    window.addEventListener('pagehide', fecharCamera, { once: true });
    window.addEventListener('limpeza:saida', fecharCamera, { once: true });
  });
})();
