# ChatGPT App OAuth Client

Este client permite que o app do ChatGPT acesse o PetOrlandia por OAuth/OIDC e MCP.

## URLs para cadastrar no ChatGPT

Dominio HTTPS estavel do PetOrlandia:

- Authorization URL: `https://www.petorlandia.com.br/oauth/authorize`
- Token URL: `https://www.petorlandia.com.br/oauth/token`
- MCP URL: `https://www.petorlandia.com.br/mcp`
- Token endpoint auth method: `client_secret_post`
- App icon: `https://www.petorlandia.com.br/static/chatgpt_app_icon.png`

## Escopos recomendados

Use todos os escopos abaixo para a primeira versao clinica completa:

```text
openid profile email pets:read appointments:read appointments:write clinical_summary:read consultations:read consultations:write prescriptions:read exams:read exams:write vaccines:read handoff:read tutor_guidance:generate tutors:write pets:write
```

Para uma versao inicial apenas de importacao de laudos, use:

```text
openid profile email tutors:write pets:write exams:write
```

## Primeiro uso em Developer Mode

1. Rode o PetOrlandia localmente.
2. Exponha o servidor com um tunnel HTTPS, por exemplo `ngrok http 5000`.
3. No ChatGPT, ative Developer Mode em **Settings -> Apps & Connectors -> Advanced settings**.
4. Crie um app apontando o MCP URL para `https://<ngrok-ou-dominio>/mcp`.
5. Configure OAuth com as URLs acima.
6. Registre ou atualize o client OAuth no PetOrlandia. O script aceita o callback atual do ChatGPT (`https://chatgpt.com/connector/oauth/*`) e tambem o callback legado `/aip/*/oauth/callback`:

```powershell
python scripts/upsert_chatgpt_oauth_client.py
```

O script cria ou atualiza o client `petorlandia-chatgpt`, preservando o `client_secret` existente. Para gerar outro segredo:

```powershell
python scripts/upsert_chatgpt_oauth_client.py --rotate-secret
```

7. Use no ChatGPT o `client_id` exibido pelo script e o `client_secret` exibido quando o client for criado ou quando voce rodar com `--rotate-secret`.

## Fluxo inicial recomendado

O fluxo inicial pode ser o importador de laudos:

1. O ultrassonografista cola o laudo ou anexa o arquivo no ChatGPT.
2. O ChatGPT chama `abrir_importador_laudo_volante` para revisar os dados visualmente.
3. O usuario confirma a gravacao.
4. O widget chama `importar_laudo_volante` com `confirmar_gravacao: "sim"`.

## Publicacao

Para app publico, use o arquivo `chatgpt-app-submission.json` como base da submissao. Antes de enviar para revisao, confirme:

- o endpoint `/mcp` esta em HTTPS estavel, sem tunnel temporario;
- o dominio pertence a conta/organizacao correta;
- a conta/organizacao esta verificada e o usuario que submete tem permissao de Owner;
- existe URL publica de politica de privacidade em `https://www.petorlandia.com.br/privacy`;
- existe contato publico de suporte em `https://www.petorlandia.com.br/support`, com `SUPPORT_EMAIL` configurado em producao;
- os testes da submissao usam dados demonstrativos, sem dados reais de clientes;
- o OAuth foi testado no ChatGPT Developer Mode com o dominio de producao.

Referencias oficiais consultadas:

- https://developers.openai.com/apps-sdk/quickstart
- https://developers.openai.com/apps-sdk/build/mcp-server
- https://developers.openai.com/apps-sdk/build/chatgpt-ui
- https://developers.openai.com/apps-sdk/plan/tools
- https://developers.openai.com/apps-sdk/reference
- https://developers.openai.com/apps-sdk/deploy
- https://developers.openai.com/apps-sdk/deploy/submission
- https://developers.openai.com/apps-sdk/app-submission-guidelines
