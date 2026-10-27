/* Visualizador de fotos do site inteiro: tocar numa foto abre ela grande.
 *
 * Mesmo visual que nasceu no prontuário (.photo-lightbox, em styles.css).
 * Funciona por delegação, então vale também para fotos que chegam depois
 * (listas por AJAX, fichas recarregadas).
 *
 * Não amplia o que já tem outra função ao tocar: foto dentro de link,
 * botão ou rótulo, editor de recorte, fotos com visualizador próprio
 * (vacinação), ícones pequenos e imagens decorativas (alt=""). Para
 * excluir uma imagem de propósito, use data-no-zoom; para mostrar outra
 * versão ao ampliar, data-zoom-src; para a legenda, data-zoom-caption.
 */
(function () {
  'use strict';

  if (window.PhotoLightbox) {
    return;
  }

  var AREA = 'main, .modal';
  var EXCLUIR = [
    'a', 'button', 'label', 'summary', 'select', 'input', 'textarea',
    '[role="button"]', '[role="link"]', '[role="option"]', '[role="tab"]',
    '[onclick]', '[data-action]', '[data-bs-toggle]', '[data-href]', '[data-url]',
    '.dropdown-item', '.list-group-item-action',
    '[data-no-zoom]', '[data-zoom-src]:not(img)',
    '.photo-cropper', '.photo-lightbox', '.pmo-lightbox', '.pmo-photo-modal',
  ].join(', ');
  var TAMANHO_MINIMO = 48; // px na tela: abaixo disso é ícone, não foto
  var ALT_GENERICO = /^(imagem( atual)?|foto|image|photo|preview|pr[eé]-visualiza[cç][aã]o)$/i;

  var overlay = null;
  var imagem = null;
  var legenda = null;
  var abrirOriginal = null;
  var fechar = null;
  var focoAnterior = null;

  function montar() {
    if (overlay) {
      return;
    }
    overlay = document.createElement('div');
    overlay.className = 'photo-lightbox';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Visualização da foto');

    fechar = document.createElement('button');
    fechar.type = 'button';
    fechar.className = 'photo-lightbox__close';
    fechar.setAttribute('aria-label', 'Fechar');
    fechar.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i>';

    var moldura = document.createElement('div');
    moldura.className = 'photo-lightbox__frame';
    imagem = document.createElement('img');
    imagem.className = 'photo-lightbox__img';
    imagem.alt = 'Foto ampliada';
    moldura.appendChild(imagem);

    legenda = document.createElement('p');
    legenda.className = 'photo-lightbox__caption';

    var acoes = document.createElement('div');
    acoes.className = 'photo-lightbox__actions';
    abrirOriginal = document.createElement('a');
    abrirOriginal.className = 'btn btn-light btn-sm';
    abrirOriginal.target = '_blank';
    abrirOriginal.rel = 'noopener';
    abrirOriginal.innerHTML = '<i class="fa-solid fa-up-right-from-square me-1" aria-hidden="true"></i>Abrir original';
    acoes.appendChild(abrirOriginal);

    overlay.append(fechar, moldura, legenda, acoes);
    document.body.appendChild(overlay);

    fechar.addEventListener('click', fecharVisualizador);
    overlay.addEventListener('click', function (evento) {
      // Fora da foto (fundo escuro ou legenda) fecha; na foto, não.
      if (evento.target === overlay || evento.target === legenda) {
        fecharVisualizador();
      }
    });
    document.addEventListener('keydown', function (evento) {
      if (evento.key === 'Escape' && overlay.classList.contains('is-open')) {
        evento.preventDefault();
        fecharVisualizador();
      }
    });
  }

  function abrir(src, texto, origem) {
    if (!src) {
      return;
    }
    montar();
    focoAnterior = origem || document.activeElement;
    imagem.src = src;
    imagem.alt = texto || 'Foto ampliada';
    legenda.textContent = texto || '';
    legenda.hidden = !texto;
    var ehDado = src.indexOf('data:') === 0 || src.indexOf('blob:') === 0;
    abrirOriginal.hidden = ehDado;
    abrirOriginal.href = ehDado ? '#' : src;
    overlay.classList.add('is-open');
    document.documentElement.classList.add('photo-lightbox-aberto');
    fechar.focus({ preventScroll: true });
  }

  function fecharVisualizador() {
    if (!overlay || !overlay.classList.contains('is-open')) {
      return;
    }
    overlay.classList.remove('is-open');
    document.documentElement.classList.remove('photo-lightbox-aberto');
    imagem.removeAttribute('src');
    if (focoAnterior && typeof focoAnterior.focus === 'function' && document.contains(focoAnterior)) {
      focoAnterior.focus({ preventScroll: true });
    }
    focoAnterior = null;
  }

  function fonte(img) {
    return img.getAttribute('data-zoom-src') || img.currentSrc || img.src || '';
  }

  // Na tela (clique) mede o tamanho exibido; na marcação, que roda também
  // para fotos em abas ainda escondidas, mede o tamanho do arquivo.
  function pequenaDemais(img, naTela) {
    if (naTela) {
      var caixa = img.getBoundingClientRect();
      return caixa.width < TAMANHO_MINIMO && caixa.height < TAMANHO_MINIMO;
    }
    return img.naturalWidth < TAMANHO_MINIMO && img.naturalHeight < TAMANHO_MINIMO;
  }

  function podeAmpliar(img, naTela) {
    if (!img || img.tagName !== 'IMG' || !img.closest(AREA)) {
      return false;
    }
    if (img.closest(EXCLUIR)) {
      return false;
    }
    if (img.hasAttribute('data-photo-placeholder') || img.getAttribute('aria-hidden') === 'true') {
      return false;
    }
    var alt = img.getAttribute('alt');
    if (alt !== null && alt.trim() === '' && !img.hasAttribute('data-zoom')) {
      return false; // decorativa
    }
    var src = fonte(img);
    if (!src || /\.svg(\?|#|$)/i.test(src) || /placeholder|default_(animal|user)\.png/i.test(src)) {
      return false;
    }
    if (img.complete && img.naturalWidth === 0) {
      return false; // não carregou
    }
    return !pequenaDemais(img, naTela);
  }

  function textoDaLegenda(img) {
    var texto = (img.getAttribute('data-zoom-caption') || img.getAttribute('alt') || '').trim();
    return ALT_GENERICO.test(texto) ? '' : texto;
  }

  // Cursor de lupa e acesso por teclado nas fotos que ampliam.
  function marcar(img) {
    if (img.dataset.zoomPronto) {
      return;
    }
    if (!img.complete) {
      img.addEventListener('load', function () { marcar(img); }, { once: true });
      return;
    }
    img.dataset.zoomPronto = '1';
    if (!podeAmpliar(img, false)) {
      return;
    }
    img.classList.add('photo-zoomable');
    if (!img.hasAttribute('tabindex')) {
      img.tabIndex = 0;
    }
    if (!img.hasAttribute('title')) {
      img.title = 'Toque para ampliar';
    }
  }

  function marcarTodas(raiz) {
    var lista = (raiz || document).querySelectorAll ? (raiz || document).querySelectorAll('img') : [];
    for (var i = 0; i < lista.length; i += 1) {
      marcar(lista[i]);
    }
  }

  document.addEventListener('click', function (evento) {
    if (evento.defaultPrevented || evento.button !== 0) {
      return;
    }
    var img = evento.target;
    if (!podeAmpliar(img, true)) {
      return;
    }
    evento.preventDefault();
    abrir(fonte(img), textoDaLegenda(img), img);
  });

  document.addEventListener('keydown', function (evento) {
    if (evento.key !== 'Enter' && evento.key !== ' ') {
      return;
    }
    var img = evento.target;
    if (!img || !img.classList || !img.classList.contains('photo-zoomable') || !podeAmpliar(img, true)) {
      return;
    }
    evento.preventDefault();
    abrir(fonte(img), textoDaLegenda(img), img);
  });

  function iniciar() {
    marcarTodas(document);
    if (!('MutationObserver' in window)) {
      return;
    }
    var pendente = false;
    new MutationObserver(function () {
      if (pendente) {
        return;
      }
      pendente = true;
      window.requestAnimationFrame(function () {
        pendente = false;
        marcarTodas(document);
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  window.PhotoLightbox = { open: abrir, close: fecharVisualizador };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
