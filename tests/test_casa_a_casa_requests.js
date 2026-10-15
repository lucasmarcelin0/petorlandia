/* Testa a função de rede usada pela tela, incluindo o JSON real do CSRFProtect. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/casa_a_casa.js'), 'utf8');
const requestSource = source.slice(source.indexOf('  async function pedir('), source.indexOf('  function aplicarEstado('));
const resposta = (status, dados, json = true) => ({ status, ok: status >= 200 && status < 300, redirected: false,
  headers: { get: () => json ? 'application/json' : 'text/html' }, json: async () => dados });
const csrf = () => resposta(400, { error: 'CSRF token missing or invalid', message: 'Falha de validação. Recarregue a página e tente novamente.', errors: { csrf_token: ['Falha de validação.'] } });
function ambiente(respostas) {
  const calls = [];
  const S = { csrf: 'vencido', cursor: 8 };
  const context = vm.createContext({ S, cfg: { urls: { estado: '/estado' } }, fetch: async (url, init) => {
    calls.push({ url, init: JSON.parse(JSON.stringify(init)) });
    return respostas.shift();
  } });
  vm.runInContext(requestSource, context);
  return { pedir: context.pedir, calls, S };
}
(async () => {
  const corpo = { acao: 'planejar', blocos: ['q570'], data: '2026-10-15', responsavel_id: 7, esperado: [{ b: 'q570' }] };
  const a = ambiente([csrf(), resposta(200, { csrf: 'renovado' }), resposta(200, { ok: true, feitos: 1 })]);
  assert.equal((await a.pedir('/plano', corpo)).feitos, 1);
  assert.deepEqual(a.calls.map(c => c.url), ['/plano', '/estado?desde=8', '/plano']);
  assert.equal(a.calls[2].init.headers['X-CSRFToken'], 'renovado');
  assert.equal(a.calls[0].init.referrerPolicy, 'same-origin');
  assert.equal(a.calls[2].init.referrerPolicy, 'same-origin');
  assert.equal(a.calls[2].init.body, a.calls[0].init.body);
  assert.equal(a.calls[1].init.cache, 'no-store');
  const b = ambiente([resposta(400, { erro: 'Data inválida.' })]);
  await assert.rejects(b.pedir('/plano', corpo), /Data inválida/);
  assert.equal(b.calls.length, 1); // Erro de negócio não repete a mutação.
  const c = ambiente([csrf(), resposta(200, { csrf: 'renovado' }), csrf()]);
  await assert.rejects(c.pedir('/plano', corpo), /seleção e as visitas foram preservadas/);
  assert.equal(c.calls.length, 3); // Nunca entra em loop de renovação.
  const d = ambiente([resposta(400, null, false), resposta(200, { csrf: 'renovado' }), resposta(200, { ok: true })]);
  assert.equal((await d.pedir('/plano', corpo)).ok, true);
  const e = ambiente([resposta(409, { erro: 'O plano mudou.' })]);
  await assert.rejects(e.pedir('/plano', corpo), erro => erro.conflito === true);
  console.log('casa_a_casa_requests: recuperação JSON/HTML, preservação do corpo e retry limitado verificados.');
})().catch(error => { console.error(error); process.exitCode = 1; });
