/* Roteiro A4 independente do zoom do mapa, com todos os imóveis e complementos. */
(function (root) {
  'use strict';
  const distancia = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  function projetar(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1], tamanho = dx * dx + dy * dy;
    const t = tamanho ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / tamanho)) : 0;
    return [a[0] + t * dx, a[1] + t * dy];
  }
  function quebrarNome(nome, limite) {
    const linhas = [];
    for (const palavra of nome.split(/\s+/)) {
      if (linhas.length && (linhas.at(-1) + ' ' + palavra).length <= limite) linhas[linhas.length - 1] += ' ' + palavra;
      else linhas.push(palavra);
    }
    return linhas;
  }
  // Geometria pura: preserva as posições e separa os identificadores da tabela.
  function desenhoDoBloco(bloco, todos, casas, offset, vias = {}) {
    const cos = Math.cos(bloco.c[1] * Math.PI / 180), origem = bloco.c;
    const metro = ([x, y]) => [(x - origem[0]) * 111320 * cos, (y - origem[1]) * 110540];
    const aneis = bloco.g.map(p => p[0].map(metro));
    const pontos = aneis.flat(), xs = pontos.map(p => p[0]), ys = pontos.map(p => p[1]);
    const caixa = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    const escala = Math.min(420 / Math.max(caixa[2] - caixa[0], 1), 225 / Math.max(caixa[3] - caixa[1], 1));
    const tela = ([x, y]) => [360 + (x - (caixa[0] + caixa[2]) / 2) * escala, 170 - (y - (caixa[1] + caixa[3]) / 2) * escala];
    const limites = [tela([caixa[0], caixa[3]])[0], tela([caixa[0], caixa[3]])[1], tela([caixa[2], caixa[1]])[0], tela([caixa[2], caixa[1]])[1]];
    const segmentos = (vias.linhas || []).flatMap(([nome, linha]) => linha.slice(1).map((p, i) => ({ a: metro(linha[i]), b: metro(p), nome: vias.nomes[nome] })));
    const lados = aneis.flatMap(anel => {
      const area = anel.slice(1).reduce((soma, p, i) => soma + anel[i][0] * p[1] - p[0] * anel[i][1], 0);
      return anel.slice(1).flatMap((b, i) => {
        const a = anel[i], comprimento = distancia(a, b);
        if (comprimento < 8) return [];
        const meio = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], dx = (b[0] - a[0]) / comprimento, dy = (b[1] - a[1]) / comprimento;
        const normal = area > 0 ? [dy, -dx] : [-dy, dx];
        let melhor = null, custo = Infinity;
        for (const s of segmentos) {
          const tamanho = distancia(s.a, s.b);
          if (!tamanho) continue;
          const paralelo = Math.abs((s.b[0] - s.a[0]) / tamanho * dx + (s.b[1] - s.a[1]) / tamanho * dy);
          if (paralelo < .88) continue;
          const perto = projetar(meio, s.a, s.b), d = distancia(meio, perto);
          // Exclui a rua do lado oposto, mesmo em quarteirões estreitos.
          if (d > 40 || (perto[0] - meio[0]) * normal[0] + (perto[1] - meio[1]) * normal[1] < -2) continue;
          const atual = d + (1 - paralelo) * 10;
          if (atual < custo) { melhor = s.nome; custo = atual; }
        }
        // Compatibilidade com a base já guardada no aparelho: usa todos os imóveis,
        // nunca só os que aparecem na folha atual.
        if (!melhor) {
          const nomes = new Map();
          for (const c of todos) if (c.rua && distancia(metro([c.x, c.y]), projetar(metro([c.x, c.y]), a, b)) < 15) nomes.set(c.rua, (nomes.get(c.rua) || 0) + 1);
          melhor = [...nomes].sort((a, b) => b[1] - a[1])[0]?.[0];
        }
        const ta = tela(a), tb = tela(b);
        let giro = Math.atan2(tb[1] - ta[1], tb[0] - ta[0]) * 180 / Math.PI;
        if (giro > 90) giro -= 180;
        if (giro < -90) giro += 180;
        const texto = quebrarNome(melhor || 'Via não identificada na base', Math.max(12, Math.floor(comprimento * escala / 7.5)));
        const recuo = 14 + texto.length * 8;
        const centro = tela(meio);
        return [{ a: ta, b: tb, normal: [normal[0], -normal[1]], nome: melhor || '', texto, giro,
          x: centro[0] - normal[0] * recuo, y: centro[1] + normal[1] * recuo }];
      });
    });
    const grupos = { cima: [], direita: [], baixo: [], esquerda: [] };
    casas.forEach((c, i) => {
      const ponto = tela(metro([c.x, c.y]));
      const lado = lados.reduce((melhor, l) => distancia(ponto, projetar(ponto, l.a, l.b)) < distancia(ponto, projetar(ponto, melhor.a, melhor.b)) ? l : melhor, lados[0]);
      const n = lado?.normal || [0, -1];
      const grupo = Math.abs(n[0]) > Math.abs(n[1]) ? (n[0] > 0 ? 'direita' : 'esquerda') : (n[1] > 0 ? 'baixo' : 'cima');
      grupos[grupo].push({ ponto, numero: offset + i + 1, id: c.id });
    });
    const marcadores = [];
    for (const [grupo, lista] of Object.entries(grupos)) {
      const vertical = grupo === 'esquerda' || grupo === 'direita', eixo = vertical ? 1 : 0;
      const minimo = vertical ? Math.min(limites[1] + 12, 46) : Math.min(limites[0] + 12, 150);
      const maximo = vertical ? Math.max(limites[3] - 12, 294) : Math.max(limites[2] - 12, 570);
      const capacidade = Math.floor((maximo - minimo) / 28) + 1, colunas = Math.ceil(lista.length / capacidade);
      lista.sort((a, b) => a.ponto[eixo] - b.ponto[eixo] || a.numero - b.numero);
      for (let coluna = 0; coluna < colunas; coluna += 1) {
        const trecho = lista.slice(coluna * capacidade, (coluna + 1) * capacidade);
        const posicoes = trecho.map((m, i) => Math.max(minimo + i * 28, Math.min(maximo, m.ponto[eixo])));
        for (let i = 1; i < posicoes.length; i += 1) posicoes[i] = Math.max(posicoes[i], posicoes[i - 1] + 28);
        if (posicoes.at(-1) > maximo) {
          posicoes[posicoes.length - 1] = maximo;
          for (let i = posicoes.length - 2; i >= 0; i -= 1) posicoes[i] = Math.min(posicoes[i], posicoes[i + 1] - 28);
        }
        trecho.forEach((m, i) => {
          const longe = 24 + coluna * 28;
          let ponto = vertical ? [grupo === 'esquerda' ? limites[0] - longe : limites[2] + longe, posicoes[i]]
            : [posicoes[i], grupo === 'cima' ? limites[1] - longe : limites[3] + longe];
          // Nas esquinas, as duas fileiras também precisam de espaço entre si.
          const livre = p => p[0] >= 16 && p[0] <= 704 && p[1] >= 16 && p[1] <= 324 && marcadores.every(outro => distancia(p, [outro.x, outro.y]) >= 27);
          if (!livre(ponto)) {
            busca: for (let r = 28; r <= 168; r += 14) for (let angulo = 0; angulo < 360; angulo += 30) {
              const candidato = [ponto[0] + Math.cos(angulo * Math.PI / 180) * r, ponto[1] + Math.sin(angulo * Math.PI / 180) * r];
              if (livre(candidato)) { ponto = candidato; break busca; }
            }
          }
          marcadores.push({ ...m, x: ponto[0], y: ponto[1] });
        });
      }
    }
    return { poligonos: bloco.g.map(p => p.map(anel => anel.map(ponto => tela(metro(ponto))))), lados, marcadores };
  }
  root.CasaACasaDesenhoImpressao = desenhoDoBloco;
  if (typeof module !== 'undefined' && module.exports) module.exports = { desenhoDoBloco };
  root.CasaACasaImpressao = function ({ S, h, casasDe, dataBr, nomeDaParte = p => p, nomeDaAtividade = () => '' }) {
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
      const desenho = desenhoDoBloco(bloco, casasDe(bloco), casas, offset, S.base.vias);
      const svg = svgNo('svg', { viewBox: '0 0 720 340', role: 'img', 'aria-label': `Quarteirão ${bloco.n}, ruas de cada lado e localização dos imóveis desta folha. Norte para cima.` });
      for (const p of desenho.poligonos) {
        const d = p.map(r => 'M ' + r.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' L ') + ' Z').join(' ');
        svg.append(svgNo('path', { d, fill: '#e6f4f1', stroke: '#0b6568', 'stroke-width': 2, 'fill-rule': 'evenodd' }));
      }
      svg.append(svgNo('text', { x: 680, y: 24, 'text-anchor': 'middle', fill: '#12343b', 'font-size': 16 }, 'N ↑'));
      for (const m of desenho.marcadores) {
        svg.append(svgNo('line', { x1: m.ponto[0], y1: m.ponto[1], x2: m.x, y2: m.y, stroke: '#647d80', 'stroke-width': 1 }));
        svg.append(svgNo('circle', { cx: m.ponto[0], cy: m.ponto[1], r: 2.5, fill: '#0b6568' }));
      }
      for (const lado of desenho.lados) {
        const grupo = svgNo('g', { transform: `translate(${lado.x} ${lado.y}) rotate(${lado.giro})`, class: 'cac-print-rua' });
        const largura = Math.max(...lado.texto.map(t => t.length)) * 8 + 12, altura = lado.texto.length * 16 + 6;
        grupo.append(svgNo('rect', { x: -largura / 2, y: -altura / 2, width: largura, height: altura, rx: 3, fill: '#fff', 'fill-opacity': .92 }));
        lado.texto.forEach((linha, i) => grupo.append(svgNo('text', { x: 0, y: (i - (lado.texto.length - 1) / 2) * 16 + 5, 'text-anchor': 'middle', fill: '#34575a', 'font-size': 15, 'font-weight': 600 }, linha)));
        svg.append(grupo);
      }
      desenho.marcadores.forEach(m => {
        svg.append(svgNo('circle', { cx: m.x, cy: m.y, r: 12, fill: '#fff', stroke: '#0b6568', 'stroke-width': 1.5, class: 'cac-print-numero' }));
        svg.append(svgNo('text', { x: m.x, y: m.y + 5, 'text-anchor': 'middle', fill: '#12343b', 'font-size': m.numero > 99 ? 12 : 15, 'font-weight': 700 }, m.numero));
      });
      return svg;
    }
    // Uma entrada por roteiro: o quarteirão inteiro ou, quando dividido em L, cada metade com o seu responsável.
    function roteiros(blocos, dia, responsavel) {
      return blocos.flatMap(bloco => {
        const planos = M.planosDoDia(bloco, dia);
        if (!planos.length) return [{ bloco, plano: null }];
        return planos.filter(p => responsavel === undefined || String(p.ri || null) === String(responsavel)).map(plano => ({ bloco, plano }));
      });
    }
    function folhas(entradas, dia) {
      return entradas.flatMap(({ bloco, plano }) => {
        const casas = plano && plano.pt ? M.casasDoL(bloco, casasDe(bloco), plano.pt) : casasDe(bloco), paginas = M.paginasDoRoteiro(casas);
        const responsavel = plano && plano.r ? plano.r : '________________________________';
        const parte = plano && plano.pt ? nomeDaParte(plano.pt) : '';
        let offset = 0;
        return paginas.map((lista, pagina) => {
          const inicio = offset;
          offset += lista.length;
          const linha = (c, i) => h('tr', {}, h('td', {}, c ? inicio + i + 1 : '+'),
            h('td', { class: 'cac-print-endereco' }, c ? [h('strong', {}, `${c.rua}, ${c.n}`), c.cp ? h('small', {}, c.cp) : null] : 'Imóvel acrescentado: __________________'),
            h('td', {}, ''), h('td', {}, ''), h('td', {}, '___ / ___ / ___'), h('td', {}, ''), h('td', {}, ''), h('td', {}, ''));
          return h('article', { class: 'cac-print-folha' },
            h('header', { class: 'cac-print-cabecalho' }, h('div', {}, h('small', {}, 'ORLÂNDIA · CONTROLE DE VETORES'), h('h1', {}, 'Roteiro casa a casa')), h('strong', {}, `Q ${bloco.n}`, h('small', {}, `SC ${bloco.s}${parte ? ' · ' + parte : ''}`))),
            h('div', { class: 'cac-print-meta' }, h('p', {}, h('strong', {}, 'Data: '), `${dataBr(dia)}/${dia.slice(0, 4)}`), h('p', {}, h('strong', {}, 'Trabalhador: '), responsavel),
              plano && plano.at ? h('p', {}, h('strong', {}, 'Atividade: '), nomeDaAtividade(plano.at)) : null,
              parte ? h('p', {}, h('strong', {}, 'Parte: '), `${parte} (os dois lados em torno do canto; o outro L é de outra pessoa)`) : null,
              h('p', {}, `${casas.length} imóveis previstos · Folha ${pagina + 1} de ${paginas.length}${bloco.d ? ' · ' + bloco.d : ''}`)),
            h('div', { class: 'cac-print-mapa' }, mapaDoBloco(bloco, lista, inicio), h('p', {}, 'Círculos = ordem na tabela desta folha. As linhas ligam cada número à posição do imóvel. Norte para cima.')),
            !casas.length ? h('p', { class: 'cac-print-atencao' }, 'Sem imóveis numerados na base deste quarteirão. Levante e anote os endereços em campo.') : null,
            h('table', { class: 'cac-print-tabela' }, h('thead', {}, h('tr', {}, ['#', 'Rua, número e complemento', 'Hora', 'Sit.', 'Recipientes E / A / L', 'Tub.', 'Controle', 'Observações'].map(t => h('th', { scope: 'col' }, t)))),
              h('tbody', {}, lista.map(linha), Array.from({ length: casas.length ? 2 : 8 }, (_, i) => linha(null, i)))),
            h('div', { class: 'cac-print-chaves' }, h('p', {}, 'Situação: T Trabalhado · F Fechado · D Desocupado · R Recusa.'),
              h('p', {}, 'Recipientes: E existentes · A com água · L com larva. Controle: M mecânico · A alternativo · F focal (N Natular · V Vectobac).'),
              h('p', {}, 'Anote o tipo (1–40), a quantidade e o controle de cada recipiente nas observações ou na ficha complementar.')),
            h('footer', { class: 'cac-print-rodape' }, h('p', {}, 'Conferência: T ____ F ____ D ____ R ____ · Assinatura: __________________'),
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
        const blocos = iniciais.slice()
          .sort((a, b) => String(a.s).localeCompare(String(b.s), 'pt-BR', { numeric: true }) || String(a.n).localeCompare(String(b.n), 'pt-BR', { numeric: true }));
        const entradas = roteiros(blocos, dia, escolher.value === 'todos' ? undefined : escolher.value);
        const conteudo = folhas(entradas, dia);
        paginas.replaceChildren(...conteudo);
        $('cac-impressao').replaceChildren(...conteudo.map(p => p.cloneNode(true)));
        $('cac-impressao').setAttribute('aria-hidden', 'false');
        imprimir.disabled = !entradas.length;
        const imoveis = entradas.reduce((n, e) => n + (e.plano && e.plano.pt ? M.casasDoL(e.bloco, casasDe(e.bloco), e.plano.pt) : casasDe(e.bloco)).length, 0);
        resumo.textContent = `${dataBr(dia)}/${dia.slice(0, 4)} · ${entradas.length} ${entradas.length === 1 ? 'roteiro' : 'roteiros'} · ${imoveis} imóveis · ${conteudo.length} folhas A4`;
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
        document.getElementById('cac-impressao').replaceChildren(...folhas(roteiros(S.blocos.filter(b => b.planos.some(p => p.d === dia)), dia), dia));
      }
    }
    return { abrir, preparar };
  };
})(typeof window !== 'undefined' ? window : globalThis);
