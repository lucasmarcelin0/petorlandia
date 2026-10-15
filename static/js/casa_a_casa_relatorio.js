/* Relatório do escritório: tudo o que foi feito, por dia e por quarteirão, pronto para conferir, imprimir e baixar. */
(function (root) {
  'use strict';
  root.CasaACasaRelatorio = function (ui) {
    const { S, cfg, h, dataBr, somarDias, pedir, avisar, desenharPainel, nomeDaParte, nomeDaAtividade, abrirBloco } = ui;
    const qtd = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
    const com = (url, inicio, fim) => url + (url.includes('?') ? '&' : '?') + 'inicio=' + inicio + '&fim=' + fim;
    const dataLonga = iso => new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' })
      .format(new Date(iso + 'T12:00:00Z'));

    async function carregar(inicio, fim) {
      S.relatorioInicio = inicio; S.relatorioFim = fim;
      if (!navigator.onLine) { S.relatorio = { erro: 'O relatório precisa de internet. Conecte e toque de novo.' }; desenharPainel(); return; }
      S.relatorio = { carregando: true };
      desenharPainel();
      try {
        const dados = await pedir(com(cfg.urls.relatorio, inicio, fim));
        if (S.relatorioInicio === inicio && S.relatorioFim === fim) S.relatorio = dados;
      } catch (erro) {
        S.relatorio = { erro: erro.message || 'Não deu para montar o relatório agora.' };
      }
      if (S.aba === 'relatorio') desenharPainel();
    }

    const responsaveis = q => q.planos.filter(p => p.responsavel)
      .map(p => p.responsavel + (p.parte ? ` (${nomeDaParte(p.parte)})` : '')).join(' + ');
    const atividades = q => q.atividades.map(nomeDaAtividade).filter(Boolean).join(' / ');
    const grupos = q => Object.entries(q.grupos).filter(([, n]) => n).map(([g, n]) => `${g} ${n}`).join(' · ');
    const focal = x => `${x.focal}${x.natular || x.vectobac ? ` (N ${x.natular} · V ${x.vectobac})` : ''}`;

    function numeros(t) {
      const kpi = (valor, rotulo, cor) => h('div', { class: 'cac-kpi' }, h('strong', { style: cor ? 'color:' + cor : null }, String(valor)), h('span', {}, rotulo));
      return h('div', { class: 'cac-kpis' },
        kpi(`${t.concluidos}/${t.quarteiroes}`, 'quarteirões concluídos', '#2f9e44'), kpi(t.imoveis, 'imóveis visitados'),
        kpi(t.trabalhados, 'trabalhados', '#2f9e44'), kpi(t.fechados, 'fechados', '#e8590c'), kpi(t.recusas, 'recusas', '#e03131'),
        kpi(t.desocupados, 'desocupados'), kpi(t.com_larva, 'com larva', '#9c36b5'), kpi(t.tubitos, 'tubitos'),
        kpi(`${t.rec_existentes}/${t.rec_agua}/${t.rec_larva}`, 'recipientes E/A/L'), kpi(t.mecanico, 'controle mecânico'),
        kpi(t.alternativo, 'controle alternativo'), kpi(t.focal, 'tratamento focal'), kpi(t.natular, 'focal com Natular'),
        kpi(t.vectobac, 'focal com Vectobac'), kpi(t.recuperados, 'pendências recuperadas'));
    }

    function tabela(dia) {
      return h('div', { class: 'cac-tabela-rolagem' }, h('table', { class: 'cac-relatorio' },
        h('caption', { class: 'cac-sr' }, `Quarteirões de ${dataBr(dia.data)}`),
        h('thead', {}, h('tr', {}, ['Quarteirão', 'Atividade', 'Responsáveis', 'Visitados', 'T', 'F', 'D', 'R', 'Larva', 'Tub.', 'Rec. E/A/L', 'Controle M/A/F', 'Recipientes por grupo', 'Concluído']
          .map(t => h('th', { scope: 'col' }, t)))),
        h('tbody', {}, dia.quarteiroes.map(q => h('tr', {},
          h('th', { scope: 'row' }, h('button', { type: 'button', class: 'cac-link-botao', onclick: () => abrirBloco(q.bloco) }, `Q ${q.quarteirao}`), h('small', {}, ` SC ${q.setor}`)),
          h('td', {}, atividades(q) || '—'), h('td', {}, responsaveis(q) || (q.agentes.join(', ') || '—')),
          h('td', {}, `${q.imoveis}/${q.previstos}`), h('td', {}, q.trabalhados + q.parciais), h('td', {}, q.fechados), h('td', {}, q.desocupados),
          h('td', {}, q.recusas), h('td', {}, q.com_larva), h('td', {}, q.tubitos), h('td', {}, `${q.rec_existentes}/${q.rec_agua}/${q.rec_larva}`),
          h('td', {}, `${q.mecanico}/${q.alternativo}/${focal(q)}`), h('td', {}, grupos(q) || '—'), h('td', {}, q.concluido ? '✓' : ''))))));
    }

    function folhaImpressa(dados) {
      return h('article', { class: 'cac-print-folha cac-print-relatorio' },
        h('header', { class: 'cac-print-cabecalho' }, h('div', {}, h('small', {}, 'ORLÂNDIA · CONTROLE DE VETORES'), h('h1', {}, 'Relatório casa a casa')),
          h('strong', {}, dados.inicio === dados.fim ? dataBr(dados.inicio) : `${dataBr(dados.inicio)} a ${dataBr(dados.fim)}`)),
        dados.dias.map(dia => h('section', {}, h('h2', {}, dataLonga(dia.data)), numeros(dia.totais), tabela(dia),
          dia.totais.agentes.length ? h('p', {}, h('strong', {}, 'Agentes: '), dia.totais.agentes.join(', ')) : null)),
        h('footer', { class: 'cac-print-rodape' }, h('small', {}, 'T trabalhado (inclui parcial) · F fechado · D desocupado · R recusa · E/A/L existentes, com água e com larva · M/A/F mecânico, alternativo e focal (N Natular, V Vectobac). Vale a última visita de cada imóvel no dia.')));
    }

    function imprimir() {
      if (!S.relatorio || !S.relatorio.dias) return;
      document.getElementById('cac-impressao').replaceChildren(folhaImpressa(S.relatorio));
      setTimeout(() => window.print(), 60);
    }

    function painel() {
      const hoje = S.hoje, ontem = somarDias(hoje, -1), semana = somarDias(hoje, -6);
      if (!S.relatorioInicio) {
        // Primeira abertura da aba: o dia de hoje, buscado fora do desenho do painel.
        S.relatorioInicio = S.relatorioFim = hoje; S.relatorio = { carregando: true };
        setTimeout(() => carregar(hoje, hoje), 0);
      }
      const inicio = S.relatorioInicio || hoje, fim = S.relatorioFim || hoje;
      const escolha = (rotulo, de, ate) => h('button', { type: 'button', 'aria-pressed': String(inicio === de && fim === ate), onclick: () => carregar(de, ate) }, rotulo);
      const campo = h('input', { type: 'date', max: hoje, value: inicio === fim ? inicio : '', 'aria-label': 'Escolher um dia' });
      campo.addEventListener('change', () => { if (campo.value && campo.value <= hoje) carregar(campo.value, campo.value); });
      const dados = S.relatorio || {};
      const topo = h('section', { class: 'cac-cartao' }, h('h2', {}, 'Relatório por dia e quarteirão'),
        h('div', { class: 'cac-escolhas' }, escolha('Hoje', hoje, hoje), escolha('Ontem', ontem, ontem), escolha('Últimos 7 dias', semana, hoje), campo),
        h('div', { class: 'cac-bloco-acoes' },
          h('button', { type: 'button', class: 'cac-botao', disabled: !dados.dias || !dados.dias.length, onclick: imprimir }, '🖨️ Imprimir relatório'),
          h('button', { type: 'button', class: 'cac-botao', onclick: () => { location.href = com(cfg.urls.relatorio_csv, inicio, fim); } }, '📄 Baixar planilha (CSV)'),
          h('button', { type: 'button', class: 'cac-botao', onclick: () => carregar(inicio, fim) }, '🔄 Atualizar')));
      if (dados.carregando) return [topo, h('section', { class: 'cac-cartao cac-vazio' }, h('p', {}, 'Montando o relatório…'))];
      if (dados.erro) return [topo, h('section', { class: 'cac-cartao cac-vazio' }, h('p', {}, dados.erro))];
      if (!dados.dias) return [topo];
      if (!dados.dias.length) return [topo, h('section', { class: 'cac-cartao cac-vazio' }, h('p', {}, 'Nenhum quarteirão planejado ou trabalhado neste período.'))];
      return [topo, ...dados.dias.map(dia => h('section', { class: 'cac-cartao' },
        h('h3', {}, `${dataLonga(dia.data)} · ${qtd(dia.totais.quarteiroes, 'quarteirão', 'quarteirões')}`),
        numeros(dia.totais), tabela(dia),
        dia.totais.agentes.length ? h('p', { class: 'cac-nota' }, 'Agentes: ' + dia.totais.agentes.join(', ')) : null))];
    }

    return { painel, carregar };
  };
})(window);
