# Runbook de produção

## Variáveis obrigatórias

- `SECRET_KEY`: valor aleatório estável;
- `DATABASE_URL`: PostgreSQL de produção;
- `MERCADOPAGO_WEBHOOK_SECRET`: segredo real para validar webhooks;
- `INSURER_PORTAL_TOKEN`: segredo fornecido pela seguradora; sem ele, a API de
  seguradora permanece desativada por segurança;
- `RATELIMIT_STORAGE_URI`: `redis://...` quando houver mais de um worker;
- `RATELIMIT_ENABLED=true`;
- `ALLOW_LOCAL_UPLOAD_FALLBACK=false`;
- `FORCE_HTTPS=true`.

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
