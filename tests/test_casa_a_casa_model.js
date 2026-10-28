'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

const M = require(path.resolve(__dirname, '..', 'static', 'js', 'casa_a_casa_model.js'));

const HOJE = '2026-10-13';
const casas = ['a', 'b', 'c', 'd'].map(id => ({ id }));
const visita = (m, s, d, extra) => Object.assign({ i: 1, m, s, d, l: 0, h: d + 'T10:00:00-03:00' }, extra);
const mapa = (...visitas) => M.juntarVisitas(visitas, []);

// --- a visita que vale para o imóvel
{
  const antiga = visita('a', 'FECHADO', '2026-10-10', { i: 5 });
  const nova = visita('a', 'TRABALHADO', HOJE, { i: 9 });
  assert.equal(M.maisRecente(antiga, nova), nova);
  assert.equal(M.maisRecente(nova, antiga), nova);
  // O que ainda não saiu do aparelho vale mais que o que o servidor tem.
  const pendente = Object.assign(visita('a', 'RECUSA', HOJE), { i: 0, pendente: true });
  assert.equal(M.maisRecente(nova, pendente), pendente);
  assert.equal(M.juntarVisitas([antiga, nova], [pendente]).get('a'), pendente);
}

// --- progresso do passe e cor do quarteirão
{
  const ultimas = mapa(visita('a', 'TRABALHADO', HOJE), visita('b', 'FECHADO', HOJE, { i: 2 }), visita('c', 'TRABALHADO', '2026-10-01', { i: 3, l: 1 }));
  const prog = M.progresso(casas, ultimas, HOJE);
  assert.deepEqual([prog.total, prog.feitas, prog.pct, prog.pendencias, prog.larvas], [4, 2, 50, 1, 0]);
  assert.deepEqual(M.progresso(casas, ultimas, '2026-10-01').feitas, 3);

  const estado = planos => M.estadoDoBloco(planos, casas, ultimas, HOJE, 60).tipo;
  assert.equal(estado([{ d: HOJE, c: null }]), 'andamento');
  assert.equal(M.estadoDoBloco([{ d: HOJE, c: null }], casas, mapa(), HOJE, 60).tipo, 'planejado');
  // Plano de dias atrás, ainda em aberto, continua valendo e o progresso conta desde o dia dele.
  const emAberto = M.estadoDoBloco([{ d: '2026-10-01', c: null }], casas, ultimas, HOJE, 60);
  assert.deepEqual([emAberto.tipo, emAberto.inicio, emAberto.prog.feitas], ['andamento', '2026-10-01', 3]);
  assert.equal(estado([{ d: HOJE, c: HOJE + 'T15:00:00-03:00' }]), 'concluido');
  assert.equal(M.estadoDoBloco([{ d: '2026-10-20', c: null }], casas, mapa(), HOJE, 60).tipo, 'agendado');
  assert.equal(M.estadoDoBloco([], casas, mapa(visita('a', 'TRABALHADO', '2026-10-09')), HOJE, 60).tipo, 'recente');
  assert.equal(M.estadoDoBloco([], casas, mapa(visita('a', 'TRABALHADO', '2026-09-01')), HOJE, 60).tipo, 'anterior');
  assert.equal(M.estadoDoBloco([], casas, mapa(visita('a', 'TRABALHADO', '2026-06-01')), HOJE, 60).tipo, 'livre');
  assert.equal(M.estadoDoBloco([], casas, mapa(), HOJE, 60).tipo, 'livre');
  // Concluído ontem não é "concluído hoje": passa a "trabalhado nos últimos dias".
  assert.equal(M.estadoDoBloco([{ d: '2026-10-12', c: '2026-10-12T16:00:00-03:00' }], casas, mapa(), HOJE, 60).tipo, 'recente');
  for (const tipo of ['planejado', 'andamento', 'concluido', 'agendado', 'recente', 'anterior', 'livre']) assert.ok(M.BLOCOS[tipo].fundo);
}

// --- cor da casa
{
  assert.equal(M.corDaCasa(null, HOJE).vazia, true);
  const hoje = M.corDaCasa(visita('a', 'RECUSA', HOJE), HOJE);
  assert.deepEqual([hoje.fundo, hoje.apagada], [M.POR_ID.RECUSA.cor, false]);
  const antes = M.corDaCasa(visita('a', 'RECUSA', '2026-10-01'), HOJE);
  assert.deepEqual([antes.fundo, antes.texto, antes.apagada], ['#ffffff', M.POR_ID.RECUSA.cor, true]);
  assert.equal(M.corDaCasa(visita('a', 'TRABALHADO', HOJE, { l: 1 }), HOJE).fundo, M.LARVA.cor);
}

