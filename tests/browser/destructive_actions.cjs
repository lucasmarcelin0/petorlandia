// Teste de navegador opcional: requer o pacote playwright e Chrome instalado.
// Não acessa o servidor nem qualquer banco de dados.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '../..');
let browser, page;
before(async () => {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  page = await browser.newPage();
});
after(async () => { await browser?.close(); });
async function render(html) {
  await page.setContent(html);
  await page.addStyleTag({ path: path.join(root, 'static/bootstrap.min.css') });
  await page.addStyleTag({ path: path.join(root, 'static/css/destructive_actions.css') });
  await page.addScriptTag({ path: path.join(root, 'static/js/destructive_actions.js') });
}

test('abrir opções não confirma nem envia; o botão original mantém CSRF e confirmação', async () => {
  await render(`<form id="form" method="post" action="/animal/1/deletar"
    onsubmit="event.preventDefault(); window.submits++">
    <input name="csrf_token" value="token-teste" type="hidden">
    <button id="delete" type="submit" onclick="return confirm('Excluir?')">Excluir animal</button>
  </form>`);
  await page.evaluate(() => { window.submits = 0; window.original = document.querySelector('#delete'); });
  let dialogs = 0;
  const cancel = dialog => { dialogs++; dialog.dismiss(); };
  page.on('dialog', cancel);
  assert.equal(await page.locator('#delete').isVisible(), false);
  await page.locator('summary').click();
  assert.equal(dialogs, 0);
  assert.equal(await page.evaluate(() => window.submits), 0);
  await page.locator('#delete').click();
  assert.equal(dialogs, 1);
  assert.equal(await page.evaluate(() => window.submits), 0);
  page.off('dialog', cancel);
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#delete').click();
  assert.deepEqual(await page.evaluate(() => ({
    submits: window.submits,
    same: window.original === document.querySelector('#delete'),
    csrf: new FormData(document.querySelector('#form')).get('csrf_token'),
    owner: document.querySelector('#delete').form.id,
  })), {submits: 1, same: true, csrf: 'token-teste', owner: 'form'});
});

test('controles dinâmicos, ícones e rótulos alterados também ficam recolhidos', async () => {
  await render('<div id="list"></div><button id="changing">Selecionar</button>');
  await page.evaluate(() => {
    document.querySelector('#list').innerHTML = '<button id="icon" aria-label="Remover Rex"><i class="fas fa-trash"></i></button>';
    document.querySelector('#changing').textContent = '🗑️ Excluir modelo';
  });
  await page.waitForFunction(() => document.querySelectorAll('.destructive-actions').length === 2);
  assert.equal(await page.locator('#icon').isVisible(), false);
  assert.equal(await page.locator('#changing').isVisible(), false);
  // Reexecuções/atualizações não criam menus dentro de menus.
  await page.evaluate(() => document.querySelector('#icon i').textContent = '');
  assert.equal(await page.locator('.destructive-actions .destructive-actions').count(), 0);
});

test('marcação explícita protege limpeza de registros sem esconder filtros', async () => {
  await render('<button id="purge" data-destructive-action>Limpar validações</button><button id="filter">Limpar filtros</button>');
  assert.equal(await page.locator('#purge').isVisible(), false);
  assert.equal(await page.locator('#filter').isVisible(), true);
});

test('menus existentes, confirmação final e ações comuns mantêm seu fluxo', async () => {
  await render(`<button id="edit">Editar</button><button id="save">Salvar alterações</button>
    <div class="dropdown-menu"><button id="menu-delete">Excluir agendamento</button></div>
    <div data-destructive-confirmation><button id="confirm">Remover</button></div>
    <details class="destructive-actions"><summary>Mais opções</summary><button id="protected">Excluir tutor</button></details>`);
  assert.equal(await page.locator('.destructive-actions').count(), 1);
  assert.equal(await page.locator('#edit').isVisible(), true);
  assert.equal(await page.locator('#save').isVisible(), true);
  assert.equal(await page.locator('#confirm').isVisible(), true);
  assert.equal(await page.locator('#protected').isVisible(), false);
});

test('modelo indisponível não deixa menu vazio e seleção volta a oferecer opções', async () => {
  await render('<button id="model" class="d-none" disabled>Excluir vacina</button>');
  assert.equal(await page.locator('summary').isVisible(), false);
  await page.evaluate(() => document.querySelector('#model').classList.remove('d-none'));
  assert.equal(await page.locator('summary').isVisible(), true);
  await page.locator('summary').click();
  assert.equal(await page.locator('#model').isDisabled(), true);
  await page.evaluate(() => { document.querySelector('#model').disabled = false; });
  assert.equal(await page.locator('#model').isEnabled(), true);
});

test('teclado abre; Escape, clique externo e outro menu fecham', async () => {
  await render('<button id="a">Excluir A</button><button id="b">Excluir B</button><button id="outside">Editar</button>');
  const summaries = page.locator('summary');
  await summaries.first().focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#a').isVisible(), true);
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('#a').evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#a').isVisible(), false);
  assert.equal(await summaries.first().evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#a').isVisible(), true);
  await summaries.last().click();
  assert.equal(await page.locator('#a').isVisible(), false);
  assert.equal(await page.locator('#b').isVisible(), true);
  await page.locator('#outside').click();
  assert.equal(await page.locator('#b').isVisible(), false);
});

test('listeners diretos e delegados são preservados em tela de celular', async () => {
  await page.setViewportSize({width: 360, height: 740});
  await render(`<div id="card" class="d-flex flex-wrap gap-2 p-3">
    <button class="btn">Consulta</button><button class="btn">Ficha</button><button class="btn">Editar</button>
    <button id="remove" class="btn btn-outline-danger" aria-label="Remover animal"><i class="fas fa-trash"></i></button>
  </div>`);
  await page.evaluate(() => {
    window.direct = 0; window.delegated = 0;
    document.querySelector('#remove').addEventListener('click', () => window.direct++);
    document.querySelector('#card').addEventListener('click', event => {
      if (event.target.closest('#remove')) window.delegated++;
    });
  });
  await page.locator('summary').click();
  assert.deepEqual(await page.evaluate(() => [window.direct, window.delegated]), [0, 0]);
  const bounds = await page.locator('#remove').boundingBox();
  assert.ok(bounds.width >= 44 && bounds.height >= 44, 'exclusão exige alvo de toque de pelo menos 44px');
  await page.locator('#remove').click();
  assert.deepEqual(await page.evaluate(() => [window.direct, window.delegated]), [1, 1]);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
});
