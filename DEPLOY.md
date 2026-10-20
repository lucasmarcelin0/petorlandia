# Deploy no Heroku

**O caminho normal é mesclar na `main`**: o Heroku publica sozinho depois que
os testes passam (veja "Automatico: merge na main publica" abaixo). Os
caminhos manuais desta página ficam para emergência.

## Pelo celular: Codex Cloud e Claude Code Cloud

O fluxo compartilhado está em `AGENTS.md` (Codex) e `CLAUDE.md` (Claude).
Ele funciona com o PC desligado: **agente na nuvem → branch/PR no GitHub →
testes → merge → integração GitHub do Heroku → confirmação do release/site**.

Pedidos para corrigir, melhorar ou implementar algo no PetOrlândia já
incluem autorização para publicar no Heroku `petorlandia`, sem confirmação
adicional. Exceções: somente análise, plano, revisão ou rascunho, ou instrução
expressa para não publicar/aguardar. A instrução específica mais recente
prevalece. O agente deve testar, publicar e confirmar o release/site;
criar ou integrar o PR, por si só, não conclui a publicação.

Nos pedidos de alteração, inclua no último commit:

```text
PetOrlandia-Publish: true
```

O workflow **Publicar correcao solicitada** reconhece esse marcador (ou a
label `publicar`), aceita somente PRs do próprio repositório de autores com
permissão de escrita e integra após `pytest` e `authorization-tests` aprovados.
Sem o marcador/label, não integra automaticamente. Rascunhos com pedido
explícito são convertidos para prontos. Conflitos e testes reprovados bloqueiam.

O merge usa `GITHUB_TOKEN`; por isso o workflow dispara explicitamente os dois
CI na `main` via `workflow_dispatch` (eventos de push gerados pelo token de
automação não disparam outros workflows). Não precisa de PAT pessoal adicional.
Após aprovação, a integração nativa publica e **Confirmar publicacao no Heroku**
confere o SHA do slug, o release concluído e a resposta HTTP 200 do site.
Esse último workflow também pode ser executado manualmente para diagnosticar.

No celular:

- **Codex**: escolha um ambiente Cloud publicado com o repositório
  `lucasmarcelin0/petorlandia`. Se ainda não existir, crie/publique uma vez
  pela web/desktop, com Python 3.12 e as dependências de teste do projeto.
- **Claude**: abra a aba **Code**, escolha uma sessão **Cloud** e o mesmo
  repositório. A conexão GitHub deve permitir criar branches e PRs.
- Peça: “Corrija [problema] no PetOrlândia.” Testar e publicar já fazem parte
  da execução; para só revisar, diga explicitamente “não publique”.
  Ao final, confira o link do deployment e da confirmação.
- Controle remoto de uma sessão **Local** nos dois aplicativos exige o PC
  ligado. Um chat comum sem acesso ao repositório não configura esse fluxo.

O agente não precisa de token do Heroku no ambiente Cloud para esse caminho.
A credencial dedicada de automação fica apenas em `HEROKU_API_KEY` no GitHub
Actions; `HEROKU_APP_NAME=petorlandia` fixa o alvo dos workflows de fallback.
Renovar o login no PC não renova os secrets do GitHub automaticamente.

