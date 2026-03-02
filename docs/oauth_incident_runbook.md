# Runbook de Incidentes OAuth/OIDC

## Objetivo

Padronizar resposta operacional para incidentes de credenciais OAuth/OIDC, com foco em:

1. Revogação em massa de tokens.
2. Rotação emergencial de chaves de assinatura (JWK).

## Sinais de incidente

- Detecção de uso indevido de refresh token.
- Exposição potencial de chave privada de assinatura.
- Aumento de `invalid_grant`/`invalid_token` atípico após mudança de deploy.
- Relatos de clientes sobre tokens válidos sendo recusados sem causa aparente.

## Procedimento A — Revogação em massa

1. **Declarar incidente** e congelar mudanças não essenciais.
2. **Identificar escopo** (cliente OAuth específico ou todos).
3. **Revogar tokens**:
   - marcar access tokens e refresh tokens como revogados no banco;
   - para refresh tokens, revogar famílias completas.
4. **Comunicar clientes integradores** para novo login/consentimento.
5. **Monitorar** queda de tráfego com tokens antigos e recuperação de autenticações.
6. **Encerrar incidente** com RCA e ações preventivas.

### SQL de referência (ajustar conforme janela/escopo)

```sql
-- Revogar todos os access tokens ativos
UPDATE oauth_access_token
SET revoked_at = CURRENT_TIMESTAMP
WHERE revoked_at IS NULL;

-- Revogar todos os refresh tokens ativos
UPDATE oauth_refresh_token
SET revoked_at = CURRENT_TIMESTAMP
WHERE revoked_at IS NULL;
```

## Procedimento B — Rotação emergencial de chaves JWK

1. **Gerar novo par de chaves** RSA (privada/pública) em ambiente seguro.
2. **Provisionar nova JWK ativa** no datastore de chaves com novo `kid`.
3. **Publicar JWKS** contendo ao menos a nova chave e, temporariamente, a anterior.
4. **Passar emissão de novos tokens** para o novo `kid`.
5. **Aguardar janela de propagação** e expiração dos tokens antigos.
6. **Remover chave antiga** do conjunto público após a janela segura.
7. **Registrar timeline** e validar clientes que fazem cache agressivo de JWKS.

## Checklist pós-incidente

- [ ] Métricas de emissão/erro normalizadas.
- [ ] Logs de auditoria consolidados.
- [ ] Causa raiz documentada.
- [ ] Ações corretivas com responsáveis e prazo.
- [ ] Simulado de mesa agendado para validar o runbook.