// --- próxima casa, na ordem da volta
{
  const ultimas = mapa(visita('b', 'TRABALHADO', HOJE));
  assert.equal(M.proximaCasa(casas, ultimas, HOJE, 'a').id, 'c');
  assert.equal(M.proximaCasa(casas, ultimas, HOJE, 'd').id, 'a');
  const todas = mapa(...casas.map((c, i) => visita(c.id, 'TRABALHADO', HOJE, { i: i + 1 })));
  assert.equal(M.proximaCasa(casas, todas, HOJE, 'a'), null);
}

// --- visita pronta para envio
{
  const agora = new Date('2026-10-13T13:00:00Z');
  const v = M.novaVisita({ bloco: 'q1', imovel: 'a', data: HOJE, situacao: 'TRABALHADO', recipientes_existentes: 1, recipientes_agua: 0, recipientes_larva: 3, tubitos: '2', controle_mecanico: true, agora });
  assert.deepEqual([v.recipientes_existentes, v.recipientes_agua, v.recipientes_larva, v.larvas, v.tubitos, v.controle_mecanico], [3, 3, 3, true, 2, true]);
  assert.equal(v.horario, '2026-10-13T13:00:00.000Z');
  assert.match(v.uuid, /^[A-Za-z0-9-]{8,64}$/);
  const fechado = M.novaVisita({ bloco: 'q1', imovel: 'a', data: HOJE, situacao: 'FECHADO', recipientes_existentes: 4, larvas: true, tubitos: 3, tratamento_focal: true, observacao: '  cão bravo ' });
  assert.deepEqual([fechado.recipientes_existentes, fechado.larvas, fechado.tubitos, fechado.tratamento_focal, fechado.observacao], [0, false, 0, false, 'cão bravo']);
  const registro = M.comoRegistro(v, { id: 7, nome: 'Ana' });
  assert.deepEqual([registro.m, registro.s, registro.l, registro.ai, registro.pendente, registro.d], ['a', 'TRABALHADO', 1, 7, true, HOJE]);
  assert.deepEqual(registro.rt, []);
}

// --- recipientes por tipo (ficha do SISAWEB)
{
  const lista = [{ t: 30, e: 1 }, { t: 12, e: 1, a: 2, l: 1 }, { t: 12, e: 1 }, { t: 41, e: 5 }, { t: 5, e: 0 }];
  assert.deepEqual(M.recipientesPorTipo(lista), [{ t: 12, e: 3, a: 2, l: 1 }, { t: 30, e: 1, a: 0, l: 0 }]);
  assert.deepEqual(M.somaDosTipos(lista), { e: 4, a: 2, l: 1 });
  // Anotados por tipo, os totais da visita são a soma; os contadores gerais são ignorados.
  const v = M.novaVisita({ bloco: 'q1', imovel: 'a', data: HOJE, situacao: 'PARCIAL', recipientes_existentes: 9, recipientes: lista });
  assert.deepEqual([v.recipientes_existentes, v.recipientes_agua, v.recipientes_larva, v.larvas], [4, 2, 1, true]);
  assert.deepEqual(v.recipientes.map(r => r.t), [12, 30]);
  assert.deepEqual(M.comoRegistro(v, null).rt, v.recipientes);
  // Sem inspeção não há recipiente.
  assert.deepEqual(M.novaVisita({ bloco: 'q1', imovel: 'a', data: HOJE, situacao: 'RECUSA', recipientes: lista }).recipientes, []);
}

// --- pontos, níveis e medalhas
{
  assert.equal(M.pontos({ visitas: 10, recuperadas: 2, quarteiroes: 1 }), 10 * 10 + 2 * 15 + 50);
  assert.deepEqual([M.nivel(0).numero, M.nivel(99).numero, M.nivel(100).numero], [1, 1, 2]);
  const meio = M.nivel(200);
  assert.deepEqual([meio.titulo, meio.piso, meio.teto, meio.pct], ['Sentinela do bairro', 100, 300, 50]);
  assert.equal(M.nivel(99999).teto, null);
  const ganhas = agente => M.medalhas(agente).filter(m => m.ganha).map(m => m.nome);
  assert.deepEqual(ganhas({}), []);
  assert.deepEqual(ganhas({ visitas: 1 }), ['Primeiro passo']);
  assert.deepEqual(ganhas({ visitas: 30, hoje: 25, recuperadas: 5, quarteiroes: 1 }), ['Primeiro passo', 'Ritmo forte', 'Porta aberta', 'Quarteirão fechado']);
  // Sem internet, o que está na fila já conta para o agente.
  const comFila = M.comFila({ visitas: 4, hoje: 1, quarteiroes: 0 }, [{ data: HOJE }, { data: '2026-10-12' }], HOJE, 1);
  assert.deepEqual([comFila.visitas, comFila.hoje, comFila.quarteiroes, comFila.quarteiroes_hoje], [6, 2, 1, 1]);
}

