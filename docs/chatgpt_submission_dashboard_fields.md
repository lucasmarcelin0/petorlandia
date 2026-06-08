# Campos para submissao publica do ChatGPT

Use estes valores no Platform Dashboard para enviar o PetOrlandia para revisao.

## App info

- Display name: `PetOrlandia`
- Subtitle: `Gestao veterinaria`
- Category: `PRODUCTIVITY`
- Company URL: `https://www.petorlandia.com.br/`
- Privacy policy URL: `https://www.petorlandia.com.br/privacy`
- Support URL: `https://www.petorlandia.com.br/support`
- Terms of Service URL: `https://www.petorlandia.com.br/terms`
- App icon: `https://www.petorlandia.com.br/static/chatgpt_app_icon.png`
- Submission import file: `chatgpt-app-submission.json`

## MCP server

- MCP Server URL: `https://www.petorlandia.com.br/mcp`
- Template MCP Server URL: deixe em branco, pois o PetOrlandia usa endpoint universal.
- Authentication: OAuth
- Authorization URL: `https://www.petorlandia.com.br/oauth/authorize`
- Token URL: `https://www.petorlandia.com.br/oauth/token`
- Token endpoint auth method: `client_secret_post`

## Escopos

```text
openid profile email pets:read appointments:read appointments:write clinical_summary:read consultations:read consultations:write prescriptions:read exams:read exams:write vaccines:read handoff:read tutor_guidance:generate tutors:write pets:write
```

## Dados de revisao

- Use uma conta demonstrativa veterinaria, sem MFA e sem dados reais de clientes.
- Teste prompts e respostas do arquivo `chatgpt-app-submission.json`.
- Confirme no Developer Mode que o login OAuth e o widget de laudo carregam no dominio de producao antes de enviar.
