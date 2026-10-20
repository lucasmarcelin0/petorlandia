# Runbook de produção

## Variáveis obrigatórias

- `SECRET_KEY`: valor aleatório estável;
- `DATABASE_URL`: PostgreSQL de produção;
- `MERCADOPAGO_WEBHOOK_SECRET`: segredo real para validar webhooks;
- `MERCADOPAGO_ACCESS_TOKEN`: credencial da conta da plataforma que cria as
  assinaturas profissionais;
- `MERCADOPAGO_NOTIFICATION_URL=https://www.petorlandia.com.br/notificacoes`;
- `INSURER_PORTAL_TOKEN`: segredo fornecido pela seguradora; sem ele, a API de
  seguradora permanece desativada por segurança;
- `RATELIMIT_STORAGE_URI`: `redis://...` quando houver mais de um worker;
- `RATELIMIT_ENABLED=true`;
- `ALLOW_LOCAL_UPLOAD_FALLBACK=false`;
- `FORCE_HTTPS=true`.

## Assinatura profissional (Mercado Pago)

No painel do Mercado Pago, cadastrar
`https://www.petorlandia.com.br/notificacoes` e habilitar os eventos de
pagamento, preapproval de assinatura e pagamento autorizado da assinatura.
O endpoint sempre consulta o recurso no Mercado Pago antes de alterar o banco;
o corpo recebido no webhook não é tratado como fonte autoritativa.

O release deve executar `flask db upgrade` antes de iniciar os dynos. Depois do
deploy, confirmar que o banco está no único head exibido por `flask db heads` e
executar uma reconciliação manual:

```text
flask reconcile-veterinarian-billing --limit 250
```

O scheduler também reconcilia automaticamente a cada 30 minutos. Os controles
podem ser ajustados com
`VETERINARIAN_BILLING_RECONCILIATION_ENABLED=true`,
`VETERINARIAN_BILLING_RECONCILIATION_MINUTES=30` e
`VETERINARIAN_BILLING_RECONCILIATION_LIMIT=250`.

Monitorar e alertar para ocorrências de `billing sync failed`,
`billing persistence failed`, `Falha na reconciliação de cobranças` e para
qualquer execução com `failed` maior que zero. A primeira verificação após o
deploy deve cobrir: criação do checkout, retomada do mesmo checkout pendente,
autorização do meio de pagamento e uma cobrança aprovada sem duplicação de
acesso.

## Sessões e capacidade do dyno

O web dyno usa um worker `gthread` com quatro threads e o pool PostgreSQL é
limitado por configuração. Arquivos estáticos são servidos pelo WhiteNoise sem
abrir sessão ou conexão com o banco.

Para sessões resilientes a deploys e independentes do PostgreSQL, provisionar
Redis e definir `REDIS_URL` e `SESSION_TYPE=redis`. Enquanto Redis não estiver
provisionado, `SESSION_TYPE=sqlalchemy` permanece compatível, mas consome banco
em toda requisição que usa sessão. Ajustar `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`DB_POOL_TIMEOUT_SECONDS` e `DB_CONNECT_TIMEOUT_SECONDS` somente após observar
uso e limites do plano PostgreSQL.

## Agendador: dyno próprio ou dentro do web

Os jobs do `scheduler.py` podem rodar de dois jeitos, com exatamente o mesmo
conjunto de jobs e horários:

- **Dyno próprio (padrão):** `scheduler=1` na formação, `SCHEDULER_IN_WEB`
  ausente. Custa um dyno Basic a mais (~US$ 7/mês).
- **Dentro do web:** `SCHEDULER_IN_WEB=1` e `scheduler=0`. O `gunicorn.conf.py`
  inicia os jobs numa thread do worker web. Economiza o dyno; em troca o web
  divide memória (512 MB) e CPU com os jobs.

Nunca deixe os dois ligados ao mesmo tempo, senão os jobs rodam em dobro.

Para passar para dentro do web: `heroku ps:scale scheduler=0` e depois
`heroku config:set SCHEDULER_IN_WEB=1` (reinicia o web). Conferir no log a
linha `[Scheduler] Rodando dentro do processo web` e, nos dias seguintes, a
memória (Metrics) e os H12. Para voltar: `heroku config:unset SCHEDULER_IN_WEB`
e `heroku ps:scale scheduler=1`. Não precisa de deploy em nenhum sentido.

`ENABLE_WEB_SCHEDULER=1` é o modo antigo, só para dev local; com ele ligado o
`SCHEDULER_IN_WEB` é ignorado.

## Verificações pós-deploy

```text
GET /live  -> 200 {"status":"ok"}
GET /ready -> 200 {"status":"ready"}
OPTIONS /mcp/v2 com Origin https://chatgpt.com -> CORS correto
```

Verificar também HSTS, CSP, cookies `Secure`/`HttpOnly`, webhook Mercado Pago,
fila de lembretes e presença de backup recente.

## Recuperação

Manter backup diário/PITR, registrar RPO/RTO e executar restauração trimestral
em ambiente isolado. Nunca restaurar sobre produção sem janela aprovada.
