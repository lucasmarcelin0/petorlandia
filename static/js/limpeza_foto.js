// Limpeza urbana: prévia da foto e posição do aparelho nos formulários com [data-limpeza-foto].
// O servidor prefere o GPS gravado na própria foto; a posição do aparelho cobre a câmera
// do navegador, que costuma remover o GPS da imagem.
(function () {
  'use strict';
  document.querySelectorAll('form[data-limpeza-foto]').forEach(function (form) {
    var campo = form.querySelector('input[type=file][name=foto]');
    var previa = form.querySelector('.limpeza-previa');
    var status = form.querySelector('.limpeza-gps');
    var texto = status && status.querySelector('span');
    var lat = form.querySelector('input[name=latitude]');
    var lon = form.querySelector('input[name=longitude]');
    var prec = form.querySelector('input[name=precisao]');
    var botao = form.querySelector('button[type=submit]');
    var melhor = null;

    function mostrar(msg, tom) {
      if (!status) return;
      status.className = 'limpeza-gps small mt-2 text-' + (tom || 'muted');
      if (texto) texto.textContent = msg;
    }

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
      var opcoes = { enableHighAccuracy: true, maximumAge: 15000, timeout: 30000 };
      var vigia = navigator.geolocation.watchPosition(guardar, falhou, opcoes);
      // Depois de 3 minutos, para de gastar bateria; a última posição boa fica no formulário.
      setTimeout(function () { navigator.geolocation.clearWatch(vigia); }, 180000);
    }

    if (campo && previa) {
      campo.addEventListener('change', function () {
        var arquivo = campo.files && campo.files[0];
        if (!arquivo) { previa.classList.add('d-none'); return; }
        try {
          previa.src = URL.createObjectURL(arquivo);
          previa.classList.remove('d-none');
        } catch (e) { /* prévia é só conforto */ }
      });
    }

    form.addEventListener('submit', function () {
      if (botao) {
        botao.disabled = true;
        botao.dataset.texto = botao.innerHTML;
        botao.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Enviando foto…';
      }
    });
  });
})();