// --- resumo do dia
{
  const r = M.resumoDoDia([visita('a', 'TRABALHADO', HOJE, { l: 1 }), visita('b', 'FECHADO', HOJE), visita('c', 'RECUSA', '2026-10-12')], HOJE);
  assert.deepEqual([r.total, r.larvas, r.pendencias, r.porSituacao.TRABALHADO, r.porSituacao.FECHADO], [2, 1, 1, 1, 1]);
  assert.equal(M.diasEntre('2026-10-01', HOJE), 12);
}

// --- quarteirão dividido em L
{
  // Quarteirão retangular alinhado ao norte, 100 m x 60 m, com uma casa no meio de cada lado.
  const k = Math.cos(-20.72 * Math.PI / 180), mx = 0.0005 / k, my = 0.00027;
  const bloco = { c: [-47.88, -20.72], g: [[[[-47.88 - mx, -20.72 - my], [-47.88 + mx, -20.72 - my], [-47.88 + mx, -20.72 + my], [-47.88 - mx, -20.72 + my], [-47.88 - mx, -20.72 - my]]]] };
  const casa = (id, dx, dy) => ({ id, x: -47.88 + dx * mx, y: -20.72 + dy * my });
  const lados = [casa('norte', 0.1, 0.9), casa('leste', 0.9, 0.05), casa('sul', -0.1, -0.9), casa('oeste', -0.9, -0.05)];
  const ids = parte => M.casasDoL(bloco, lados, parte).map(c => c.id).sort();
  assert.deepEqual(ids('NE'), ['leste', 'norte']);
  assert.deepEqual(ids('SO'), ['oeste', 'sul']);
  assert.deepEqual(ids('NO'), ['norte', 'oeste']);
  assert.deepEqual(ids('SE'), ['leste', 'sul']);
  assert.deepEqual(ids(''), ['leste', 'norte', 'oeste', 'sul']);
  // Os dois Ls de uma divisão nunca deixam casa de fora nem repetem casa, mesmo com casas espalhadas.
  const muitas = Array.from({ length: 60 }, (_, i) => casa('c' + i, Math.cos(i) * 0.95, Math.sin(i * 1.7) * 0.95));
  for (const [a, b] of [['NE', 'SO'], ['NO', 'SE']]) {
    const x = M.casasDoL(bloco, muitas, a), y = M.casasDoL(bloco, muitas, b);
    assert.equal(x.length + y.length, muitas.length);
    assert.ok(x.every(c => !y.includes(c)));
  }
  // A linha da divisão NE/SO liga os cantos NO e SE.
  const [no, se] = M.linhaDaDivisao(bloco, 'NE');
  assert.ok(no[0] < -47.88 && no[1] > -20.72 && se[0] > -47.88 && se[1] < -20.72);
  // Agenda: cada pessoa conta só os imóveis do seu L.
  const dividido = Object.assign({}, bloco, { id: 'q9', casas: lados, extras: [], planos: [{ d: HOJE, ri: 1, r: 'Ana', pt: 'NE' }, { d: HOJE, ri: 2, r: 'Bia', pt: 'SO' }] });
  const agenda = M.agendaDoDia([dividido], HOJE);
  assert.deepEqual(agenda.map(g => [g.nome, g.imoveis, g.partes.get('q9')]), [['Ana', 2, 'NE'], ['Bia', 2, 'SO']]);
}

