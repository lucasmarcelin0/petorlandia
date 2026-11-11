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
      if (melhor && c.accuracy > melhor.accuracy && (Date.now() - melhor.quando) < 60000) return;
      melhor = { accuracy: c.accuracy, quando: Date.now() };
      lat.value = c.latitude.toFixed(7);
      lon.value = c.longitude.toFixed(7);
      prec.value = Math.round(c.accuracy);
      var ok = c.accuracy <= 50;
      mostrar('Localização registrada (precisão de ' + Math.round(c.accuracy) + ' m)' +
        (ok ? '.' : '. Se puder, vá para céu aberto para melhorar.'), ok ? 'success' : 'warning');
    }

    function falhou(erro) {
      if (lat.value) return;
      var msg = erro && erro.code === 1
        ? 'Localização bloqueada. Permita o acesso à localização para este site ou use uma foto com localização gravada.'
        : 'Não foi possível obter a localização agora. Fotos com localização gravada também são aceitas.';
      mostrar(msg, 'danger');
    }

    if (!('geolocation' in navigator)) {
      mostrar('Este navegador não informa a localização. Use uma foto com localização gravada.', 'danger');
    } else {
      var vigia = navigator.geolocation.watchPosition(guardar, falhou,
        { enableHighAccuracy: true, maximumAge: 15000, timeout: 30000 });
      // Depois de 3 minutos, para de gastar bateria; a última posição boa fica no formulário.
      setTimeout(function () { navigator.geolocation.clearWatch(vigia); }, 180000);
      window.addEventListener('limpeza:saida', function () { navigator.geolocation.clearWatch(vigia); }, { once: true });
    }

    // ---- Foto ----
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
      canvas.toBlob(function (blob) {
        if (!blob) { avisar('Não foi possível capturar a foto. Tente de novo.'); return; }
        try {
          var dt = new DataTransfer();
          dt.items.add(new File([blob], 'foto-' + Date.now() + '.jpg', { type: 'image/jpeg' }));
          campoCamera.files = dt.files;
          campoCamera.dispatchEvent(new Event('change'));
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
        if (celular || !temCamera) { campoCamera.click(); return; }
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
      ev.preventDefault();
      var categorias = form.querySelectorAll('input[name=categoria]');
      if (categorias.length && !form.querySelector('input[name=categoria]:checked')) {
        avisar('Marque o que precisa ser limpo antes de enviar. Sua foto continua selecionada.');
        categorias[0].focus();
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
