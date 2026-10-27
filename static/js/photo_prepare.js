/*
 * Reduz a foto no próprio aparelho antes do envio.
 *
 * Foto de celular sai com 12 MP e 3 a 5 MB. Pela rede móvel do interior isso
 * levava mais que o tempo limite do envio: a tela mostrava "Não foi possível
 * enviar" e, no servidor, o pedaço que chegou virava um formulário vazio (era
 * a origem dos animais com nome "None"). Reduzida para 1600 px, a mesma foto
 * vira ~250 KB e sobe em poucos segundos.
 *
 * Mesmo critério do painel da vacinação (templates/vacina_pmo/dashboard.html):
 * lado maior de 1600 px, JPEG 0,82, e nunca devolver algo maior que o
 * original. PNG/GIF/SVG passam intactos (logos com transparência). Se o
 * navegador não conseguir decodificar (HEIC no Android, navegador antigo), o
 * arquivo original segue e o servidor converte.
 */
(function (window) {
  'use strict';

  var MAX_SIDE = 1600;
  var QUALITY = 0.82;
  var RAW_LIMIT = 500 * 1024; // abaixo disto não há o que ganhar
  var KEEP_TYPES = ['image/png', 'image/gif', 'image/svg+xml'];
  var IMAGE_EXT = /\.(jpe?g|webp|heic|heif|avif|bmp|tiff?)$/i;

  function shouldReduce(file) {
    if (!file || typeof file.size !== 'number') return false;
    var type = String(file.type || '').toLowerCase();
    if (KEEP_TYPES.indexOf(type) !== -1) return false;
    if (file.size <= RAW_LIMIT) return false;
    if (type.indexOf('image/') === 0) return true;
    // Alguns seletores (Google Fotos, Arquivos) mandam sem tipo.
    return (!type || type === 'application/octet-stream') && IMAGE_EXT.test(String(file.name || ''));
  }

  function canvasToBlob(canvas, type, quality) {
    return new Promise(function (resolve) {
      try {
        canvas.toBlob(resolve, type, quality);
      } catch (err) {
        resolve(null);
      }
    });
  }

  async function prepare(file) {
    if (!shouldReduce(file) || typeof window.createImageBitmap !== 'function') {
      return file;
    }
    try {
      var bitmap = await window.createImageBitmap(file, { imageOrientation: 'from-image' });
      var scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
      var canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      var ctx = canvas.getContext('2d');
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      if (typeof bitmap.close === 'function') bitmap.close();
      var blob = await canvasToBlob(canvas, 'image/jpeg', QUALITY);
      if (!blob || blob.size >= file.size) return file;
      var base = String(file.name || 'foto').replace(/\.[^.]+$/, '') || 'foto';
      return new File([blob], base + '.jpg', { type: 'image/jpeg', lastModified: Date.now() });
    } catch (err) {
      return file;
    }
  }

  // Troca o arquivo de um <input type="file"> sem disparar "change".
  function replaceInputFile(input, file) {
    if (!input || !file || typeof window.DataTransfer !== 'function') return false;
    try {
      var dt = new window.DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      return input.files && input.files[0] === file;
    } catch (err) {
      return false;
    }
  }

  // Reduz o arquivo escolhido no input e guarda a promessa no próprio
  // elemento, para quem for enviar o formulário poder esperar terminar.
  function prepareInput(input, file) {
    var original = file || (input && input.files && input.files[0]);
    if (!input || !original) return Promise.resolve(original || null);
    input.dataset.photoPreparing = '1';
    var pending = prepare(original).then(function (result) {
      // Se outra foto foi escolhida no meio do caminho, não sobrescreve.
      var current = input.files && input.files[0];
      if (result !== original && current === original) {
        replaceInputFile(input, result);
      }
      return result;
    }).catch(function () {
      return original;
    }).finally(function () {
      if (input.__petPhotoPending === pending) {
        delete input.dataset.photoPreparing;
        input.__petPhotoPending = null;
      }
    });
    input.__petPhotoPending = pending;
    return pending;
  }

  // Espera as fotos ainda em preparo dentro de um formulário (no máximo
  // ``timeoutMs``; depois disso envia o que houver).
  function waitForm(form, timeoutMs) {
    if (!form || !form.querySelectorAll) return Promise.resolve();
    var pendings = [];
    form.querySelectorAll('input[type="file"]').forEach(function (input) {
      if (input.__petPhotoPending) pendings.push(input.__petPhotoPending);
    });
    if (!pendings.length) return Promise.resolve();
    var limit = new Promise(function (resolve) { window.setTimeout(resolve, timeoutMs || 8000); });
    return Promise.race([Promise.all(pendings), limit]).then(function () {});
  }

  // Há arquivo de verdade para subir neste formulário?
  function formHasFile(form) {
    if (!form || !form.querySelectorAll) return false;
    return Array.prototype.some.call(form.querySelectorAll('input[type="file"]'), function (input) {
      return !input.disabled && input.files && input.files.length > 0 && input.files[0].size > 0;
    });
  }

  window.PetPhoto = {
    prepare: prepare,
    prepareInput: prepareInput,
    waitForm: waitForm,
    formHasFile: formHasFile,
    replaceInputFile: replaceInputFile,
    MAX_SIDE: MAX_SIDE,
  };
})(window);
