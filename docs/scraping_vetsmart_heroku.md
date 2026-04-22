# Scraping VetSmart no Heroku

Como rodar o `scripts/importar_medicamentos_vetsmart.py` num one-off dyno do Heroku
para importar todos os ~6000 produtos do VetSmart no banco de produção.

## Visão geral

O scraping completo leva ~11 horas. Para isso funcionar no Heroku:

1. **Playwright** precisa estar instalado **e** o Chromium precisa estar disponível
   no slug. Não dá só para `pip install playwright` — o binário do navegador é
   baixado por um buildpack próprio.
2. **Filesystem efêmero**: arquivos criados no dyno desaparecem quando ele
   reinicia. Por isso o modo `--scrape-importar` grava direto no Postgres
   (commit a cada 25 produtos), sem usar o cache em disco.
3. **One-off detached**: o comando precisa rodar em background pra você poder
   fechar o terminal. O dyno fica vivo até o script terminar (ou ser morto).

## Setup (uma vez)

### 1. Adicionar o buildpack do Playwright

```bash
heroku buildpacks:add --index 1 https://github.com/mxschmitt/heroku-playwright-buildpack -a petorlandia
heroku config:set PLAYWRIGHT_BUILDPACK_BROWSERS=chromium -a petorlandia
```

> Nota: o buildpack precisa vir **antes** do buildpack de Python (por isso o
> `--index 1`). Confira com `heroku buildpacks -a petorlandia`.

### 2. Garantir que `playwright` está em `requirements.txt`

Já está (`playwright==1.51.0`). Faça deploy normalmente:

```bash
git push heroku main
```

O slug vai ficar maior (~150-200 MB extras pro Chromium), mas continua dentro do
limite de 500 MB do Heroku.

## Rodar o scrape

### Comando principal — scrape + import direto, em background

```bash
heroku run:detached --size=performance-l \
  "python scripts/importar_medicamentos_vetsmart.py --scrape-importar" \
  -a petorlandia
```

**Por quê `performance-l`?** O Chromium consome ~500 MB de RAM. O `standard-1x`
(512 MB) corre risco de OOM-kill. `performance-l` (14 GB) tem folga e o tempo
de wall-clock é ilimitado para `run:detached`.

### Acompanhar o log

```bash
heroku logs --tail --dyno=run -a petorlandia
```

Você vai ver linhas tipo:

```
[1/6056] 4Dx® Plus
    ✓ class='Teste Diagnóstico' pa=None apres=2 doses=0
[2/6056] ACQUA Limp
    ✓ class='Oftálmico' pa='Álcool polivinílico…' apres=1 doses=1
…
  ↳ commit (24 inseridos, 1 pulados, 0 falhas)
```

A cada 25 produtos faz commit no banco — mesmo se o dyno morrer, o que já foi
importado fica.

### Parar o dyno (se precisar)

```bash
heroku ps -a petorlandia                # vê o nome do dyno (ex: run.1234)
heroku ps:stop run.1234 -a petorlandia
```

Da próxima vez que rodar, ele pula automaticamente os produtos cujo nome já
está no banco.

## Modos disponíveis

| Modo | Quando usar |
|---|---|
| `--scrape-importar` | **Heroku/produção** — scrape + INSERT direto no DB, sem cache em disco. Idempotente. |
| `--somente-cache` | Local — só raspa pro arquivo JSON, não toca no DB. |
| `--usar-cache` | Local — importa um cache JSON já existente para o DB. |
| `--resume` | Local — continua um scrape interrompido (lê o cache anterior). |
| `--limite N` | Limita aos N primeiros produtos (útil pra teste). |
| `--dry-run` | Não escreve nada — só simula. |
| `--visible` | Roda navegador visível (debug local). |

## Smoke test antes do scrape completo

```bash
heroku run "python scripts/importar_medicamentos_vetsmart.py --scrape-importar --limite 10" -a petorlandia
```

Vai raspar e importar só os 10 primeiros. Se sair com sucesso, dispare o
detached.

## Custos estimados

- `performance-l` custa ~$1.39/h.
- 11 h × $1.39 = **~$15** pelo scrape inteiro.
- Se você já tem dynos performance ligados, é proporcional ao tempo extra.

Para reduzir custo, dá pra usar `standard-2x` (1 GB RAM, $0.10/h ≈ $1 total),
mas o risco de OOM é maior; comece com `performance-l` e otimize depois.

## Troubleshooting

### "Browser executable not found"
O buildpack do Playwright não baixou o Chromium. Confira:

```bash
heroku buildpacks -a petorlandia
heroku config:get PLAYWRIGHT_BUILDPACK_BROWSERS -a petorlandia
```

E faça um novo `git push heroku main` para reconstruir o slug.

### OOM kill
Aumente o tamanho do dyno (`--size=performance-l` em vez de `performance-m`),
ou abra o navegador com flags pra reduzir memória — edite a chamada
`pw.chromium.launch(...)` para incluir `args=["--disable-dev-shm-usage", "--no-sandbox"]`.

### Slug muito grande (> 500 MB)
Verifique `heroku slugs -a petorlandia`. Se passar, mova o Playwright
para `requirements-dev.txt` e use uma imagem de container em vez de buildpacks
(`heroku stack:set container`).
