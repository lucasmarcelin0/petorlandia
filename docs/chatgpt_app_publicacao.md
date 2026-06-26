# PetOrlandia no ChatGPT

Status desta versao: app MCP com OAuth/OIDC, tools clinicas, widget de revisao de laudo volante e pacote inicial de submissao publica.

## Arquitetura escolhida

- Arquitetura: `submission-ready` com MCP server existente em Flask.
- Endpoint principal: `/mcp`.
- Autenticacao: OAuth/OIDC do proprio PetOrlandia.
- UI Apps SDK: widget HTML em `ui://petorlandia/laudo-volante-v2.html`.
- App icon sugerido: `static/chatgpt_app_icon.png`.
- Arquivo de submissao: `chatgpt-app-submission.json`.

## Tools disponiveis

- `listar_meus_pets`
- `listar_agendamentos`
- `interpretar_mensagem_livre_atendimento`
- `assistente_operacional_veterinario`
- `cadastrar_tutor_e_pets`
- `registrar_consulta_clinica`
- `registrar_bloco_exames`
- `abrir_importador_laudo_volante`
- `importar_laudo_volante`
- `agendar_consulta`
- `agendar_retorno`
- `obter_resumo_clinico_animal`
- `listar_agenda_do_dia`
- `listar_pendencias_clinicas`
- `listar_vacinas_pendentes`
- `listar_exames_pendentes`
- `listar_retornos_pendentes`
- `gerar_orientacao_tutor`
- `gerar_handoff_clinico`

Todas as tools agora recebem hints explicitos (`readOnlyHint`, `destructiveHint`, `openWorldHint`), `outputSchema` e security schemes OAuth quando aplicavel.

## Arquivos no ChatGPT

- Para anexos de PDF no ChatGPT atual, use `arquivo_pdf` ou `laudo_arquivo` como file reference com `download_url` e `file_id`.
- `attachment_id` permanece apenas como compatibilidade legada e nao deve ser o `fileParam` principal.
- Caminhos locais do sandbox, como `/mnt/data/...`, nao devem ser enviados ao PetOrlandia.

## Developer Mode

1. Suba o backend:

```powershell
python run_production.py
```

2. Exponha via HTTPS para desenvolvimento local:

```powershell
ngrok http 5000
```

3. No ChatGPT, ative Developer Mode:

```text
Settings -> Apps & Connectors -> Advanced settings -> Developer Mode
```

4. Crie o app apontando para o tunnel local ou para o dominio de producao:

```text
https://www.petorlandia.com.br/mcp
```

5. Configure OAuth:

```text
Authorization URL: https://www.petorlandia.com.br/oauth/authorize
Token URL: https://www.petorlandia.com.br/oauth/token
Token endpoint auth method: client_secret_post
```

6. Rode o script de client OAuth no banco de producao. Ele registra o callback atual do ChatGPT (`https://chatgpt.com/connector/oauth/*`) e mantem compatibilidade com o callback legado (`/aip/*/oauth/callback`):

```powershell
python scripts/upsert_chatgpt_oauth_client.py
```

7. Use no ChatGPT o `client_id` exibido pelo script (`petorlandia-chatgpt` por padrao) e o `client_secret` exibido quando o client for criado ou quando voce rodar com `--rotate-secret`.

8. Depois de alterar descriptors, widget ou scopes, atualize/reconecte o app no ChatGPT para recarregar metadados.

## Producao publica

Antes de submeter para o publico:

- Hospede o PetOrlandia em HTTPS estavel.
- Confirme que `/mcp`, `/.well-known/oauth-protected-resource`, `/.well-known/openid-configuration`, `/oauth/authorize`, `/oauth/token` e `/oauth/userinfo` respondem no dominio final.
- Configure logs para chamadas MCP, latencia, erros OAuth e falhas de tool.
- Use secrets fora do repositorio.
- Confirme que o client OAuth `petorlandia-chatgpt` inclui `openid profile email` e os escopos clinicos (`pets:read`, `exams:read`, `exams:write`, etc.).
- Publique e revise a politica de privacidade em `https://www.petorlandia.com.br/privacy`.
- Publique o contato de suporte em `https://www.petorlandia.com.br/support` e defina `SUPPORT_EMAIL` antes da submissao.
- Prepare usuario e dados demonstrativos para revisao, sem dados reais de clientes.
- Verifique ownership do dominio e permissao de Owner na conta/organizacao que fara a submissao.

## Materiais de submissao

- Display name: `PetOrlandia`
- Subtitle: `Gestao veterinaria`
- Categoria: `PRODUCTIVITY`
- MCP URL: `https://www.petorlandia.com.br/mcp`
- Icone: `https://www.petorlandia.com.br/static/chatgpt_app_icon.png`
- Company URL: `https://www.petorlandia.com.br/`
- Privacy policy URL: `https://www.petorlandia.com.br/privacy`
- Support URL: `https://www.petorlandia.com.br/support`
- Terms of Service URL: `https://www.petorlandia.com.br/terms`
- Demo Recording URL: `https://www.petorlandia.com.br/static/chatgpt_app_demo.mp4`
- Import JSON: `chatgpt-app-submission.json`

## Riscos antes da revisao publica

- Dados clinicos e dados de tutores sao sensiveis; a politica de privacidade precisa explicar uso, retencao e autorizacao.
- Tools de escrita exigem `confirmar_gravacao`, mas a revisao deve testar que o ChatGPT pede confirmacao antes de gravar.
- O contrato OAuth precisa ser testado com callback real do ChatGPT em producao.
- Os testes OAuth legados do repositorio ainda precisam ser alinhados ao desafio PKCE usado nos fixtures.

## Referencias oficiais

- https://developers.openai.com/apps-sdk/quickstart
- https://developers.openai.com/apps-sdk/build/mcp-server
- https://developers.openai.com/apps-sdk/build/chatgpt-ui
- https://developers.openai.com/apps-sdk/plan/tools
- https://developers.openai.com/apps-sdk/reference
- https://developers.openai.com/apps-sdk/deploy
- https://developers.openai.com/apps-sdk/deploy/submission
- https://developers.openai.com/apps-sdk/app-submission-guidelines
