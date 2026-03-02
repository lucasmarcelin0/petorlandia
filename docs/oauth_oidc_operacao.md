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

## Erro comum: `PKCE with code_challenge_method=S256 is required.`

Esse erro indica que o cliente tentou iniciar o fluxo Authorization Code sem enviar PKCE obrigatório no padrão exigido pelo servidor.

O PetOrlândia aceita apenas:

- `code_challenge_method=S256`
- `code_challenge` (na chamada `/oauth/authorize`)
- `code_verifier` correspondente (na chamada `/oauth/token`)

### Como corrigir rapidamente

1. Gere um `code_verifier` aleatório (43 a 128 caracteres URL-safe).
2. Calcule o `code_challenge = BASE64URL(SHA256(code_verifier))`.
3. Envie no authorize:
   - `code_challenge=<valor calculado>`
   - `code_challenge_method=S256`
4. Na troca do code por token, envie o mesmo `code_verifier` original.

### Armadilhas mais frequentes

- Não enviar `code_challenge_method` (ou enviar `plain` em vez de `S256`).
- Trocar o `code_verifier` entre authorize e token.
- Fazer URL encoding incorreto do `code_challenge`.
- Cliente OAuth configurado em modo público, mas SDK sem PKCE habilitado.

### Configuração em SDKs (resumo)

- **Auth0 / oidc-client / AppAuth**: habilite explicitamente `usePkce`/`pkce: true`.
- **NextAuth / custom OIDC**: confirme `checks: ["pkce", "state", "nonce"]` quando aplicável.
- **Mobile (Android/iOS)**: use Authorization Code + PKCE, nunca implicit flow.


## Integração com ChatGPT (OAuth pronto para produção)

O PetOrlândia agora aceita dois perfis no Authorization Code:

- **Cliente público**: PKCE obrigatório (`S256`).
- **Cliente confidencial** (ex.: integração do ChatGPT): PKCE opcional, porém autenticação no token endpoint com `client_secret_post` é obrigatória.

### Checklist para cadastrar o cliente do ChatGPT

1. Crie um `OAuthClient` com:
   - `is_confidential=True`
   - `auth_method=client_secret_post`
   - `client_secret` forte
   - `redirect_uris` contendo exatamente o callback configurado no ChatGPT
2. No ChatGPT, configure:
   - Authorization URL: `https://<dominio-publico>/oauth/authorize`
   - Token URL: `https://<dominio-publico>/oauth/token`
   - Client ID/Secret iguais aos do `OAuthClient`
3. Garanta HTTPS público no domínio (`issuer` e redirect precisam ser válidos externamente).

> Se o cliente for público/mobile/web SPA, mantenha PKCE obrigatório como já está implementado.

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
