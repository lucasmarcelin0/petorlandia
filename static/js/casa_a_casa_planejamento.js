/* Planejamento de campo: selecionar, conferir e só então salvar. */
(function (root) {
  'use strict';
  root.CasaACasaPlanejamento = function (ui) {
    const { S, cfg, h, casasDe, dataBr, somarDias, corDoAgente, desenhar, desenharPainel,
      selecionarBloco, aplicarSelecao, reagendarBloco, removerDoPlano, irParaBloco, imprimir,
      dividirBloco, juntarBloco, incluirTrabalhador, nomeDaParte, nomeDaAtividade, fotografiaPlano } = ui;
    const M = root.CasaACasaModel;
    const nomeDia = dia => new Intl.DateTimeFormat('pt-BR', { weekday: 'short', timeZone: 'UTC' }).format(new Date(dia + 'T12:00:00Z'));
    const pessoas = () => (cfg.equipe || []).concat([{ id: null, nome: 'Sem responsável' }]);
    const escolherDia = dia => { if (!S.salvandoPlano) { S.diaPlano = dia; desenhar(); } };
    const total = blocos => blocos.reduce((n, b) => n + casasDe(b).length, 0);
    const qtd = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
    const ver = bloco => { S.blocoAtivo = bloco; S.aba = 'quarteirao'; desenhar(); irParaBloco(bloco); };
    const quemNoDia = (b, dia) => M.planosDoDia(b, dia).map(p => (p.r || 'Sem responsável') + (p.pt ? ' (' + p.pt + ')' : '')).join(' / ');

    // Uma única janela de conferência, independente das atualizações ao vivo do painel.
    function abrirDivisao(b, dia, plano, origem) {
      if (S.salvandoPlano || document.getElementById('cac-divisao-dialogo')) return;
      const membros = cfg.equipe || [];
      const planos = M.planosDoDia(b, dia);
      const inicial = planos.some(p => p.pt === 'NO') ? 'NO' : 'NE';
      const atualA = planos.find(p => p.pt === inicial) || plano;
      const atualB = planos.find(p => p.pt === M.PARTES[inicial]);
      const outro = (membros.find(p => p.id === S.responsavelPlano && p.id !== atualA.ri) || membros.find(p => p.id !== atualA.ri) || {}).id || null;
      const escolhaPessoa = (rotulo, valor) => h('select', { 'aria-label': rotulo }, h('option', { value: '' }, 'Sem responsável'),
        membros.map(p => h('option', { value: String(p.id), selected: p.id === valor }, p.nome)));
      const esperado = fotografiaPlano([b], dia);
      const atividade = plano.at || S.atividadePlano;
      let sentido = inicial, enviando = false;
      const primeira = escolhaPessoa('Trabalhador da parte A', atualA.ri || null), segunda = escolhaPessoa('Trabalhador da parte B', atualB ? atualB.ri : outro);
      const rotulos = [h('strong', {}), h('strong', {})], listas = [h('div', {}), h('div', {})];
      const mapa = h('div', { class: 'cac-divisao-mapa' });
      const resumo = h('p', { class: 'cac-divisao-resumo', 'aria-live': 'polite' });
      const erro = h('p', { class: 'cac-alerta-texto', role: 'alert' });
      const numero = valor => (valor ? Number(valor) : null);
      const fechar = () => { if (!enviando) dialogo.close(); };
      const salvar = h('button', { type: 'button', class: 'cac-botao forte', onclick: async () => {
        if (enviando || salvar.disabled) return;
        enviando = true; atualizar();
        const ok = await dividirBloco(b, dia, [{ parte: sentido, responsavel_id: numero(primeira.value) },
          { parte: M.PARTES[sentido], responsavel_id: numero(segunda.value) }], esperado, atividade);
        enviando = false;
        if (ok) { S.selecionados.delete(b.id); dialogo.close(); desenhar(); }
        else { atualizar(); erro.textContent = 'A divisão não foi salva. Confira a conexão. Se a agenda mudou, cancele e abra a divisão novamente.'; }
      } }, 'Salvar divisão');
      const cancelar = h('button', { type: 'button', class: 'cac-botao', onclick: fechar }, 'Cancelar');
      const fecharTopo = h('button', { type: 'button', class: 'cac-icone', 'aria-label': 'Fechar divisão', onclick: fechar }, '×');
      const opcoes = ['NE', 'NO'].map(parte => h('button', { type: 'button', class: 'cac-divisao-opcao', 'aria-pressed': String(sentido === parte),
        onclick: () => { sentido = parte; atualizar(); } },
      h('span', { class: 'cac-divisao-mini ' + parte, 'aria-hidden': 'true' }, h('b', {}, 'A'), h('b', {}, 'B')),
      h('span', {}, parte === 'NE' ? 'Nordeste + Sudoeste' : 'Noroeste + Sudeste', h('small', {}, parte === 'NE' ? 'Cantos superior direito e inferior esquerdo' : 'Cantos superior esquerdo e inferior direito'))));
      const corpo = h('div', { class: 'cac-divisao-corpo' },
        h('section', {}, h('h3', {}, '1. Escolha os cantos'), h('p', { class: 'cac-nota' }, 'Cada parte é um L: dois lados em torno de um canto.'),
          h('div', { class: 'cac-divisao-opcoes', role: 'group', 'aria-label': 'Como dividir o quarteirão' }, opcoes), mapa,
          h('p', { class: 'cac-nota' }, 'Prévia dos imóveis cadastrados. A linha tracejada separa as partes A e B.')),
        h('section', {}, h('h3', {}, '2. Defina quem faz cada parte'),
          [primeira, segunda].map((select, i) => h('div', { class: 'cac-divisao-parte ' + (i ? 'parte-b' : 'parte-a') },
            h('label', { class: 'cac-campo' }, h('span', {}, h('b', { class: 'cac-divisao-letra' }, i ? 'B' : 'A'), rotulos[i]), select),
            h('details', {}, h('summary', {}, 'Conferir endereços desta parte'), listas[i]))),
          h('button', { type: 'button', class: 'cac-botao cac-divisao-trocar', onclick: () => {
            const valor = primeira.value; primeira.value = segunda.value; segunda.value = valor; atualizar();
          } }, '⇄ Trocar trabalhadores'),
          h('div', { class: 'cac-divisao-conferencia' }, h('h3', {}, '3. Confira e salve'), resumo, erro)));
      const dialogo = h('dialog', { id: 'cac-divisao-dialogo', class: 'cac-divisao-dialogo', 'aria-labelledby': 'cac-divisao-titulo' },
        h('header', { class: 'cac-divisao-topo' }, h('div', {}, h('p', { class: 'cac-nota' }, `QUARTEIRÃO ${b.n} · SC ${b.s} · ${dataBr(dia)}/${dia.slice(0, 4)}`),
          h('h2', { id: 'cac-divisao-titulo' }, 'Dividir entre trabalhadores'),
          h('p', {}, `${casasDe(b).length} imóveis · ${nomeDaAtividade(atividade) || 'Atividade do planejamento'}`)), fecharTopo), corpo,
        h('footer', { class: 'cac-divisao-rodape' }, h('span', { class: 'cac-nota' }, 'A agenda só muda ao salvar a divisão.'), cancelar, salvar));
      function atualizar() {
        const partes = [sentido, M.PARTES[sentido]], seletores = [primeira, segunda];
        const casas = partes.map(parte => M.casasDoL(b, casasDe(b), parte));
        const nomes = seletores.map(s => s.options[s.selectedIndex].textContent);
        opcoes.forEach((botao, i) => { botao.setAttribute('aria-pressed', String(sentido === ['NE', 'NO'][i])); botao.disabled = enviando; });
        seletores.forEach((select, i) => {
          select.disabled = enviando;
          rotulos[i].textContent = `${nomeDaParte(partes[i])} · ${qtd(casas[i].length, 'imóvel', 'imóveis')}`;
          const ruas = new Map();
          casas[i].forEach(c => { if (!ruas.has(c.rua)) ruas.set(c.rua, []); ruas.get(c.rua).push([c.n, c.cp].filter(Boolean).join(' ')); });
          listas[i].replaceChildren(...Array.from(ruas, ([rua, numeros]) => h('p', {}, h('strong', {}, rua + ': '), numeros.join(', '))));
          if (!casas[i].length) listas[i].append(h('p', {}, 'Nenhum imóvel cadastrado nesta parte.'));
        });
        mapa.replaceChildren(previaDivisao(b, partes, casas));
        resumo.textContent = `A: ${nomes[0]} · ${casas[0].length} imóveis. B: ${nomes[1]} · ${casas[1].length} imóveis. Total: ${casas[0].length + casas[1].length}.`;
        const iguais = primeira.value && primeira.value === segunda.value;
        erro.textContent = iguais ? 'Escolha trabalhadores diferentes para as partes A e B.' : !navigator.onLine ? 'Conecte à internet para salvar a divisão.'
          : !primeira.value || !segunda.value ? 'Há uma parte sem responsável. Ela ficará pendente de atribuição na agenda.' : '';
        salvar.disabled = enviando || S.salvandoPlano || !navigator.onLine || Boolean(iguais);
        salvar.textContent = enviando ? 'Salvando…' : 'Salvar divisão';
        cancelar.disabled = fecharTopo.disabled = enviando;
        corpo.querySelector('.cac-divisao-trocar').disabled = enviando;
      }
      primeira.addEventListener('change', atualizar); segunda.addEventListener('change', atualizar);
      dialogo.addEventListener('cancel', evento => { if (enviando) evento.preventDefault(); });
      dialogo.addEventListener('close', () => {
        window.removeEventListener('online', atualizar); window.removeEventListener('offline', atualizar);
        dialogo.remove(); if (origem && origem.isConnected) origem.focus();
      });
      window.addEventListener('online', atualizar); window.addEventListener('offline', atualizar);
      atualizar(); document.body.append(dialogo); dialogo.showModal();
    }

    // Usa a mesma geometria e a mesma lista de imóveis da divisão salva e dos roteiros A4.
    function previaDivisao(b, partes, casas) {
      const svg = (tag, attrs, texto) => {
        const no = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attrs).forEach(([k, v]) => no.setAttribute(k, v));
        if (texto) no.textContent = texto;
        return no;
      };
      const geo = M.geometriaDoBloco(b), cantos = Object.values(geo.cantos).map(c => c.ponto);
      const pontos = cantos.concat(...casas.map(lista => lista.map(c => [c.x, c.y])));
      const k = Math.cos(b.c[1] * Math.PI / 180), xs = pontos.map(p => p[0] * k), ys = pontos.map(p => p[1]);
      const x0 = Math.min(...xs), y0 = Math.min(...ys), largura = Math.max(...xs) - x0, altura = Math.max(...ys) - y0;
      const escala = Math.min(280 / Math.max(largura, 1e-9), 210 / Math.max(altura, 1e-9));
      const projetar = p => [180 + (p[0] * k - x0 - largura / 2) * escala, 145 - (p[1] - y0 - altura / 2) * escala];
      const par = p => projetar(p).join(',');
      const raiz = svg('svg', { viewBox: '0 0 360 290', role: 'img', 'aria-label': `Prévia do quarteirão ${b.n}: parte A ${nomeDaParte(partes[0])}, parte B ${nomeDaParte(partes[1])}` });
      const linha = M.linhaDaDivisao(b, partes[0]);
      const forma = (b.g || []).map(pol => pol.map(anel => 'M' + anel.map(par).join('L') + 'Z').join('')).join('');
      const clip = svg('clipPath', { id: 'cac-divisao-recorte' });
      clip.append(svg('path', { d: forma, 'clip-rule': 'evenodd' }));
      const defs = svg('defs', {}); defs.append(clip); raiz.append(defs);
      partes.forEach((parte, i) => {
        const cor = i ? '#a34b0a' : '#075f93', fundo = i ? '#fff0d6' : '#dceffc';
        raiz.append(svg('polygon', { points: [geo.cantos[parte].ponto, ...linha].map(par).join(' '), fill: fundo, 'clip-path': 'url(#cac-divisao-recorte)' }));
        casas[i].forEach(c => { const [cx, cy] = projetar([c.x, c.y]); raiz.append(svg('circle', { cx, cy, r: 3.5, fill: cor, stroke: '#fff', 'stroke-width': 1 })); });
        const [x, y] = projetar(geo.cantos[parte].ponto);
        raiz.append(svg('circle', { cx: x, cy: y, r: 13, fill: cor }));
        raiz.append(svg('text', { x, y: y + 5, 'text-anchor': 'middle', fill: '#fff', 'font-size': 14, 'font-weight': 700 }, i ? 'B' : 'A'));
      });
      raiz.append(svg('path', { d: forma, fill: 'none', stroke: '#496469', 'stroke-width': 1.5 }));
      const [a, z] = linha.map(projetar);
      raiz.append(svg('line', { x1: a[0], y1: a[1], x2: z[0], y2: z[1], stroke: '#12343b', 'stroke-width': 2, 'stroke-dasharray': '6 5' }));
      raiz.append(svg('text', { x: 335, y: 23, 'text-anchor': 'middle', fill: '#496469', 'font-size': 12 }, '↑ N'));
      return raiz;
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
      const doDia = Array.from(new Set(grupos.flatMap(g => g.blocos)));
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
          selecionados.length === 1 && !concluidos.length && !S.origemPlano ? h('div', { class: 'cac-divisao-atalho' },
            h('strong', {}, 'Mais de um trabalhador neste quarteirão?'),
            h('p', { class: 'cac-nota' }, 'Divida os imóveis em duas partes e escolha quem faz cada uma.'),
            h('button', { type: 'button', class: 'cac-botao', disabled: S.salvandoPlano, onclick: evento => {
              const b = selecionados[0]; abrirDivisao(b, dia, M.planosDoDia(b, dia)[0] || { ri: quem.id, at: S.atividadePlano }, evento.currentTarget);
            } }, 'Dividir entre trabalhadores')) : null,
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
            const grupos = M.agendaDoDia(S.blocos, d), n = new Set(grupos.flatMap(g => g.blocos)).size;
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
              return h('div', { class: 'cac-agenda-item' },
                h('button', { type: 'button', class: 'cac-selecionar', onclick: () => ver(b) }, h('strong', {}, `Q ${b.n} · SC ${b.s}${p.pt ? ' · ' + nomeDaParte(p.pt) : ''}`),
                  h('small', {}, `${imoveis} imóveis${p.at ? ' · ' + nomeDaAtividade(p.at) : ''}${p.c ? ' · Concluído' : ''}`)),
                h('div', { class: 'cac-item-acoes' }, h('button', { type: 'button', onclick: () => imprimir({ bloco: b, responsavel: g.id }) }, 'Ficha A4'),
                  cfg.registra && !planos.some(x => x.c) ? [
                    h('button', { type: 'button', class: 'cac-divisao-abrir', disabled: S.salvandoPlano, 'aria-haspopup': 'dialog', onclick: evento => abrirDivisao(b, dia, p, evento.currentTarget) }, dividido ? 'Ajustar divisão' : 'Dividir entre trabalhadores'),
                    dividido ? h('button', { type: 'button', disabled: S.salvandoPlano, onclick: () => {
                      if (window.confirm(`Reunir as duas partes de Q ${b.n} em ${dataBr(dia)}? Todos os imóveis ficarão com ${g.nome}.`)) juntarBloco(b, dia, p.ri || null);
                    } }, 'Reunir quarteirão') : null,
                    h('button', { type: 'button', disabled: S.salvandoPlano, onclick: () => reagendarBloco(b, dia) }, 'Reagendar'),
                    h('button', { type: 'button', disabled: S.salvandoPlano, onclick: () => removerDoPlano(b, dia) }, 'Retirar')] : null),
                dividido ? h('p', { class: 'cac-nota' }, 'Dividido entre ' + planos.map(x => `${x.r || 'Sem responsável'} (${nomeDaParte(x.pt)})`).join(' e ')) : null);
            })))),
      ];
    }
    return { painel };
  };
})(window);
