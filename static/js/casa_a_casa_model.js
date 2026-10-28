/* Casa a casa: regras puras (sem tela nem rede), usadas pelo app e pelos testes em Node. */
(function (root) {
  'use strict';

  // Situação do imóvel, com os nomes do boletim oficial "Visita a Imóvel".
  const SITUACOES = [
    { id: 'TRABALHADO', nome: 'Trabalhado', icone: '✅', cor: '#2f9e44', clara: '#d3f9d8' },
    { id: 'FECHADO', nome: 'Fechado', icone: '🚪', cor: '#e8590c', clara: '#ffe8cc' },
    { id: 'DESOCUPADO', nome: 'Desocupado', icone: '🏚️', cor: '#868e96', clara: '#e9ecef' },
    { id: 'TEMPORADA', nome: 'Temporada', icone: '🏖️', cor: '#1c7ed6', clara: '#d0ebff' },
    { id: 'PARCIAL', nome: 'Parcial', icone: '🌗', cor: '#5c940d', clara: '#e9fac8' },
    { id: 'RECUSA', nome: 'Recusa', icone: '✋', cor: '#e03131', clara: '#ffe3e3' },
  ];
  const POR_ID = Object.fromEntries(SITUACOES.map(s => [s.id, s]));
  const INSPECIONADO = new Set(['TRABALHADO', 'PARCIAL']);
  const PENDENCIA = new Set(['FECHADO', 'RECUSA', 'TEMPORADA']);
  const LARVA = { cor: '#9c36b5', clara: '#f3d9fa' };
  // Temporada segue valendo nos registros antigos e no boletim, mas não aparece como opção.
  const OCULTAS = new Set(['TEMPORADA']);
  const OPCOES = SITUACOES.filter(s => !OCULTAS.has(s.id));
  // Controle feito em cada recipiente; o focal leva o larvicida.
  const CONTROLES = [{ id: 'M', nome: 'Mecânico' }, { id: 'A', nome: 'Alternativo' }, { id: 'F', nome: 'Focal' }];
  const PRODUTOS = [{ id: 'NATULAR', nome: 'Natular' }, { id: 'VECTOBAC', nome: 'Vectobac' }];
  // Quarteirão dividido entre duas pessoas: cada uma faz um L (os dois lados em torno de um canto).
  const PARTES = { NE: 'SO', SO: 'NE', NO: 'SE', SE: 'NO' };
  const NOME_PARTE = { NE: 'L Nordeste', NO: 'L Noroeste', SE: 'L Sudeste', SO: 'L Sudoeste' };

  // Cores leves do quarteirão, na ordem em que aparecem na legenda.
  const BLOCOS = {
    planejado: { nome: 'No plano, a fazer', fundo: '#fff3bf', borda: '#f08c00' },
    andamento: { nome: 'Em andamento', fundo: '#d0ebff', borda: '#1c7ed6' },
    concluido: { nome: 'Concluído hoje', fundo: '#b2f2bb', borda: '#2f9e44' },
    agendado: { nome: 'Planejado para outro dia', fundo: '#ffe8cc', borda: '#fd7e14' },
    recente: { nome: 'Trabalhado nos últimos 7 dias', fundo: '#e5dbff', borda: '#7950f2' },
    anterior: { nome: 'Trabalhado há mais tempo', fundo: '#f1f3f5', borda: '#adb5bd' },
    livre: { nome: 'Sem trabalho recente', fundo: '#ffffff', borda: '#adb5bd' },
  };
  const RECENTE_DIAS = 7;

  const XP = { visita: 10, recuperada: 15, quarteirao: 50 };
  const NIVEIS = [
    [0, 'Aprendiz de campo'], [100, 'Sentinela do bairro'], [300, 'Guardião da quadra'],
    [700, 'Defensor de Orlândia'], [1500, 'Mestre da vigilância'], [3000, 'Lenda do casa a casa'],
  ];

  const dia = iso => String(iso || '').slice(0, 10);
  const instante = iso => { const t = Date.parse(iso || ''); return Number.isFinite(t) ? t : 0; };

  function diasDeTrabalho(inicio, quantidade = 5) {
    const dias = [], data = new Date(inicio + 'T12:00:00Z');
    while (dias.length < quantidade && Number.isFinite(data.getTime())) {
      if (![0, 6].includes(data.getUTCDay())) dias.push(data.toISOString().slice(0, 10));
      data.setUTCDate(data.getUTCDate() + 1);
    }
    return dias;
  }

  const planosDoDia = (bloco, dia) => (bloco.planos || []).filter(p => p.d === dia);
  const todasAsCasas = bloco => (bloco.extras && bloco.extras.length ? bloco.casas.concat(bloco.extras) : bloco.casas);

  // Agrupa por identidade, mesmo quando duas pessoas têm o mesmo nome. Quarteirão dividido em L
  // entra no grupo de cada pessoa com os imóveis do L dela (``partes`` diz qual).
  function agendaDoDia(blocos, dia) {
    const grupos = new Map();
    for (const bloco of blocos) {
      for (const plano of planosDoDia(bloco, dia)) {
        const chave = plano.ri || null;
        if (!grupos.has(chave)) grupos.set(chave, { id: chave, nome: plano.r || 'Sem responsável', blocos: [], imoveis: 0, partes: new Map() });
        const grupo = grupos.get(chave);
        if (!grupo.blocos.includes(bloco)) grupo.blocos.push(bloco);
        if (plano.pt) grupo.partes.set(bloco.id, plano.pt);
        grupo.imoveis += plano.pt ? casasDoL(bloco, todasAsCasas(bloco), plano.pt).length : todasAsCasas(bloco).length;
      }
    }
    return Array.from(grupos.values());
  }

  /* Geometria do L. O quarteirão é girado para ficar alinhado ao seu lado mais comprido; no retângulo que o
     envolve, o L de um canto são os dois lados que encostam nele. Os quatro cantos recebem o nome da direção
     (NE, NO, SO, SE) mais próxima no mapa. Uma casa está no L do canto (sx, sy) quando
     sx·x/largura + sy·y/altura > 0; o L oposto fica com o resto, então a divisão não deixa casa de fora. */
  function geometriaDoBloco(bloco) {
    if (bloco._geo) return bloco._geo;
    const poligono = (bloco.g || []).reduce((maior, p) => (p[0].length > (maior ? maior[0].length : 0) ? p : maior), null);
    const anel = poligono ? poligono[0] : [bloco.c];
    const k = Math.cos(bloco.c[1] * Math.PI / 180);
    const local = ([x, y]) => [(x - bloco.c[0]) * k, y - bloco.c[1]];
    const pontos = anel.map(local);
    let theta = 0, maior = -1;
    for (let i = 1; i < pontos.length; i += 1) {
      const dx = pontos[i][0] - pontos[i - 1][0], dy = pontos[i][1] - pontos[i - 1][1], tamanho = dx * dx + dy * dy;
      if (tamanho > maior) { maior = tamanho; theta = Math.atan2(dy, dx); }
    }
    const cos = Math.cos(theta), sen = Math.sin(theta);
    const girar = ([x, y]) => [x * cos + y * sen, -x * sen + y * cos];
    const voltar = ([x, y]) => [x * cos - y * sen, x * sen + y * cos];
    const girados = pontos.map(girar);
    const xs = girados.map(p => p[0]), ys = girados.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const meio = [(x0 + x1) / 2, (y0 + y1) / 2], largura = Math.max(x1 - x0, 1e-9), altura = Math.max(y1 - y0, 1e-9);
    // Cantos na ordem anti-horária, como as direções NE, NO, SO, SE.
    const sinais = [[1, 1], [-1, 1], [-1, -1], [1, -1]];
    const cantos = sinais.map(([sx, sy]) => {
      const [lx, ly] = voltar([meio[0] + sx * largura / 2, meio[1] + sy * altura / 2]);
      return { sx, sy, angulo: Math.atan2(ly, lx), ponto: [bloco.c[0] + lx / k, bloco.c[1] + ly] };
    });
    const alvos = ['NE', 'NO', 'SO', 'SE'], graus = [Math.PI / 4, 3 * Math.PI / 4, -3 * Math.PI / 4, -Math.PI / 4];
    const diferenca = (a, b) => { const d = Math.abs(a - b) % (2 * Math.PI); return d > Math.PI ? 2 * Math.PI - d : d; };
    let melhor = 0, custo = Infinity;
    for (let desloca = 0; desloca < 4; desloca += 1) {
      const total = cantos.reduce((soma, c, i) => soma + diferenca(c.angulo, graus[(i + desloca) % 4]), 0);
      if (total < custo) { custo = total; melhor = desloca; }
    }
    const porNome = {};
    cantos.forEach((c, i) => { porNome[alvos[(i + melhor) % 4]] = c; });
    const geo = { girar, local, meio, largura, altura, cantos: porNome };
    Object.defineProperty(bloco, '_geo', { value: geo, enumerable: false, configurable: true });
    return geo;
  }

  function noL(bloco, casa, parte) {
    const geo = geometriaDoBloco(bloco), canto = geo.cantos[parte];
    if (!canto) return true;
    const [x, y] = geo.girar(geo.local([casa.x, casa.y]));
    const valor = canto.sx * (x - geo.meio[0]) / geo.largura + canto.sy * (y - geo.meio[1]) / geo.altura;
    // NE e NO ficam com o lado positivo; SO e SE com o resto, incluindo o empate.
    return parte === 'NE' || parte === 'NO' ? valor > 0 : valor >= 0;
  }

  function casasDoL(bloco, casas, parte) {
    return parte ? casas.filter(casa => noL(bloco, casa, parte)) : casas;
  }

  // Linha que separa os dois Ls: liga os dois cantos que não são de nenhum deles.
  function linhaDaDivisao(bloco, parte) {
    const cantos = geometriaDoBloco(bloco).cantos, outros = parte === 'NE' || parte === 'SO' ? ['NO', 'SE'] : ['NE', 'SO'];
    return outros.map(nome => cantos[nome].ponto);
  }

  // Não agrega números iguais: frente, fundos e unidades continuam sendo imóveis distintos.
  function paginasDoRoteiro(casas, tamanho = 14) {
    // Endereços longos recebem menos linhas por folha, preservando o texto completo.
    const altura = Math.max(8, ...casas.map(c => Math.ceil([c.rua || '', c.n || '', c.cp || ''].join(' ').length / 37) * 3.4 + 2.8));
    tamanho = Math.max(1, Math.min(tamanho, Math.floor(128 / altura)));
    const paginas = [];
    for (let i = 0; i < casas.length; i += tamanho) paginas.push(casas.slice(i, i + tamanho));
    return paginas.length ? paginas : [[]];
  }

  function diasEntre(de, ate) {
    const a = Date.parse(dia(de) + 'T00:00:00Z'), b = Date.parse(dia(ate) + 'T00:00:00Z');
    return Number.isFinite(a) && Number.isFinite(b) ? Math.round((b - a) / 86400000) : null;
  }

  function uuid() {
    if (root.crypto && root.crypto.randomUUID) return root.crypto.randomUUID();
    return 'v' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12) + '-' + Math.random().toString(36).slice(2, 8);
  }

  // A visita que vale para um imóvel é a mais recente; a que ainda não foi enviada conta como a mais nova.
  function maisRecente(a, b) {
    if (!a) return b;
    if (!b) return a;
    if (a.pendente !== b.pendente) return a.pendente ? a : b;
    if (a.i && b.i) return b.i > a.i ? b : a;
    return instante(b.h) >= instante(a.h) ? b : a;
  }

  function juntarVisitas(doServidor, daFila) {
    const ultimas = new Map();
    for (const v of doServidor) ultimas.set(v.m, maisRecente(ultimas.get(v.m), v));
    for (const v of daFila) ultimas.set(v.m, maisRecente(ultimas.get(v.m), v));
    return ultimas;
  }

  /* Histórico de um imóvel: o que veio do servidor e o que ainda está no aparelho, sem repetir a mesma
     visita (uuid), do dia mais recente para o mais antigo; no mesmo dia, a que ainda não foi enviada e
     depois a que chegou por último. */
  function historicoDoImovel(doServidor, daFila, imovel) {
    const porVisita = new Map();
    for (const v of daFila || []) if (v && v.m === imovel) porVisita.set(v.u, v);
    for (const v of doServidor || []) if (v && v.m === imovel) porVisita.set(v.u || 'i' + v.i, v);
    return Array.from(porVisita.values()).sort((a, b) => String(b.d || '').localeCompare(String(a.d || ''))
      || (b.pendente ? 1 : 0) - (a.pendente ? 1 : 0) || (b.i || 0) - (a.i || 0) || instante(b.h) - instante(a.h));
  }

  // Passe: começa no dia do plano em aberto; sem plano, hoje. O progresso conta as casas visitadas desde então.
  function planoAberto(planos, hoje) {
    let aberto = null;
    for (const p of planos || []) if (!p.c && p.d <= hoje && (!aberto || p.d > aberto.d)) aberto = p;
    return aberto;
  }

  function progresso(casas, ultimas, inicio) {
    const r = { total: casas.length, feitas: 0, larvas: 0, pendencias: 0, porSituacao: {}, pct: 0 };
    for (const casa of casas) {
      const v = ultimas.get(casa.id);
      if (!v || v.d < inicio) continue;
      r.feitas += 1;
      r.porSituacao[v.s] = (r.porSituacao[v.s] || 0) + 1;
      if (v.l) r.larvas += 1;
      if (PENDENCIA.has(v.s)) r.pendencias += 1;
    }
    r.pct = r.total ? Math.min(100, Math.round(100 * r.feitas / r.total)) : 0;
    return r;
  }

  /* Estado do quarteirão para a cor: plano em aberto vem primeiro; depois concluído hoje, planejado
     para outro dia e, por fim, há quanto tempo foi trabalhado. */
  function estadoDoBloco(planos, casas, ultimas, hoje, janela) {
    const aberto = planoAberto(planos, hoje);
    let inicio = aberto ? aberto.d : hoje;
    let prog = progresso(casas, ultimas, inicio);
    let ultimaData = '';
    for (const casa of casas) { const v = ultimas.get(casa.id); if (v && v.d > ultimaData) ultimaData = v.d; }
    let concluido = null, futuro = null;
    for (const p of planos || []) {
      if (p.c && (!concluido || p.c > concluido.c)) concluido = p;
      if (!p.c && p.d > hoje && (!futuro || p.d < futuro.d)) futuro = p;
    }
    if (concluido && dia(concluido.c) > ultimaData) ultimaData = dia(concluido.c);
    const ha = ultimaData ? diasEntre(ultimaData, hoje) : null;
    let tipo = 'livre';
    if (aberto) tipo = prog.feitas ? 'andamento' : 'planejado';
    else if (concluido && dia(concluido.c) === hoje) tipo = 'concluido';
    else if (futuro) tipo = 'agendado';
    else if (ha !== null && ha <= RECENTE_DIAS) tipo = 'recente';
    else if (ha !== null && ha <= (janela || 60)) tipo = 'anterior';
    if (tipo === 'concluido') { inicio = concluido.d; prog = progresso(casas, ultimas, inicio); }
    return { tipo, plano: aberto || (tipo === 'concluido' ? concluido : futuro) || null, inicio, prog, ha, ultimaData };
  }

  // Cor do imóvel: o resultado da última visita; visita anterior ao passe aparece esmaecida.
  function corDaCasa(visita, inicio) {
    if (!visita) return { cor: '#868e96', fundo: '#ffffff', texto: '#495057', apagada: false, vazia: true };
    const base = visita.l ? LARVA : (POR_ID[visita.s] || POR_ID.TRABALHADO);
    const apagada = visita.d < inicio;
    return { cor: base.cor, fundo: apagada ? '#ffffff' : base.cor, texto: apagada ? base.cor : '#ffffff', apagada, vazia: false };
  }

  function proximaCasa(casas, ultimas, inicio, depoisDe) {
    const comeco = Math.max(0, casas.findIndex(c => c.id === depoisDe) + 1);
    for (let passo = 0; passo < casas.length; passo += 1) {
      const casa = casas[(comeco + passo) % casas.length];
      const v = ultimas.get(casa.id);
      if (casa.id !== depoisDe && (!v || v.d < inicio)) return casa;
    }
    return null;
  }

  const contagem = valor => Math.max(0, Math.min(999, parseInt(valor, 10) || 0));

  /* Recipientes anotados por tipo (1 a 40 da ficha do SISAWEB): um por tipo, em ordem, com
     existentes >= com água >= com larva. Tipo sem recipiente existente sai da lista. */
  /* Recipientes anotados linha a linha: tipo (1 a 40), contagens e, opcionalmente, o controle feito naquela
     linha (c: M, A ou F) e, no focal, o larvicida (p). Linhas iguais em tipo e controle somam. */
  function recipientesPorTipo(lista) {
    const porLinha = new Map();
    for (const linha of lista || []) {
      const tipo = parseInt(linha && linha.t, 10);
      if (!(tipo >= 1 && tipo <= 40)) continue;
      const c = CONTROLES.some(x => x.id === linha.c) ? linha.c : '';
      const p = c === 'F' && PRODUTOS.some(x => x.id === linha.p) ? linha.p : '';
      const l = contagem(linha.l), a = Math.max(contagem(linha.a), l), e = Math.max(contagem(linha.e), a);
      const chave = tipo + '|' + c + '|' + p;
      const soma = porLinha.get(chave) || { t: tipo, e: 0, a: 0, l: 0 };
      const nova = { t: tipo, e: Math.min(999, soma.e + e), a: Math.min(999, soma.a + a), l: Math.min(999, soma.l + l) };
      if (c) nova.c = c;
      if (p) nova.p = p;
      porLinha.set(chave, nova);
    }
    const ordem = x => [x.t, x.c || '', x.p || ''].join('|');
    return Array.from(porLinha.values()).filter(linha => linha.e > 0)
      .sort((x, y) => x.t - y.t || ordem(x).localeCompare(ordem(y)));
  }

  function somaDosTipos(lista) {
    const r = { e: 0, a: 0, l: 0 };
    for (const linha of recipientesPorTipo(lista)) { r.e += linha.e; r.a += linha.a; r.l += linha.l; }
    return { e: Math.min(999, r.e), a: Math.min(999, r.a), l: Math.min(999, r.l) };
  }

  // Telefone: só os dígitos, sem o 55 do país; vale número local (8 ou 9) ou com DDD (10 ou 11).
  function telefoneDigitos(valor) {
    const d = String(valor || '').replace(/\D/g, '');
    return (d.length === 12 || d.length === 13) && d.startsWith('55') ? d.slice(2) : d;
  }
  const telefoneValido = valor => { const d = telefoneDigitos(valor); return !d || (d.length >= 8 && d.length <= 11); };
  function telefoneBr(valor) {
    const d = telefoneDigitos(valor);
    if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
    if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
    if (d.length === 9) return `${d.slice(0, 5)}-${d.slice(5)}`;
    if (d.length === 8) return `${d.slice(0, 4)}-${d.slice(4)}`;
    return d;
  }

  /* Moradores do imóvel: os do servidor com as mudanças das visitas que ainda estão no aparelho, na ordem
     em que foram feitas (incluir ou corrigir pelo uuid, tirar pela lista de removidos). */
  function moradoresDoImovel(doServidor, envios, imovel) {
    const porId = new Map();
    for (const m of doServidor || []) if (m && m.u) porId.set(m.u, m);
    for (const envio of envios || []) {
      if (!envio || envio.imovel !== imovel) continue;
      for (const m of envio.moradores || []) porId.set(m.u, Object.assign({}, m, { pendente: true }));
      for (const u of envio.moradores_removidos || []) porId.delete(u);
    }
    return Array.from(porId.values());
  }

  // Monta a visita no formato que o servidor recebe. Sem inspeção, os campos de recipiente ficam zerados.
  // Com recipientes anotados por tipo, os totais do boletim são a soma dos tipos.
  function novaVisita(d) {
    const inspecionado = INSPECIONADO.has(d.situacao);
    const n = contagem;
    const tipos = inspecionado ? recipientesPorTipo(d.recipientes) : [];
    const soma = tipos.length ? somaDosTipos(tipos) : null;
    const comLarva = !inspecionado ? 0 : (soma ? soma.l : n(d.recipientes_larva));
    const comAgua = !inspecionado ? 0 : (soma ? soma.a : Math.max(n(d.recipientes_agua), comLarva));
    const agora = d.agora || new Date();
    // O controle anotado em cada recipiente vale também para o imóvel.
    const controles = new Set(tipos.map(linha => linha.c));
    const focal = inspecionado && (Boolean(d.tratamento_focal) || controles.has('F'));
    const produtos = new Set(focal ? [].concat(d.focal_produto || []).filter(p => PRODUTOS.some(x => x.id === p)) : []);
    for (const linha of tipos) if (linha.p) produtos.add(linha.p);
    return {
      uuid: d.uuid || uuid(), bloco: d.bloco, imovel: d.imovel, situacao: d.situacao, atividade: d.atividade || '',
      data: d.data, horario: agora.toISOString(),
      logradouro: d.logradouro || '', numero: d.numero || '', complemento: d.complemento || '',
      lat: d.lat ?? null, lng: d.lng ?? null,
      recipientes_existentes: !inspecionado ? 0 : (soma ? soma.e : Math.max(n(d.recipientes_existentes), comAgua)),
      recipientes_agua: comAgua, recipientes_larva: comLarva, recipientes: tipos,
      larvas: inspecionado && (Boolean(d.larvas) || comLarva > 0),
      tubitos: inspecionado ? n(d.tubitos) : 0,
      controle_mecanico: inspecionado && (Boolean(d.controle_mecanico) || controles.has('M')),
      controle_alternativo: inspecionado && (Boolean(d.controle_alternativo) || controles.has('A')),
      tratamento_focal: focal, focal_produto: Array.from(produtos).sort(),
      observacao: String(d.observacao || '').trim().slice(0, 1000),
      // Moradores valem pelo imóvel: vão junto com a visita só quando mudaram nesta ficha.
      ...((d.moradores || []).length ? { moradores: d.moradores.map(m => ({ u: m.u, nome: String(m.nome || '').trim().slice(0, 120), telefone: telefoneDigitos(m.telefone) })) } : {}),
      ...((d.moradores_removidos || []).length ? { moradores_removidos: d.moradores_removidos.slice() } : {}),
    };
  }

  // A visita da fila no formato curto do servidor, para colorir o mapa antes de ser enviada.
  function comoRegistro(envio, agente) {
    return {
      i: 0, u: envio.uuid, b: envio.bloco, m: envio.imovel, s: envio.situacao, l: envio.larvas ? 1 : 0,
      d: envio.data, h: envio.horario, ai: agente ? agente.id : null, a: agente ? agente.nome : '',
      re: envio.recipientes_existentes, ra: envio.recipientes_agua, rl: envio.recipientes_larva, t: envio.tubitos,
      cm: envio.controle_mecanico ? 1 : 0, ca: envio.controle_alternativo ? 1 : 0, tf: envio.tratamento_focal ? 1 : 0,
      rc: 0, o: envio.observacao, lg: envio.logradouro, n: envio.numero, cp: envio.complemento,
      la: envio.lat, lo: envio.lng, rt: envio.recipientes || [], fp: (envio.focal_produto || []).join(','),
      at: envio.atividade || '', pendente: true,
    };
  }

  function pontos(agente) {
    const a = agente || {};
    return (a.visitas || 0) * XP.visita + (a.recuperadas || 0) * XP.recuperada + (a.quarteiroes || 0) * XP.quarteirao;
  }

  function nivel(xp) {
    let indice = 0;
    NIVEIS.forEach(([minimo], posicao) => { if (xp >= minimo) indice = posicao; });
    const [piso, titulo] = NIVEIS[indice];
    const teto = NIVEIS[indice + 1] ? NIVEIS[indice + 1][0] : null;
    return { numero: indice + 1, titulo, xp, piso, teto, pct: teto ? Math.round(100 * (xp - piso) / (teto - piso)) : 100 };
  }

  function medalhas(agente) {
    const a = agente || {};
    const todas = [
      ['🌱', 'Primeiro passo', 'Primeiro imóvel registrado', (a.visitas || 0) >= 1],
      ['⚡', 'Ritmo forte', '25 imóveis num dia', (a.hoje || 0) >= 25],
      ['🚀', 'Dia cheio', '50 imóveis num dia', (a.hoje || 0) >= 50],
      ['🔑', 'Porta aberta', 'Recuperou 5 imóveis que estavam fechados ou recusados', (a.recuperadas || 0) >= 5],
      ['🏁', 'Quarteirão fechado', 'Concluiu o primeiro quarteirão', (a.quarteiroes || 0) >= 1],
      ['🗺️', 'Mapa na mão', 'Concluiu 10 quarteirões', (a.quarteiroes || 0) >= 10],
      ['🛡️', 'Escudo de Orlândia', '500 imóveis registrados', (a.visitas || 0) >= 500],
    ];
    return todas.map(([icone, nome, como, ganha]) => ({ icone, nome, como, ganha }));
  }

  // O que o agente ainda não enviou entra na conta dele, para o placar não andar para trás sem internet.
  function comFila(agente, fila, hoje, concluidosLocais) {
    const a = Object.assign({ visitas: 0, hoje: 0, recuperadas: 0, quarteiroes: 0, quarteiroes_hoje: 0 }, agente || {});
    a.visitas += fila.length;
    a.hoje += fila.filter(v => v.data === hoje).length;
    a.quarteiroes += concluidosLocais || 0;
    a.quarteiroes_hoje += concluidosLocais || 0;
    return a;
  }

  function resumoDoDia(visitas, hoje) {
    const r = { total: 0, larvas: 0, pendencias: 0, porSituacao: {} };
    for (const v of visitas) {
      if (v.d !== hoje) continue;
      r.total += 1;
      r.porSituacao[v.s] = (r.porSituacao[v.s] || 0) + 1;
      if (v.l) r.larvas += 1;
      if (PENDENCIA.has(v.s)) r.pendencias += 1;
    }
    return r;
  }

  const api = {
    SITUACOES, OPCOES, OCULTAS, CONTROLES, PRODUTOS, PARTES, NOME_PARTE, POR_ID, INSPECIONADO, PENDENCIA, LARVA, BLOCOS, XP, NIVEIS, RECENTE_DIAS,
    dia, diasEntre, diasDeTrabalho, planosDoDia, agendaDoDia, geometriaDoBloco, noL, casasDoL, linhaDaDivisao, paginasDoRoteiro, uuid, maisRecente, juntarVisitas, historicoDoImovel, planoAberto, progresso, estadoDoBloco, corDaCasa,
    proximaCasa, recipientesPorTipo, somaDosTipos, telefoneDigitos, telefoneValido, telefoneBr, moradoresDoImovel, novaVisita, comoRegistro, pontos, nivel, medalhas, comFila, resumoDoDia,
  };
  root.CasaACasaModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