// --- opções, controle por recipiente e focal
{
  assert.deepEqual(M.OPCOES.map(s => s.id), ['TRABALHADO', 'FECHADO', 'DESOCUPADO', 'PARCIAL', 'RECUSA']);
  assert.ok(M.POR_ID.TEMPORADA);   // registros antigos continuam legíveis
  assert.ok(M.INSPECIONADO.has('PARCIAL'));   // parcial também anota recipientes
  const linhas = [{ t: 28, e: 2, l: 1, c: 'F', p: 'VECTOBAC' }, { t: 28, e: 1, c: 'M' }, { t: 28, e: 1, c: 'M' }, { t: 5, e: 1, c: 'X' }];
  assert.deepEqual(M.recipientesPorTipo(linhas), [{ t: 5, e: 1, a: 0, l: 0 }, { t: 28, e: 2, a: 1, l: 1, c: 'F', p: 'VECTOBAC' }, { t: 28, e: 2, a: 0, l: 0, c: 'M' }]);
  const v = M.novaVisita({ bloco: 'q1', imovel: 'a', data: HOJE, situacao: 'TRABALHADO', recipientes: linhas, atividade: 'ADL' });
  assert.deepEqual([v.controle_mecanico, v.controle_alternativo, v.tratamento_focal, v.focal_produto, v.atividade], [true, false, true, ['VECTOBAC'], 'ADL']);
  const so = M.novaVisita({ bloco: 'q1', imovel: 'a', data: HOJE, situacao: 'TRABALHADO', tratamento_focal: true, focal_produto: ['NATULAR', 'ABATE'] });
  assert.deepEqual(so.focal_produto, ['NATULAR']);
  const fechado = M.novaVisita({ bloco: 'q1', imovel: 'a', data: HOJE, situacao: 'FECHADO', tratamento_focal: true, focal_produto: ['NATULAR'] });
  assert.deepEqual([fechado.tratamento_focal, fechado.focal_produto], [false, []]);
  assert.equal(M.comoRegistro(v, null).fp, 'VECTOBAC');
}

// --- histórico do imóvel: servidor e aparelho juntos, sem repetir, do mais novo ao mais antigo
{
  const antiga = visita('a', 'FECHADO', '2025-03-02', { i: 2, u: 'u2' });
  const manha = visita('a', 'RECUSA', HOJE, { i: 7, u: 'u7' });
  const tarde = visita('a', 'TRABALHADO', HOJE, { i: 9, u: 'u9' });
  const outra = visita('b', 'TRABALHADO', HOJE, { i: 8, u: 'u8' });
  const pendente = Object.assign(visita('a', 'TRABALHADO', HOJE, { u: 'u10' }), { i: 0, pendente: true });
  // A mesma visita que já chegou ao servidor não aparece duas vezes; o imóvel b fica de fora.
  const lista = M.historicoDoImovel([antiga, tarde, manha, outra, tarde], [pendente, Object.assign({}, tarde, { pendente: true, i: 0 })], 'a');
  assert.deepEqual(lista.map(v => v.u), ['u10', 'u9', 'u7', 'u2']);
  assert.equal(lista[1].pendente, undefined);
  assert.deepEqual(M.historicoDoImovel([], [], 'a'), []);
  assert.deepEqual(M.historicoDoImovel(null, undefined, 'a'), []);
}

console.log('casa_a_casa_model: ok');

// A agenda salta o fim de semana nos atalhos, sem excluir datas manuais.
assert.deepEqual(M.diasDeTrabalho('2026-10-16'), ['2026-10-16', '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22']);
assert.equal(M.diasDeTrabalho('2026-10-17')[0], '2026-10-19');
const agenda = M.agendaDoDia([
  { casas: [{ id: 'a' }], extras: [{ id: 'extra' }], planos: [{ d: HOJE, ri: 1, r: 'Ana' }] },
  { casas: [{ id: 'b' }], planos: [{ d: HOJE, ri: 2, r: 'Ana', c: HOJE }] },
  { casas: [{ id: 'c' }], planos: [{ d: '2026-10-20', ri: 1, r: 'Ana' }] },
], HOJE);
assert.deepEqual(agenda.map(g => [g.id, g.imoveis]), [[1, 2], [2, 1]]);
const roteiro = Array.from({ length: 31 }, (_, i) => ({ id: String(i), n: '10', cp: 'Unidade ' + i }));
const folhas = M.paginasDoRoteiro(roteiro);
assert.deepEqual(folhas.map(p => p.length), [14, 14, 3]);
assert.deepEqual(folhas.flat(), roteiro); // Nenhum imóvel repetido ou perdido entre folhas.
assert.deepEqual(M.paginasDoRoteiro([]), [[]]);
const longos = roteiro.map(c => ({ ...c, rua: 'Rua ' + 'nome muito longo '.repeat(10), cp: 'Unidade com acesso pelos fundos' }));
assert(M.paginasDoRoteiro(longos)[0].length < 14);
assert.deepEqual(M.paginasDoRoteiro(longos).flat(), longos);
const concluidoReal = M.estadoDoBloco([{ d: '2026-10-10', c: HOJE + 'T15:00:00Z' }], casas, mapa(visita('a', 'TRABALHADO', '2026-10-11')), HOJE, 60);
assert.deepEqual([concluidoReal.inicio, concluidoReal.prog.feitas], ['2026-10-10', 1]);
