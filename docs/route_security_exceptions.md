# Exceções permitidas para validação estática de segurança de rotas

Este projeto aplica um gate de CI para **novas rotas sensíveis**. O padrão exigido é:

1. `@login_required` (quando aplicável)
2. chamada de função central de autorização no corpo da view

## Exceções aceitas

As exceções abaixo podem não exigir `login_required`, desde que sigam seu contrato de segurança:

- **Healthcheck** (ex.: `/health`, `/healthz`, `/health/check`)
- **Login / autenticação inicial** (ex.: `/login`, `/oauth/token`)
- **Webhooks públicos** (`/webhook/...`) com **validação de assinatura** obrigatória

> Importante: webhook público sem validação de assinatura **não** deve ser tratado como exceção válida.
