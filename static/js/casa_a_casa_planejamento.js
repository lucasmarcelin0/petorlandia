/* Planejamento de campo: selecionar, conferir e só então salvar. */
(function (root) {
  'use strict';
  root.CasaACasaPlanejamento = function (ui) {
    const { S, cfg, h, casasDe, dataBr, somarDias, corDoAgente, desenhar, desenharPainel,
      selecionarBloco, aplicarSelecao, reagendarBloco, removerDoPlano, irParaBloco, imprimir,
      dividirBloco, juntarBloco, incluirTrabalhador, nomeDaParte, nomeDaAtividade } = ui;
    const M = root.CasaACasaModel;
    const nomeDia = dia => new Intl.DateTimeFormat('pt-BR', { weekday: 'short', timeZone: 'UTC' }).format(new Date(dia + 'T12:00:00Z'));
    const pessoas = () => (cfg.equipe || []).concat([{ id: null, nome: 'Sem responsável' }]);
    const escolherDia = dia => { if (!S.salvandoPlano) { S.diaPlano = dia; desenhar(); } };
    const total = blocos => blocos.reduce((n, b) => n + casasDe(b).length, 0);
    const qtd = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
    const ver = bloco => { S.blocoAtivo = bloco; S.aba = 'quarteirao'; desenhar(); irParaBloco(bloco); };
    const quemNoDia = (b, dia) => M.planosDoDia(b, dia).map(p => (p.r || 'Sem responsável') + (p.pt ? ' (' + p.pt + ')' : '')).join(' / ');

    // Formulário de divisão em L de um quarteirão da agenda: dois Ls opostos, uma pessoa em cada.
    function formularioDivisao(b, dia, plano) {
      const membros = cfg.equipe || [];
      const outro = (membros.find(p => p.id === S.responsavelPlano && p.id !== plano.ri) || membros.find(p => p.id !== plano.ri) || {}).id || null;
      const escolhaPessoa = (rotulo, valor) => h('select', { 'aria-label': rotulo }, h('option', { value: '' }, 'Sem responsável'),
        membros.map(p => h('option', { value: String(p.id), selected: p.id === valor }, p.nome)));
      const sentido = h('select', { 'aria-label': 'Como dividir' },
        h('option', { value: 'NE' }, 'L Nordeste + L Sudoeste'), h('option', { value: 'NO' }, 'L Noroeste + L Sudeste'));
      const primeira = escolhaPessoa('Responsável pelo primeiro L', plano.ri || null), segunda = escolhaPessoa('Responsável pelo segundo L', outro);
      const rotulos = [h('span', {}), h('span', {})];
      const contar = () => {
        const parte = sentido.value, oposta = M.PARTES[parte];
        rotulos[0].textContent = `${nomeDaParte(parte)} · ${M.casasDoL(b, casasDe(b), parte).length} imóveis`;
        rotulos[1].textContent = `${nomeDaParte(oposta)} · ${M.casasDoL(b, casasDe(b), oposta).length} imóveis`;
      };
      sentido.addEventListener('change', contar);
      contar();
      const numero = valor => (valor ? Number(valor) : null);
      return h('div', { class: 'cac-dividir' },
        h('p', { class: 'cac-nota' }, 'Cada pessoa faz um L: os dois lados do quarteirão em torno de um canto. A linha tracejada no mapa mostra a divisão.'),
        h('label', { class: 'cac-campo' }, 'Divisão', sentido),
        h('label', { class: 'cac-campo' }, rotulos[0], primeira),
        h('label', { class: 'cac-campo' }, rotulos[1], segunda),
        h('div', { class: 'cac-bloco-acoes' },
          h('button', { type: 'button', class: 'cac-botao', onclick: () => { S.dividindo = null; desenharPainel(); } }, 'Cancelar'),
          h('button', { type: 'button', class: 'cac-botao forte', disabled: S.salvandoPlano || !navigator.onLine, onclick: async () => {
            if (primeira.value && primeira.value === segunda.value) { window.alert('Escolha duas pessoas diferentes, uma para cada L.'); return; }
            const ok = await dividirBloco(b, dia, [{ parte: sentido.value, responsavel_id: numero(primeira.value) },
              { parte: M.PARTES[sentido.value], responsavel_id: numero(segunda.value) }]);
            if (ok) { S.dividindo = null; desenhar(); }
          } }, 'Dividir em dois Ls')));
    }

    function semana() {
      const dias = M.diasDeTrabalho(S.hoje);
      const agendas = dias.map(d => M.agendaDoDia(S.blocos, d));
      return h('details', { class: 'cac-semana', open: S.semanaAberta, ontoggle: evento => { S.semanaAberta = evento.target.open; } }, h('summary', {}, 'Carga da equipe · próximos 5 dias úteis'),
        h('div', { class: 'cac-tabela-rolagem' }, h('table', {},
          h('caption', { class: 'cac-sr' }, 'Quarteirões e imóveis previstos por trabalhador e dia'),
          h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Trabalhador'), dias.map(d => h('th', { scope: 'col' }, nomeDia(d), h('small', {}, dataBr(d)))))),
          h('tbody', {}, pessoas().map(p => h('tr', {}, h('th', { scope: 'row' }, p.nome), dias.map((d, i) => {
            const grupo = agendas[i].find(g => g.id === p.id);
            return h('td', {}, h('button', { type: 'button', disabled: S.salvandoPlano, 'aria-label': `${p.nome}, ${dataBr(d)}: ${grupo ? grupo.blocos.length : 0} quarteirões, ${grupo ? grupo.imoveis : 0} imóveis`,
              onclick: () => { S.responsavelPlano = p.id; escolherDia(d); } }, grupo ? grupo.blocos.length + ' q' : '—', h('small', {}, grupo ? grupo.imoveis + ' im.' : 'Livre')));
          })))))));
    }

    function painel() {
      const dia = S.diaPlano || S.hoje;
      const grupos = M.agendaDoDia(S.blocos, dia);
      const doDia = grupos.flatMap(g => g.blocos);
      const selecionados = S.blocos.filter(b => S.selecionados.has(b.id));
      const quem = pessoas().find(p => p.id === (S.responsavelPlano || null)) || pessoas().at(-1);
      const campoData = h('input', { type: 'date', min: S.hoje, max: somarDias(S.hoje, 60), value: dia, disabled: S.salvandoPlano, 'aria-label': 'Data de trabalho' });
      campoData.addEventListener('change', () => { if (campoData.value >= S.hoje && campoData.value <= somarDias(S.hoje, 60)) escolherDia(campoData.value); });
      const dias = Array.from(new Set([S.hoje, somarDias(S.hoje, 1), ...M.diasDeTrabalho(S.hoje)])).sort();
      const trabalhador = h('div', { class: 'cac-agentes', role: 'radiogroup', 'aria-label': 'Trabalhador responsável' }, pessoas().map(p => {
        const grupo = grupos.find(g => g.id === p.id);
        return h('button', { type: 'button', role: 'radio', 'aria-checked': String(quem.id === p.id), disabled: S.salvandoPlano, style: `--agente:${corDoAgente(p.id)}`, onclick: () => { S.responsavelPlano = p.id; desenharPainel(); } },
          h('i', { 'aria-hidden': 'true' }), h('span', {}, p.nome, h('small', {}, `${qtd(grupo ? grupo.blocos.length : 0, 'quarteirão', 'quarteirões')} · ${qtd(grupo ? grupo.imoveis : 0, 'imóvel', 'imóveis')}`)));
      }));
      // O que será feito nos quarteirões salvos: ADL, visita a imóveis ou controle de criadouro (rotina ou pendência).
      const atividade = h('div', { class: 'cac-atividades', role: 'radiogroup', 'aria-label': 'Atividade' },
        Object.entries(cfg.atividades || {}).map(([id, nome]) => h('button', { type: 'button', role: 'radio', 'aria-checked': String(S.atividadePlano === id), disabled: S.salvandoPlano,
          onclick: () => { S.atividadePlano = id; desenharPainel(); } }, nome)));
      const listar = h('div', { class: 'cac-catalogo', 'aria-label': 'Quarteirões disponíveis' });
      const busca = h('input', { type: 'search', value: S.buscaPlano, placeholder: 'Ex.: 216, Rua 12 ou Centro', 'aria-label': 'Buscar quarteirão, rua ou bairro' });
      const setor = h('select', { 'aria-label': 'Filtrar setor' }, h('option', { value: '' }, 'Todos os setores'),
        Array.from(new Set(S.blocos.map(b => b.s))).sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true })).map(s => h('option', { value: s, selected: S.setorPlano === s }, 'SC ' + s)));
      function resultados() {
        const termo = S.buscaPlano.trim().toLocaleLowerCase('pt-BR');
        const todos = S.blocos.filter(b => (!S.setorPlano || b.s === S.setorPlano) && (!termo || [b.n, b.s, b.d || '', ...b.casas.map(c => c.rua)].join(' ').toLocaleLowerCase('pt-BR').includes(termo)));
        listar.replaceChildren(h('p', { class: 'cac-nota' }, `${todos.length} encontrados${todos.length > 60 ? ' · mostrando os primeiros 60; refine a busca' : ''}`), ...todos.slice(0, 60).map(b => {
          const p = b.planos.find(p => p.d === dia);
          const outros = b.planos.filter(p => !p.c && p.d !== dia);
          return h('button', { type: 'button', class: 'cac-selecionar', disabled: S.salvandoPlano || Boolean(S.origemPlano), 'aria-pressed': String(S.selecionados.has(b.id)), onclick: () => selecionarBloco(b) },
            h('span', { class: 'cac-selecao-marca', 'aria-hidden': 'true' }, S.selecionados.has(b.id) ? '✓' : '+'),
            h('span', {}, h('strong', {}, `Q ${b.n} · SC ${b.s}`), h('small', {}, `${casasDe(b).length} imóveis · ${p ? (p.c ? 'Concluído' : quemNoDia(b, dia)) : 'Livre neste dia'}`),
              outros.length ? h('small', { class: 'cac-alerta-texto' }, 'Também previsto em ' + outros.map(p => dataBr(p.d)).join(', ')) : null));
        }));
      }
      busca.addEventListener('input', () => { S.buscaPlano = busca.value; resultados(); });
      setor.addEventListener('change', () => { S.setorPlano = setor.value; resultados(); });
      resultados();
      const trocas = selecionados.filter(b => b.planos.some(p => p.d === dia && !p.c && (p.ri || null) !== quem.id));
      const concluidos = selecionados.filter(b => b.planos.some(p => p.d === dia && p.c));
      const diasExtras = selecionados.filter(b => b.planos.some(p => p.d !== dia && !p.c));
      const cargaAtual = grupos.find(g => g.id === quem.id)?.imoveis || 0;
      const acrescidos = selecionados.filter(b => !b.planos.some(p => p.d === dia && (p.c || (p.ri || null) === quem.id)));
      const selecao = h('section', { class: 'cac-cartao cac-revisao', 'aria-label': 'Conferir seleção' },
        h('h3', {}, '4. Conferir e salvar'),
        h('p', {}, selecionados.length ? `${qtd(selecionados.length, 'quarteirão', 'quarteirões')} · ${qtd(total(selecionados), 'imóvel', 'imóveis')}` : 'Selecione no mapa ou na lista. Nenhuma alteração é salva ao selecionar.'),
        selecionados.length ? [
          h('p', { class: 'cac-destino' }, `${dataBr(dia)}/${dia.slice(0, 4)} · ${quem.nome}${S.origemPlano ? '' : ' · ' + nomeDaAtividade(S.atividadePlano)}`),
          h('p', {}, `Carga prevista: ${cargaAtual} atuais + ${total(acrescidos)} selecionados = ${cargaAtual + total(acrescidos)} imóveis.`),
          h('p', { class: 'cac-nota' }, selecionados.map(b => `Q ${b.n} / SC ${b.s}`).join(' · ')),
          S.origemPlano ? h('p', { class: 'cac-alerta-texto' }, `Reagendamento: sairá de ${dataBr(S.origemPlano)} ao salvar.`) : null,
          trocas.length ? h('p', { class: 'cac-alerta-texto' }, `Ao salvar, ${trocas.length} quarteirão(ões) passarão de outro responsável para ${quem.nome}.`) : null,
          concluidos.length ? h('p', { class: 'cac-alerta-texto' }, `${concluidos.length} concluído(s): serão preservados.`) : null,
          diasExtras.length && !S.origemPlano ? h('p', { class: 'cac-alerta-texto' }, 'Há quarteirões previstos em outros dias. Este salvamento acrescenta uma data; use Reagendar na agenda para mudar o dia.') : null,
          h('div', { class: 'cac-bloco-acoes' },
            h('button', { type: 'button', class: 'cac-botao', disabled: S.salvandoPlano, onclick: () => { S.selecionados.clear(); S.origemPlano = null; desenhar(); } }, 'Cancelar seleção'),
            h('button', { type: 'button', class: 'cac-botao forte', disabled: S.salvandoPlano || !navigator.onLine || Boolean(S.origemPlano && S.origemPlano === dia), onclick: aplicarSelecao }, S.salvandoPlano ? 'Salvando…' : S.origemPlano ? 'Salvar reagendamento' : 'Salvar planejamento')),
        ] : null, !navigator.onLine ? h('p', { class: 'cac-alerta-texto' }, 'Conecte à internet para salvar o planejamento.') : null);
      return [
        h('section', { class: 'cac-cartao' }, h('h2', {}, 'Organizar os próximos dias'), h('p', {}, 'Escolha o dia, o trabalhador e os quarteirões.'),
          h('h3', { class: 'cac-etapa' }, '1. Dia de trabalho'),
          h('div', { class: 'cac-dias' }, dias.map(d => {
            const grupos = M.agendaDoDia(S.blocos, d), n = grupos.reduce((n, g) => n + g.blocos.length, 0);
            return h('button', { type: 'button', 'aria-pressed': String(dia === d), disabled: S.salvandoPlano, onclick: () => escolherDia(d) },
              h('strong', {}, d === S.hoje ? 'Hoje' : d === somarDias(S.hoje, 1) ? 'Amanhã' : nomeDia(d)), h('span', {}, dataBr(d)), h('small', {}, qtd(n, 'quarteirão', 'quarteirões')));
          })), h('label', { class: 'cac-campo' }, 'Outra data (inclui fins de semana)', campoData), semana(),
          cfg.registra ? [h('h3', { class: 'cac-etapa' }, '2. Trabalhador responsável'), trabalhador,
            cfg.admin ? h('button', { type: 'button', class: 'cac-botao cac-mais', onclick: incluirTrabalhador, 'aria-label': 'Incluir novo trabalhador' }, '＋ Novo trabalhador') : null,
            h('h3', { class: 'cac-etapa' }, '3. Atividade'), atividade] : h('p', {}, 'Somente leitura: entre com uma conta da equipe para planejar.')),
        cfg.registra ? selecao : null,
        cfg.registra ? h('section', { class: 'cac-cartao' }, h('h3', {}, 'Selecionar quarteirões'),
          h('label', { class: 'cac-interruptor' }, (() => { const marca = h('input', { type: 'checkbox' }); marca.checked = S.planejando; marca.addEventListener('change', () => { S.planejando = marca.checked; desenharPainel(); }); return marca; })(), 'Selecionar ao clicar no mapa'),
          h('div', { class: 'cac-filtros' }, busca, setor), listar) : null,
        h('section', { class: 'cac-cartao' }, h('h3', {}, `Agenda de ${dataBr(dia)} · ${qtd(doDia.length, 'quarteirão', 'quarteirões')} · ${qtd(total(doDia), 'imóvel', 'imóveis')}`),
          h('div', { class: 'cac-bloco-acoes' }, h('button', { type: 'button', class: 'cac-botao forte', disabled: !doDia.length, onclick: () => imprimir() }, 'Prévia e impressão A4')),
          !doDia.length ? h('p', { class: 'cac-vazio' }, 'O dia está livre. Selecione quarteirões e salve o planejamento.') : grupos.map(g => h('div', { class: 'cac-grupo' },
            h('h4', {}, h('i', { class: 'cac-agente-cor', style: `background:${corDoAgente(g.id)}` }), `${g.nome} · ${g.imoveis} imóveis`),
            h('button', { type: 'button', class: 'cac-link-botao', onclick: () => imprimir({ responsavel: g.id }) }, 'Imprimir roteiro deste trabalhador'),
            g.blocos.map(b => {
              const planos = M.planosDoDia(b, dia);
              const p = planos.find(p => (p.ri || null) === g.id) || planos[0];
              const dividido = planos.some(x => x.pt);
              const imoveis = p.pt ? M.casasDoL(b, casasDe(b), p.pt).length : casasDe(b).length;
              const chave = b.id + '|' + dia;
              return h('div', { class: 'cac-agenda-item' },
                h('button', { type: 'button', class: 'cac-selecionar', onclick: () => ver(b) }, h('strong', {}, `Q ${b.n} · SC ${b.s}${p.pt ? ' · ' + nomeDaParte(p.pt) : ''}`),
                  h('small', {}, `${imoveis} imóveis${p.at ? ' · ' + nomeDaAtividade(p.at) : ''}${p.c ? ' · Concluído' : ''}`)),
                h('div', { class: 'cac-item-acoes' }, h('button', { type: 'button', onclick: () => imprimir({ bloco: b, responsavel: g.id }) }, 'Ficha A4'),
                  cfg.registra && !planos.some(x => x.c) ? [
                    dividido ? h('button', { type: 'button', disabled: S.salvandoPlano, onclick: () => juntarBloco(b, dia, p.ri || null) }, 'Juntar Ls')
                      : h('button', { type: 'button', disabled: S.salvandoPlano, 'aria-expanded': String(S.dividindo === chave), onclick: () => { S.dividindo = S.dividindo === chave ? null : chave; desenharPainel(); } }, 'Dividir em L'),
                    h('button', { type: 'button', disabled: S.salvandoPlano, onclick: () => reagendarBloco(b, dia) }, 'Reagendar'),
                    h('button', { type: 'button', disabled: S.salvandoPlano, onclick: () => removerDoPlano(b, dia) }, 'Retirar')] : null),
                S.dividindo === chave && !dividido ? formularioDivisao(b, dia, p) : null);
            })))),
      ];
    }
    return { painel };
  };
})(window);
