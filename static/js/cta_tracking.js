/**
 * Rastreia cliques nos CTAs de aquisição — o topo do funil.
 *
 * Sem isso só sabemos quem terminou o cadastro (`signup_completed`), e não
 * quantos chegaram a clicar em "começar". A diferença entre os dois é
 * exatamente onde as pessoas desistem.
 *
 * Marque um link ou botão com `data-cta="nome_do_evento"`. Links que levam ao
 * cadastro ou ao login são detectados sozinhos, sem precisar de atributo.
 */
(function () {
  'use strict';

  var enviados = Object.create(null);

  function rotuloAutomatico(el) {
    var href = el.getAttribute('href') || '';
    if (href.indexOf('/register') !== -1) return 'cta_criar_conta';
    if (href.indexOf('/login') !== -1) return 'cta_entrar';
    if (href.indexOf('/precos') !== -1) return 'cta_precos';
    if (href.indexOf('wa.me') !== -1) return 'cta_whatsapp';
    return null;
  }

  function envia(nome, el) {
    // Um clique repetido no mesmo CTA na mesma página não é sinal novo.
    var chave = nome + '|' + (el.getAttribute('href') || '');
    if (enviados[chave]) return;
    enviados[chave] = true;

    var destino = el.getAttribute('href') || '';
    var texto = (el.textContent || '').trim().slice(0, 60);

    if (typeof window.gtag === 'function') {
      window.gtag('event', nome, {
        link_url: destino,
        link_text: texto,
        page_path: window.location.pathname
      });
    }

    // Espelha no log do servidor: o GA pode estar desligado ou bloqueado por
    // extensão, e o funil precisa existir de qualquer forma.
    try {
      var payload = JSON.stringify({
        name: nome,
        path: window.location.pathname,
        text: texto
      });
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/eventos/cta', new Blob([payload], { type: 'application/json' }));
      }
    } catch (e) {
      /* telemetria nunca pode atrapalhar a navegação */
    }
  }

  document.addEventListener('click', function (event) {
    var el = event.target.closest('a, button');
    if (!el) return;

    var nome = el.getAttribute('data-cta') || rotuloAutomatico(el);
    if (!nome) return;

    envia(nome, el);
  }, { passive: true });
})();
