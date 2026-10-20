const { test } = require('node:test');
const assert = require('node:assert/strict');
const { publish } = require('./mobile_publish.cjs');

function fixture(overrides = {}) {
  const pr = { number: 1, node_id: 'PR_1', state: 'open', base: {ref: 'main'},
    head: {sha: 'head1', repo: {full_name: 'owner/repo'}}, merge_commit_sha: 'merge1',
    mergeable: true, user: {login: 'owner'}, draft: false, labels: [], ...overrides };
  const calls = { merges: [], dispatches: [], ready: 0 };
  const f = { pr, calls, message: 'Correção\n\nPetOrlandia-Publish: true', permission: 'admin',
    checks: ['pytest', 'authorization-tests'].map(name =>
      ({name, app: {id: 15368}, status: 'completed', conclusion: 'success'})) };
  const github = {rest: {
    pulls: {get: async () => ({data: f.pr}), list: async () => ({data: [f.pr]}),
      merge: async args => {calls.merges.push(args); return {data: {merged: true, sha: 'published'}};}},
    repos: {getCommit: async () => ({data: {commit: {message: f.message}}}),
      getCollaboratorPermissionLevel: async () => ({data: {permission: f.permission}})},
    checks: {listForRef: () => {}},
    actions: {createWorkflowDispatch: async args => calls.dispatches.push(args)}},
    paginate: async () => f.checks, graphql: async () => {calls.ready++;} };
  const summary = {addHeading() {return this;}, addRaw() {return this;}, async write() {}};
  f.run = payload => publish({github, context: {repo: {owner: 'owner', repo: 'repo'},
    payload: payload || {pull_request: {number: 1}}}, core: {info() {}, warning() {}, summary}});
  return f;
}

test('pedido explícito e dois checks aprovados integram o SHA examinado e disparam CI', async () => {
  const f = fixture(); await f.run();
  assert.equal(f.calls.merges[0].sha, 'head1');
  assert.equal(f.calls.merges[0].merge_method, 'merge');
  assert.deepEqual(f.calls.dispatches.map(x => x.workflow_id), ['tests.yml', 'authorization-gate.yml']);
});
test('rascunho sem pedido não publica', async () => {
  const f = fixture({draft: true}); f.message = 'Apenas análise'; await f.run();
  assert.equal(f.calls.ready, 0); assert.equal(f.calls.merges.length, 0);
});
test('pedido explícito converte rascunho sem exigir celular ou PC', async () => {
  const f = fixture({draft: true}); await f.run(); assert.equal(f.calls.ready, 1);
});
test('label publicar também registra intenção', async () => {
  const f = fixture({labels: [{name: 'publicar'}]}); f.message = 'Correção';
  await f.run(); assert.equal(f.calls.merges.length, 1);
});
test('fork, autor sem escrita, base errada e conflitos não publicam', async () => {
  for (const overrides of [{head: {sha: 'h', repo: {full_name: 'externo/repo'}}},
    {base: {ref: 'outra'}}, {mergeable: false}]) {
    const f = fixture(overrides); await f.run(); assert.equal(f.calls.merges.length, 0);
  }
  const f = fixture(); f.permission = 'read'; await f.run(); assert.equal(f.calls.merges.length, 0);
});
test('teste ausente, pendente, falho ou de outro aplicativo impede publicação', async () => {
  for (const change of [c => c.pop(), c => {c[0].status = 'in_progress';},
    c => {c[1].conclusion = 'failure';}, c => {c[0].app.id = 999;}]) {
    const f = fixture(); change(f.checks); await f.run(); assert.equal(f.calls.merges.length, 0);
  }
});
test('workflow_run só trata PRs do próprio repositório', async () => {
  const f = fixture(); await f.run({workflow_run: {event: 'push', head_repository: {full_name: 'owner/repo'}}});
  assert.equal(f.calls.merges.length, 0);
  await f.run({workflow_run: {event: 'pull_request', head_repository: {full_name: 'externo/repo'}}});
  assert.equal(f.calls.merges.length, 0);
  await f.run({workflow_run: {event: 'pull_request', head_repository: {full_name: 'owner/repo'}, head_branch: 'claude/fix'}});
  assert.equal(f.calls.merges.length, 1);
});