Referências: [Codex Cloud](https://learn.chatgpt.com/docs/environments/cloud-environments),
[Claude Cloud](https://code.claude.com/docs/en/claude-code-on-the-web),
[integração Heroku/GitHub](https://devcenter.heroku.com/articles/github-integration).

## Pelo computador (script PowerShell)

```bash
powershell -File scripts/deploy_heroku.ps1
```

Publique por aqui só a `main` (o próximo merge substitui qualquer outra
branch publicada assim). O script faz, nesta ordem, e para no primeiro problema:

1. confere que o remoto `heroku` existe e aponta para o Git do Heroku;
2. confere que não há alteração rastreada sem commit;
3. confere que o Heroku não tem commit que você não tem (sem `--force`, para não apagar correção que já está em produção);
4. roda o **preflight** — o que quebra o release phase;
5. roda os testes, se você pedir com `-TestPath`;
6. publica e confirma que o Heroku registrou o commit.

Variações:

```bash
powershell -File scripts/deploy_heroku.ps1 -PreflightOnly
```

```bash
powershell -File scripts/deploy_heroku.ps1 -TestPath tests -PytestArgs "-q"
```

## Automatico: merge na main publica

O app usa a integracao GitHub do Heroku (Dashboard > app > Deploy > Automatic
deploys from `main`), com **Wait for GitHub checks to pass** marcado. Todo
merge na `main` vira release sozinho, mas so depois que os checks do commit
(Test Suite e authorization-gate) passam; se algum falhar, nada vai para o ar.
O release phase (`flask db upgrade`) roda como em qualquer deploy, e o
andamento fica na aba Activity do app.

Regra que vem junto: **publique sempre pela `main`**. A integracao publica a
`main` por cima do que estiver no ar, sem a trava de fast-forward do workflow
abaixo: um commit publicado direto no Heroku (script PowerShell ou
`git push heroku` de outra branch) some de producao no proximo merge. Se algo
precisar ir ao ar antes, mescle na `main`.

Para publicar a `main` na hora, sem esperar um merge: Deploy > Manual deploy >
`main` > **Deploy Branch**.

## Pelo GitHub Actions (sem depender da sua maquina)

Fallback, quando a integracao nao serve (republicar com as travas, ou um
ref especifico em emergencia -- lembrando que o proximo merge na `main`
substitui o que for publicado assim): o workflow **Deploy (Heroku)**, em
Actions > Deploy (Heroku) > Run workflow. Ele nao roda sozinho no push, senao
cada merge geraria dois deploys. Ele pede o `ref` a publicar (padrao `main`),
o `app` (vazio = descobre sozinho) e se deve rodar a suite antes (padrao sim).
Funciona pelo app do GitHub no celular.

O workflow faz, na ordem, as mesmas travas do script manual:

1. confere o token do Heroku (`scripts/check_heroku_token.py`) e, se ele foi
   recusado, para logo dizendo como trocar;
2. preflight (`scripts/preflight_deploy.py`);
3. suite completa, com os mesmos comandos do workflow de testes;
4. guarda de artefatos sensiveis;
5. push **sem `--force`**, recusando publicar se o Heroku tem commit que o ref
   nao tem;
6. espera o release phase terminar (`scripts/wait_heroku_release.py`) e falha
   com o log quando o `flask db upgrade` quebra.

### Configuracao (uma vez)

Em Settings > Secrets and variables > Actions, crie **um** secret:

| Secret | Valor |
|---|---|
| `HEROKU_API_KEY` | token sem validade: `heroku authorizations:create -d "GitHub Actions deploy"` (sem `-e`) |

O token com prazo (`-e 2592000`, 30 dias) era o que travava o deploy de tempos
em tempos com um 401: ele expirava em silencio. Agora a recomendacao e o token
sem validade, com duas protecoes no lugar do prazo:

- o workflow Deploy (Heroku) confere o token no primeiro passo
  (`scripts/check_heroku_token.py`) e, se ele foi recusado, para dizendo como
  trocar; o mesmo script confere a validade a mao;
- se vazar, revogue na hora: `heroku authorizations` e
  `heroku authorizations:revoke <id>`, e gere outro.

Sem computador a mao, a API Key de dashboard.heroku.com/account (Account
settings > API Key > Reveal) tambem serve: nao expira por data, mas deixa de
valer quando a senha da conta muda.

O fluxo Cloud normal não exige copiar esse token para o Claude/Codex. Para
diagnóstico e contingência, prefira os workflows deste repositório, que usam
o secret do GitHub; credenciais adicionais no agente só se forem indispensáveis.

Com a integracao GitHub ligada, o token nao e mais necessario para o deploy
normal: so para este workflow manual, para o CLI e para o agente ler logs.

O nome do app nao precisa ser configurado. O token ja diz quais apps a conta
tem, e o workflow escolhe nesta ordem:

1. o nome digitado no campo **app** do Run workflow;
2. o secret `HEROKU_APP_NAME`, se existir;
3. o unico app da conta, quando so ha um;
4. o app que tem exatamente o nome do repositorio.

So quando nada disso resolve ele para, em segundos, listando as opcoes. Na
pratica: pelo celular e so **Run**, sem preencher nada.

Para exigir aprovacao humana antes de cada deploy, crie um Environment
chamado `production` (Settings > Environments) com required reviewers e
acrescente `environment: production` ao job em
`.github/workflows/deploy.yml`.

## Quando producao tem commit que o repositorio nao tem

Acontece quando alguem publica uma branch direto no Heroku sem passar pelo
GitHub. O deploy detecta e **se recusa a publicar**:

```
O Heroku tem commit que este ref nao tem. Traga producao para o ref antes de publicar:
```

A recusa e proposital: o push e sem `--force`, entao publicar por cima
apagaria do ar um codigo que nao existe em outro lugar. O conserto e trazer
producao para o repositorio, nunca forcar.

Pelo celular, use o workflow **Sincronizar producao (Heroku -> GitHub)**: ele
copia a `main` do Heroku para uma branch nova (`producao/heroku-main-<data>`)
sem mesclar nada. Abra um Pull Request dessa branch para a `main`, confira o
que veio e faca o merge. Depois disso o deploy volta a funcionar.

Pelo computador, o equivalente e:

```bash
git fetch heroku
git checkout main
git merge heroku/main
git push origin main
```

## Por que existe um preflight

O `Procfile` declara:

```
release: flask db upgrade
```

Se esse comando falhar, o release inteiro aborta: o dyno antigo continua de pé
e o novo se recusa a subir. O erro aparece no meio do deploy, não antes dele.

O preflight roda essas mesmas verificações localmente, em segundos:

```bash
python scripts/preflight_deploy.py
```

| Checagem   | O que pega                                                                 |
|------------|---------------------------------------------------------------------------|
| `heads`    | duas cabeças do Alembic → `Multiple head revisions are present`            |
| `chain`    | `down_revision` apontando para migration que não existe, id repetido       |
| `pending`  | quais migrations o release vai aplicar (opcional, veja abaixo)             |
| `imports`  | `create_app()` falhando → release passa e o web dyno morre em loop no boot |
| `procfile` | `release` e `web` continuam declarados                                     |

Saída `0` = pode publicar.

### A falha mais comum: duas cabeças

Não vem de erro de digitação. Acontece sozinha sempre que duas branches criam
migration a partir da mesma revisão — cada uma grava o mesmo `down_revision` e
o histórico bifurca. Conserto:

```bash
python scripts/preflight_deploy.py --check heads
```

A saída mostra as cabeças e o pai de cada uma. Escolha qual migration vem
depois e aponte o `down_revision` dela para a outra cabeça.

Isso também é testado em [tests/test_migrations_integrity.py](tests/test_migrations_integrity.py),
então um merge que reintroduza a bifurcação falha na suíte antes de chegar no push.

### Checando contra o banco real

Para ver exatamente o que o release vai aplicar, aponte para uma **cópia
restaurada** do banco de produção — nunca para a produção:

```bash
PREFLIGHT_DATABASE_URL=postgresql://... python scripts/preflight_deploy.py --check pending
```

Sem essa variável, `pending` é pulado.

## O que o preflight não cobre

O histórico de migrations **não é replayável do zero**: a migration inicial já
assume tabelas anteriores à adoção do Alembic, e um `upgrade` num banco vazio
falha com `NoSuchTableError`. O banco de produção foi construído
incrementalmente e está correto — mas isso significa que não dá para validar a
cadeia inteira criando um banco novo. A suíte de testes usa `db.create_all()` a
partir dos models, não as migrations, pelo mesmo motivo.

Consequência prática: uma migration nova só é validada de verdade contra uma
cópia do banco real (`pending`, acima). Se um dia valer a pena, o conserto é
colapsar o histórico antigo numa migration-base gerada do esquema atual.

## Se o deploy falhar mesmo assim

```bash
powershell -File scripts/heroku.cmd releases
```

```bash
powershell -File scripts/heroku.cmd logs --tail
```

O `scripts/heroku.cmd` existe porque a instalação oficial também coloca um
script POSIX sem extensão no PATH, e o PowerShell escolhe ele antes de um
comando Windows utilizável nesta máquina.
