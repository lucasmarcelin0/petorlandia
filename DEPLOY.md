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
