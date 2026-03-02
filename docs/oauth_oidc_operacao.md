# OAuth 2.1 / OpenID Connect — Contrato Operacional

## Endpoints oficiais

Assumindo `ISSUER=https://<dominio-publico>`:

- Authorize: `GET/POST {ISSUER}/oauth/authorize`
- Token: `POST {ISSUER}/oauth/token`
- JWKS: `GET {ISSUER}/.well-known/jwks.json`
- UserInfo: `GET {ISSUER}/oauth/userinfo`
- OpenID Configuration: `GET {ISSUER}/.well-known/openid-configuration`
- Revogação: `POST {ISSUER}/oauth/revoke`
- Introspecção: `POST {ISSUER}/oauth/introspect`

## Escopos suportados

- `openid`
- `profile`
- `email`
- `pets:read`
- `appointments:read`

> Observação: o servidor exige consentimento explícito por escopo no fluxo de autorização.

## Exemplo de URL de autorização (Authorization Code + PKCE)

```text
GET https://<dominio-publico>/oauth/authorize?
  response_type=code&
  client_id=petorlandia-web&
  redirect_uri=https%3A%2F%2Fclient.example%2Foauth%2Fcallback&
  scope=openid%20profile%20email&
  state=af0ifjsldkj&
  nonce=n-0S6_WzA2Mj&
  code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&
  code_challenge_method=S256
```

## Exemplo de troca de `code` por token

```bash
curl -X POST "https://<dominio-publico>/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=<authorization_code>" \
  --data-urlencode "client_id=petorlandia-web" \
  --data-urlencode "redirect_uri=https://client.example/oauth/callback" \
  --data-urlencode "code_verifier=<pkce_code_verifier>"
```

Resposta esperada (resumo):

```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 900,
  "scope": "openid profile email",
  "id_token": "...",
  "refresh_token": "..."
}
```

## Política de refresh e revogação

- Refresh token com **rotação obrigatória** a cada uso (`grant_type=refresh_token`).
- Em reutilização de refresh token revogado/expirado, a família inteira é revogada.
- Revogação de access token em `/oauth/revoke` também revoga a família de refresh associada.
- Introspecção em `/oauth/introspect` retorna `active=false` para tokens inválidos, expirados ou revogados.

## Checklist de ambiente (produção)

- [ ] `PREFERRED_URL_SCHEME=https`
- [ ] Domínio público estável e resolvível (sem URLs efêmeras).
- [ ] `SECRET_KEY` fixa, forte, com rotação controlada.
- [ ] Chaves de assinatura (JWK) provisionadas e armazenadas com segurança.
- [ ] Endpoint `/.well-known/openid-configuration` acessível externamente.
- [ ] Endpoint `/.well-known/jwks.json` servindo chave(s) pública(s) ativas.
