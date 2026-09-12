# Deploy no Heroku

## O caminho normal

```bash
powershell -File scripts/deploy_heroku.ps1
```

É isso. O script faz, nesta ordem, e para no primeiro problema:

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

## Pelo GitHub Actions (sem depender da sua maquina)

O caminho acima precisa do remoto `heroku` configurado no computador de quem
publica. Quando isso nao existe -- outra maquina, outra pessoa, um agente --
use o workflow **Deploy (Heroku)**, em Actions > Deploy (Heroku) > Run
workflow. Ele pede o `ref` a publicar (padrao `main`), o `app` (vazio =
descobre sozinho) e se deve rodar a suite antes (padrao sim). Funciona pelo
app do GitHub no celular.

O workflow faz, na ordem, as mesmas travas do script manual:

1. preflight (`scripts/preflight_deploy.py`);
2. suite completa, com os mesmos comandos do workflow de testes;
3. guarda de artefatos sensiveis;
4. push **sem `--force`**, recusando publicar se o Heroku tem commit que o ref
   nao tem;
5. espera o release phase terminar (`scripts/wait_heroku_release.py`) e falha
   com o log quando o `flask db upgrade` quebra.

### Configuracao (uma vez)

Em Settings > Secrets and variables > Actions, crie **um** secret:

| Secret | Valor |
|---|---|
| `HEROKU_API_KEY` | token da conta -- gere um com prazo: `heroku authorizations:create -d "GitHub Actions deploy" -e 2592000` |

Prefira o token com prazo ao permanente: se vazar, ele expira sozinho. Para
revogar, `heroku authorizations` e `heroku authorizations:revoke <id>`.

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
