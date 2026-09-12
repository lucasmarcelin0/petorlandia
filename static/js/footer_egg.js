// A porta da pagina secreta de jogos (/surpresa), escondida no rodape.
//
// O acesso era um link de patinha sempre visivel, e sumiu no redesenho do
// rodape (680c40b). Voltou escondido: clicar no "© 2026 PetOrlandia." revela a
// patinha. Um segredo que aparece sozinho nao e segredo, e um que nao da para
// achar de novo vira frustracao -- entao a descoberta fica guardada neste
// aparelho e a patinha continua la nas proximas visitas.
(function () {
  'use strict';

  const CHAVE = 'petorlandia:footer-egg-aberto';

  function lembrar(aberto) {
    // Navegador anonimo, site data bloqueado ou cota estourada: a memoria e
    // um conforto, nao um requisito. O easter egg funciona sem ela.
    try {
      if (aberto) {
        localStorage.setItem(CHAVE, '1');
      } else {
        localStorage.removeItem(CHAVE);
      }
    } catch (_erro) {
      /* segue sem lembrar */
    }
  }

  function lembrado() {
    try {
      return localStorage.getItem(CHAVE) === '1';
    } catch (_erro) {
      return false;
    }
  }

  function iniciar() {
    const gatilho = document.getElementById('footer-egg-key');
    const link = document.getElementById('footer-egg-link');
    if (!gatilho || !link) return;

    function aplicar(aberto, comAnimacao) {
      link.hidden = !aberto;
      gatilho.setAttribute('aria-expanded', aberto ? 'true' : 'false');
      // Na restauracao a patinha ja estava la: animar a entrada faria parecer
      // que acabou de ser descoberta de novo.
      if (aberto && !comAnimacao) link.style.animation = 'none';
    }

    if (lembrado()) aplicar(true, false);

    gatilho.addEventListener('click', () => {
      const abrindo = link.hidden;
      link.style.animation = '';
      aplicar(abrindo, true);
      lembrar(abrindo);
      // Quem abriu com o teclado precisa chegar na patinha sem cacar o foco.
      if (abrindo) link.focus({ preventScroll: true });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
