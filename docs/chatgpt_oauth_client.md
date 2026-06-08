# ChatGPT OAuth client

Este client permite que o app/conector do ChatGPT acesse o PetOrlandia sem depender do modo desenvolvedor local.

## Configuracao no ChatGPT

- Authorization URL: `https://<dominio-publico>/oauth/authorize`
- Token URL: `https://<dominio-publico>/oauth/token`
- MCP URL: `https://<dominio-publico>/mcp`
- Token endpoint auth method: `client_secret_post`
- Scopes: `openid profile email tutors:write pets:write exams:write`

## Primeiro uso

O fluxo inicial pode ser tool-only: o ultrassonografista cola o laudo ou passa os dados extraidos, o ChatGPT confirma o minimo necessario e chama `importar_laudo_volante`.

Quando houver dados suficientes para revisao visual, o ChatGPT tambem pode chamar `abrir_importador_laudo_volante`. Essa tool renderiza um widget leve para revisar clinica, tutor, animal, exame, laudo e mensagem para a clinica. O widget so grava quando o usuario confirma, chamando `importar_laudo_volante`.

## Cadastro no PetOrlandia

Use o callback OAuth exato exibido pelo ChatGPT:

```powershell
$env:CHATGPT_OAUTH_REDIRECT_URI="https://callback-exato-informado-pelo-chatgpt"
python scripts/upsert_chatgpt_oauth_client.py
```

O script cria ou atualiza o client `petorlandia-chatgpt-connector`, preservando o `client_secret` existente. Para gerar outro segredo:

```powershell
python scripts/upsert_chatgpt_oauth_client.py --rotate-secret
```

Tambem e possivel sobrescrever os valores por ambiente:

- `CHATGPT_OAUTH_CLIENT_ID`
- `CHATGPT_OAUTH_CLIENT_NAME`
- `CHATGPT_OAUTH_CLIENT_SECRET`
- `CHATGPT_OAUTH_REDIRECT_URI`
- `CHATGPT_OAUTH_SCOPES`
