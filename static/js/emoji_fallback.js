/*
 * Emojis em computadores sem fonte de emoji colorida.
 *
 * Windows 7 (e alguns Linux) não têm fonte de emoji: os ícones em emoji do
 * site (🩺, 🐾, 📅…) viram quadrados vazios. O navegador desenha um emoji num
 * canvas; se o desenho não tiver cor, carregamos o Twemoji (imagens SVG
 * abertas, pelo jsDelivr já liberado na CSP) e cada emoji da página vira uma
 * imagem do tamanho do texto. Em aparelhos com emoji colorido nada é baixado
 * e a página continua exatamente igual.
 */
(function () {
  'use strict';

  var SCRIPT_URL = 'https://cdn.jsdelivr.net/npm/@twemoji/api@15.1.0/dist/twemoji.min.js';
  var SCRIPT_SRI = 'sha384-o28+zJO3/45GHIy+9TFKGaYnbt0KQcFRzyBrb0WSSrz7bPGwGI1d64worBiXPgXw';
  var OPTIONS = {folder: 'svg', ext: '.svg', className: 'emoji-img'};

  function hasColorEmoji() {
    try {
      var canvas = document.createElement('canvas');
      canvas.width = 32;
      canvas.height = 32;
      var context = canvas.getContext('2d');
      if (!context || typeof context.fillText !== 'function') return true;
      context.textBaseline = 'top';
      context.font = '24px sans-serif';
      context.fillStyle = '#000';
      context.fillText('😀', 0, 0);
      var pixels = context.getImageData(0, 0, 32, 32).data;
      for (var i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] && (Math.abs(pixels[i] - pixels[i + 1]) > 40 || Math.abs(pixels[i + 1] - pixels[i + 2]) > 40)) {
          return true;
        }
      }
      return false;
    } catch (error) {
      return true; // Canvas bloqueado: sem como medir, mantém o texto original.
    }
  }

  function parse(node) {
    if (node && node.nodeType === 1 && node.isConnected !== false) window.twemoji.parse(node, OPTIONS);
  }

  // Conteúdo inserido depois (formulários em segundo plano, listas
  // atualizadas) também é convertido, agrupado por quadro de animação.
  function watch() {
    if (!window.MutationObserver) return;
    var pending = [];
    var scheduled = false;
    function flush() {
      scheduled = false;
      var nodes = pending;
      pending = [];
      for (var i = 0; i < nodes.length; i += 1) parse(nodes[i]);
    }
    new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i += 1) {
        var mutation = mutations[i];
        if (mutation.type === 'characterData') {
          pending.push(mutation.target.parentNode);
        } else {
          for (var j = 0; j < mutation.addedNodes.length; j += 1) {
            var added = mutation.addedNodes[j];
            if (added.nodeType === 3) pending.push(added.parentNode);
            else if (added.nodeType === 1 && !(added.classList && added.classList.contains('emoji-img'))) pending.push(added);
          }
        }
      }
      if (pending.length && !scheduled) {
        scheduled = true;
        window.requestAnimationFrame(flush);
      }
    }).observe(document.body, {childList: true, subtree: true, characterData: true});
  }

  function start() {
    var style = document.createElement('style');
    style.textContent = 'img.emoji-img{display:inline-block;width:1.1em;height:1.1em;margin:0 .3em 0 .05em;vertical-align:-.18em;border:0}';
    document.head.appendChild(style);
    parse(document.body);
    watch();
  }

  if (hasColorEmoji()) return;
  document.documentElement.classList.add('sem-emoji-colorido');
  var script = document.createElement('script');
  script.src = SCRIPT_URL;
  script.integrity = SCRIPT_SRI;
  script.crossOrigin = 'anonymous';
  script.async = true;
  script.onload = function () {
    if (!window.twemoji) return;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  };
  document.head.appendChild(script);
})();
