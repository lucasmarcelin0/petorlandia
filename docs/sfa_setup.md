# Setup do SFA para pesquisa

Este guia organiza o módulo SFA para uso em pesquisa de mestrado com um fluxo mais seguro e previsível.

## 1. O que já existe no projeto

O módulo SFA já inclui:

- tabelas próprias no banco;
- painel operacional em `/sfa/`;
- importação de casos a partir de uma planilha SINAN no Google Sheets;
- redirecionamento do participante para o formulário T0 pré-preenchido;
- webhooks para T0, T10 e T30;
- rotinas de seguimento e priorização operacional.

Arquivos principais:

- [blueprints/sfa.py](C:\Users\lucas\petorlandia\petorlandia\blueprints\sfa.py)
- [services/sfa_service.py](C:\Users\lucas\petorlandia\petorlandia\services\sfa_service.py)
- [models/sfa.py](C:\Users\lucas\petorlandia\petorlandia\models\sfa.py)
- [migrations/versions/a1b2c3d4e5f6_create_sfa_tables.py](C:\Users\lucas\petorlandia\petorlandia\migrations\versions\a1b2c3d4e5f6_create_sfa_tables.py)

## 2. Segurança recomendada para pesquisa

As telas internas do SFA agora ficam fechadas por padrão fora de testes.

Você pode acessar as rotas internas de duas formas:

- fazendo login com um usuário `admin` do sistema;
- usando o cabeçalho `X-SFA-Token` com o valor de `SFA_ADMIN_TOKEN`.

Comportamento importante:

- `/sfa/`, `/sfa/pacientes`, `/sfa/paciente/<id>` e ações operacionais exigem login admin ou token;
- `/sfa/p/<token>` continua público, porque é o link enviado ao participante;
- `/sfa/webhook/t0`, `/sfa/webhook/t10` e `/sfa/webhook/t30` exigem `SFA_WEBHOOK_SECRET` fora de testes.

Para desenvolvimento local temporário, você pode usar:

```env
SFA_ALLOW_OPEN_ACCESS=1
```

Não use isso em produção.

## 3. Variáveis de ambiente

Use [`.env.sfa.example`](C:\Users\lucas\petorlandia\petorlandia\.env.sfa.example) como base.

Campos mais importantes:

```env
SFA_NOME_PESQUISADOR=Seu Nome
SFA_EMAIL_PESQUISADOR=voce@universidade.br

SFA_ADMIN_TOKEN=gere-um-token-longo
SFA_WEBHOOK_SECRET=gere-outro-segredo-longo

SFA_WEBAPP_URL=https://seu-dominio.com

SFA_SHEET_ID_SINAN=...
SFA_FORM_T0_ID=...
SFA_FORM_T10_ID=...
SFA_FORM_T30_ID=...

SFA_ENTRY_T0_ID_ESTUDO=entry.xxxxx
SFA_ENTRY_T0_NOME=entry.xxxxx
SFA_ENTRY_T0_DATA_NASC_BASE=entry.xxxxx
SFA_ENTRY_T10_NOME=entry.xxxxx
SFA_ENTRY_T10_ID_ESTUDO=entry.xxxxx
SFA_ENTRY_T30_NOME=entry.xxxxx
SFA_ENTRY_T30_ID_ESTUDO=entry.xxxxx

SFA_GOOGLE_CREDENTIALS_FILE=C:\caminho\service-account.json
```

## 4. Banco de dados e aplicação

Instale dependências:

```bash
pip install -r requirements.txt
```

Aplique as migrations:

```bash
flask db upgrade
```

Suba a aplicação:

```bash
python run_production.py --host 127.0.0.1 --port 5000
```

## 5. Configuração do Google Sheets

O método de sincronização usa conta de serviço.

Passos:

1. Crie uma service account no Google Cloud.
2. Baixe o JSON de credenciais.
3. Defina `SFA_GOOGLE_CREDENTIALS_FILE` ou `SFA_GOOGLE_CREDENTIALS_JSON`.
4. Compartilhe a planilha do SINAN com o e-mail da service account com permissão de leitura.
5. Copie o ID da planilha para `SFA_SHEET_ID_SINAN`.

Sem isso, `sincronizar_sinan()` não conseguirá importar os casos.

## 6. Configuração dos Google Forms

Você precisa de três formulários:

- T0
- T10
- T30

Defina os IDs dos formulários e os `entry.*` usados no pré-preenchimento.

Observação importante:

- `SFA_ENTRY_T10_ID_ESTUDO` e `SFA_ENTRY_T30_ID_ESTUDO` ainda precisam ser preenchidos manualmente para o link sair completo.

## 7. Webhooks do Apps Script

Os endpoints esperados são:

- `POST /sfa/webhook/t0`
- `POST /sfa/webhook/t10`
- `POST /sfa/webhook/t30`

Envie JSON e inclua o cabeçalho:

```http
X-SFA-Secret: <valor de SFA_WEBHOOK_SECRET>
```

Exemplo de payload mínimo do T0:

```json
{
  "id_estudo": "SFA-001",
  "nome": "Participante Exemplo",
  "data_nascimento": "2000-01-31"
}
```

## 8. Operação diária

Fluxo esperado:

1. Rodar sincronização SINAN.
2. Revisar novos casos no painel.
3. Enviar convites T0 por WhatsApp.
4. Registrar retorno do contato.
5. Rodar a rotina de seguimento para marcar atrasos e fila operacional.

Rotas manuais:

- `POST /sfa/sync`
- `POST /sfa/rotina`

Com token:

```bash
curl -X POST "http://127.0.0.1:5000/sfa/sync" -H "X-SFA-Token: SEU_TOKEN"
curl -X POST "http://127.0.0.1:5000/sfa/rotina" -H "X-SFA-Token: SEU_TOKEN"
```

## 9. Checklist mínimo antes de usar com dados reais

- Banco com migration aplicada
- Usuário admin criado
- `SFA_ADMIN_TOKEN` configurado
- `SFA_WEBHOOK_SECRET` configurado
- `SFA_WEBAPP_URL` apontando para domínio válido
- Service account com acesso à planilha SINAN
- Forms T0/T10/T30 revisados
- Entry IDs conferidos
- Fluxo de teste executado com 1 participante fictício

## 10. Limites atuais do módulo

Pontos que ainda merecem atenção antes de um uso acadêmico mais robusto:

- não há documentação versionada do Apps Script no repositório;
- não há testes automatizados específicos do módulo SFA;
- a rotina diária existe no serviço, mas o agendamento recorrente ainda precisa ser conectado à sua infraestrutura de execução.
