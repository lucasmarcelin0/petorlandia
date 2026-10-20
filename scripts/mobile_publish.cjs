// Executado somente a partir da main pelo workflow de publicação.
// Nunca executa arquivos, comandos ou expressões fornecidos pelo PR.
const MARKER = /^PetOrlandia-Publish: true\s*$/m;
const REQUIRED = ['pytest', 'authorization-tests'];

async function publish({ github, context, core }) {
  const repo = context.repo;
  const payload = context.payload;
  let numbers = [];
  if (payload.pull_request) numbers = [payload.pull_request.number];
  else if (payload.inputs?.pr) numbers = [Number(payload.inputs.pr)];
  else if (payload.workflow_run) {
    const run = payload.workflow_run;
    if (run.event !== 'pull_request' || run.head_repository?.full_name !== `${repo.owner}/${repo.repo}`) return;
    numbers = (await github.rest.pulls.list({ ...repo, state: 'open', base: 'main',
      head: `${repo.owner}:${run.head_branch}`, per_page: 100 })).data.map(pr => pr.number);
  }

  for (const pull_number of numbers) {
    let pr = (await github.rest.pulls.get({ ...repo, pull_number })).data;
    if (pr.state !== 'open' || pr.base.ref !== 'main' || pr.head.repo?.full_name !== `${repo.owner}/${repo.repo}`) continue;
    const commit = (await github.rest.repos.getCommit({ ...repo, ref: pr.head.sha })).data;
    const requested = pr.labels.some(label => label.name === 'publicar') || MARKER.test(commit.commit.message);
    if (!requested) { core.info(`PR #${pull_number}: sem pedido de publicação.`); continue; }
    const permission = (await github.rest.repos.getCollaboratorPermissionLevel({ ...repo, username: pr.user.login })).data.permission;
    if (!['admin', 'maintain', 'write'].includes(permission)) {
      core.warning(`PR #${pull_number}: autor sem permissão de escrita; revisão manual necessária.`); continue;
    }
    if (pr.draft) {
      await github.graphql('mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{id}}}', { id: pr.node_id });
      core.info(`PR #${pull_number}: publicação solicitada; rascunho convertido em pronto.`);
    }
    // O CI faz checkout do merge de teste, mas o GitHub associa os checks ao
    // head do PR. Consultar merge_commit_sha não encontra esses resultados.
    if (!pr.merge_commit_sha || pr.mergeable !== true) {
      core.warning(`PR #${pull_number}: merge ainda indisponível ou com conflito.`); continue;
    }
    const checks = await github.paginate(github.rest.checks.listForRef,
      { ...repo, ref: pr.head.sha, filter: 'latest', per_page: 100 });
    const approved = REQUIRED.every(name => checks.some(check => check.name === name &&
      check.app?.id === 15368 && check.status === 'completed' && check.conclusion === 'success'));
    if (!approved) { core.info(`PR #${pull_number}: aguardando os dois testes obrigatórios.`); continue; }
    // Revalida o head para não publicar uma atualização que não foi examinada.
    const current = (await github.rest.pulls.get({ ...repo, pull_number })).data;
    if (current.head.sha !== pr.head.sha || current.merge_commit_sha !== pr.merge_commit_sha) continue;
    let result;
    try {
      result = (await github.rest.pulls.merge({ ...repo, pull_number,
        sha: pr.head.sha, merge_method: 'merge' })).data;
    } catch (error) {
      if ([405, 409].includes(error.status)) { core.warning(`PR #${pull_number}: GitHub bloqueou o merge; preservado para revisão.`); continue; }
      throw error;
    }
    if (!result.merged) { core.warning(`PR #${pull_number}: merge não concluído.`); continue; }
    core.info(`PR #${pull_number} integrado: ${result.sha}`);
    // Merges feitos pelo GITHUB_TOKEN não disparam eventos push em outros
    // workflows. workflow_dispatch é a exceção oficial: dispara os dois CI
    // na main, cujos checks liberam a integração nativa do Heroku.
    for (const workflow_id of ['tests.yml', 'authorization-gate.yml']) {
      await github.rest.actions.createWorkflowDispatch({ ...repo, workflow_id, ref: 'main' });
    }
    await core.summary.addHeading('Correção integrada').addRaw(
      `PR #${pull_number}: ${result.sha}\n\nTestes da main iniciados. A integração GitHub do Heroku publica após aprovação.\n`).write();
  }
}
module.exports = { publish, MARKER, REQUIRED };
