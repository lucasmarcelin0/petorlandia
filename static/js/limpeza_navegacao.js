// Navegação das seções sem descartar um formulário em andamento.
(function () {
  'use strict';
  let carregando = false;
  function temRascunho() {
    const form = document.querySelector('.limpeza-pagina form[data-limpeza-foto]');
    return form && Array.from(form.elements).some(el =>
      (el.type === 'file' && el.files.length) || (el.type === 'checkbox' && el.checked) ||
      (['referencia', 'descricao', 'observacao'].includes(el.name) && el.value.trim()));
  }
  async function abrir(url, historico) {
    if (carregando) return;
    carregando = true;
    try {
      const resposta = await fetch(url, { credentials: 'same-origin' });
      if (!resposta.ok || resposta.redirected) throw new Error('Navegação indisponível');
      const doc = new DOMParser().parseFromString(await resposta.text(), 'text/html');
      const nova = doc.querySelector('.limpeza-pagina');
      const atual = document.querySelector('.limpeza-pagina');
      if (!nova || !atual) throw new Error('Página indisponível');
      window.dispatchEvent(new Event('limpeza:saida'));
      atual.replaceWith(nova);
      document.title = doc.title;
      if (historico) history.pushState({ limpeza: true }, '', url);
      const scripts = doc.querySelectorAll('main > script');
      for (const original of scripts) {
        const script = document.createElement('script');
        if (original.src) {
          if (original.src.includes('/leaflet/leaflet.js') && window.L) continue;
          script.src = original.src;
          await new Promise((resolve, reject) => {
            script.onload = resolve; script.onerror = reject; document.body.appendChild(script);
          });
        } else {
          script.textContent = original.textContent;
          document.body.appendChild(script);
        }
        script.remove();
      }
      nova.scrollIntoView({ block: 'start' });
    } catch (erro) {
      window.location.href = url;
    } finally { carregando = false; }
  }
  document.addEventListener('click', function (evento) {
    const link = evento.target.closest('.limpeza-nav a');
    if (!link || evento.button !== 0 || evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey) return;
    evento.preventDefault();
    if (temRascunho() && !window.confirm('Você tem dados ou uma foto não enviados. Deseja sair mesmo assim?')) return;
    abrir(link.href, true);
  });
  window.addEventListener('popstate', function () {
    if (temRascunho() && !window.confirm('Você tem dados ou uma foto não enviados. Deseja sair mesmo assim?')) {
      history.forward(); return;
    }
    abrir(window.location.href, false);
  });
})();
