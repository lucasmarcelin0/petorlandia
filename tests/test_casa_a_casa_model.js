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

console.log('casa_a_casa_model: ok');
