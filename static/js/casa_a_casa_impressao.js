/* Roteiro A4 independente do zoom do mapa, com todos os imóveis e complementos. */
(function (root) {
  'use strict';
  root.CasaACasaImpressao = function ({ S, h, casasDe, dataBr }) {
    const M = root.CasaACasaModel;
    const dialogo = h('dialog', { id: 'cac-print-preview', class: 'cac-print-preview', 'aria-labelledby': 'cac-print-titulo' });
    document.body.append(dialogo);
    let foco;
    const svgNo = (tag, attrs, texto) => {
      const no = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [k, v] of Object.entries(attrs)) no.setAttribute(k, String(v));
      if (texto !== undefined) no.textContent = texto;
      return no;
    };
    function mapaDoBloco(bloco, casas, offset) {
      const todos = casasDe(bloco), anel = bloco.g.flatMap(p => p[0]);
      const pontos = anel.concat(todos.map(c => [c.x, c.y]));
      const xs = pontos.map(p => p[0]), ys = pontos.map(p => p[1]);
      const x0 = Math.min(...xs), y0 = Math.min(...ys), x1 = Math.max(...xs), y1 = Math.max(...ys);
      const cos = Math.cos(bloco.c[1] * Math.PI / 180);
      const escala = Math.min(580 / Math.max((x1 - x0) * cos, 0.00001), 155 / Math.max(y1 - y0, 0.00001));
      const px = x => 360 + (x - (x0 + x1) / 2) * cos * escala;
      const py = y => 110 - (y - (y0 + y1) / 2) * escala;
      const svg = svgNo('svg', { viewBox: '0 0 720 220', role: 'img', 'aria-label': `Quarteirão ${bloco.n}, localização dos imóveis desta folha. Norte para cima.` });
      for (const p of bloco.g) {
        const d = p.map(r => 'M ' + r.map(([x, y]) => `${px(x).toFixed(2)},${py(y).toFixed(2)}`).join(' L ') + ' Z').join(' ');
        svg.append(svgNo('path', { d, fill: '#e6f4f1', stroke: '#0b6568', 'stroke-width': 2, 'fill-rule': 'evenodd' }));
      }
      svg.append(svgNo('text', { x: 670, y: 24, 'text-anchor': 'middle', fill: '#12343b', 'font-size': 16 }, 'N ↑'));
      casas.forEach((c, i) => {
        svg.append(svgNo('circle', { cx: px(c.x), cy: py(c.y), r: 10, fill: '#fff', stroke: '#0b6568', 'stroke-width': 1.5 }));
        svg.append(svgNo('text', { x: px(c.x), y: py(c.y) + 4, 'text-anchor': 'middle', fill: '#12343b', 'font-size': 11, 'font-weight': 700 }, offset + i + 1));
      });
      return svg;
    }
    function folhas(blocos, dia) {
      return blocos.flatMap(bloco => {
        const casas = casasDe(bloco), paginas = M.paginasDoRoteiro(casas);
        const plano = bloco.planos.find(p => p.d === dia);
        const responsavel = plano && plano.r ? plano.r : '________________________________';
        let offset = 0;
        return paginas.map((lista, pagina) => {
          const inicio = offset;
          offset += lista.length;
          const linha = (c, i) => h('tr', {}, h('td', {}, c ? inicio + i + 1 : '+'),
            h('td', { class: 'cac-print-endereco' }, c ? [h('strong', {}, `${c.rua}, ${c.n}`), c.cp ? h('small', {}, c.cp) : null] : 'Imóvel acrescentado: __________________'),
            h('td', {}, ''), h('td', {}, ''), h('td', {}, '___ / ___ / ___'), h('td', {}, ''), h('td', {}, ''), h('td', {}, ''));
          return h('article', { class: 'cac-print-folha' },
            h('header', { class: 'cac-print-cabecalho' }, h('div', {}, h('small', {}, 'ORLÂNDIA · CONTROLE DE VETORES'), h('h1', {}, 'Roteiro casa a casa')), h('strong', {}, `Q ${bloco.n}`, h('small', {}, `SC ${bloco.s}`))),
            h('div', { class: 'cac-print-meta' }, h('p', {}, h('strong', {}, 'Data: '), `${dataBr(dia)}/${dia.slice(0, 4)}`), h('p', {}, h('strong', {}, 'Trabalhador: '), responsavel),
              h('p', {}, `${casas.length} imóveis previstos · Folha ${pagina + 1} de ${paginas.length}${bloco.d ? ' · ' + bloco.d : ''}`)),
            h('div', { class: 'cac-print-mapa' }, mapaDoBloco(bloco, lista, inicio), h('p', {}, 'Números no desenho = ordem na tabela desta folha. Siga a lista e confira os endereços em campo.')),
            !casas.length ? h('p', { class: 'cac-print-atencao' }, 'Sem imóveis numerados na base deste quarteirão. Levante e anote os endereços em campo.') : null,
            h('table', { class: 'cac-print-tabela' }, h('thead', {}, h('tr', {}, ['#', 'Rua, número e complemento', 'Hora', 'Sit.', 'Recipientes E / A / L', 'Tub.', 'Controle', 'Observações'].map(t => h('th', { scope: 'col' }, t)))),
              h('tbody', {}, lista.map(linha), Array.from({ length: casas.length ? 2 : 8 }, (_, i) => linha(null, i)))),
            h('div', { class: 'cac-print-chaves' }, h('p', {}, 'Situação: T Trabalhado · F Fechado · D Desocupado · V Temporada · P Parcial · R Recusa.'),
              h('p', {}, 'Recipientes: E existentes · A com água · L com larva. Controle: M mecânico · A alternativo · F focal.'),
              h('p', {}, 'Anote o tipo (1–40) e a quantidade de recipientes nas observações ou na ficha complementar.')),
            h('footer', { class: 'cac-print-rodape' }, h('p', {}, 'Conferência: T ____ F ____ D ____ V ____ P ____ R ____ · Assinatura: __________________'),
              h('small', {}, `Planejamento não comprova visita. Base de endereços: ${S.base.versao}. Imóveis fora da base devem ser anotados nas linhas extras.`)));
        });
      });
    }

    function abrir(opcoes = {}) {
      const dia = S.diaPlano || S.hoje;
      const previstos = S.blocos.filter(b => b.planos.some(p => p.d === dia));
      const iniciais = opcoes.bloco ? [opcoes.bloco] : previstos;
      const grupos = M.agendaDoDia(iniciais, dia);
      const escolher = h('select', { 'aria-label': 'Trabalhador para impressão' }, h('option', { value: 'todos' }, 'Toda a equipe'),
        grupos.map(g => h('option', { value: String(g.id), selected: Object.hasOwn(opcoes, 'responsavel') && g.id === opcoes.responsavel }, g.nome)));
      const paginas = h('div', { class: 'cac-print-paginas' });
      const resumo = h('p', { id: 'cac-print-resumo', role: 'status' });
      const imprimir = h('button', { type: 'button', class: 'cac-botao forte', onclick: () => { dialogo.close(); window.print(); } }, 'Imprimir / salvar PDF');
      const fechar = () => { dialogo.close(); };
      function atualizar() {
        const blocos = iniciais.filter(b => escolher.value === 'todos' || String(b.planos.find(p => p.d === dia)?.ri || null) === escolher.value)
          .sort((a, b) => String(a.s).localeCompare(String(b.s), 'pt-BR', { numeric: true }) || String(a.n).localeCompare(String(b.n), 'pt-BR', { numeric: true }));
        const conteudo = folhas(blocos, dia);
        paginas.replaceChildren(...conteudo);
        $('cac-impressao').replaceChildren(...conteudo.map(p => p.cloneNode(true)));
        $('cac-impressao').setAttribute('aria-hidden', 'false');
        imprimir.disabled = !blocos.length;
        resumo.textContent = `${dataBr(dia)}/${dia.slice(0, 4)} · ${blocos.length} ${blocos.length === 1 ? 'quarteirão' : 'quarteirões'} · ${blocos.reduce((n, b) => n + casasDe(b).length, 0)} imóveis · ${conteudo.length} folhas A4`;
        if (!conteudo.length) paginas.append(h('p', { class: 'cac-vazio' }, 'Não há quarteirões planejados neste dia.'));
      }
      const $ = id => document.getElementById(id);
      escolher.addEventListener('change', atualizar);
      dialogo.replaceChildren(h('header', { class: 'cac-print-barra' },
        h('div', {}, h('h2', { id: 'cac-print-titulo' }, 'Roteiro pronto para levar'), resumo),
        escolher, imprimir, h('button', { type: 'button', class: 'cac-botao', onclick: fechar }, 'Fechar prévia')),
        h('p', { class: 'cac-print-ajuda' }, 'A4 retrato · todos os imóveis previstos, com complemento e espaço para anotar · impressão também em preto e branco.'), paginas);
      atualizar();
      foco = document.activeElement;
      dialogo.showModal();
    }
    dialogo.addEventListener('close', () => { if (foco?.isConnected) foco.focus(); });
    function preparar() {
      if (!document.getElementById('cac-impressao').children.length) {
        const dia = S.diaPlano || S.hoje;
        document.getElementById('cac-impressao').replaceChildren(...folhas(S.blocos.filter(b => b.planos.some(p => p.d === dia)), dia));
      }
    }
    return { abrir, preparar };
  };
})(window);
