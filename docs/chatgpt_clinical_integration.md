# Integração Clínica com ChatGPT

Esta documentação descreve a primeira versão operacional da integração clínica do PetOrlândia com o ChatGPT via OAuth/OIDC e MCP.

## Objetivo

Permitir que veterinários usem o ChatGPT como interface operacional segura para:

- consultar resumo clínico do animal;
- listar agenda do dia;
- ver pendências clínicas;
- gerar orientação ao tutor;
- gerar handoff clínico;
- buscar paciente por nome, tutor, telefone ou email;
- preparar consulta com briefing operacional;
- visualizar timeline clínica consolidada;
- gerar mensagem WhatsApp para o tutor sem envio automático;
- consultar produtos reais da loja;
- criar pedido/carrinho para checkout no PetOrlandia;
- cadastrar tutor e pets;
- registrar dados clínicos essenciais da consulta;
- registrar blocos de exames;
- agendar consultas e retornos.

## Escopos OAuth usados

- `profile`
- `pets:read`
- `appointments:read`
- `appointments:write`
- `clinical_summary:read`
- `consultations:read`
- `consultations:write`
- `prescriptions:read`
- `exams:read`
- `exams:write`
- `vaccines:read`
- `handoff:read`
- `tutor_guidance:generate`
- `tutors:write`
- `pets:write`

Observações:

- Os novos escopos são validados de forma real nos endpoints de integração e nas tools MCP.
- O isolamento por clínica continua sendo aplicado para veterinários e colaboradores.
- Usuários tutores seguem limitados ao próprio escopo de seus animais.

## Endpoints de integração

Todos exigem `Authorization: Bearer <token>`.

- `GET /api/integrations/me`
- `GET /api/integrations/pets`
- `GET /api/integrations/appointments`
- `GET /api/integrations/clinical-summary/<animal_id>`
- `GET /api/integrations/today-agenda`
- `GET /api/integrations/clinical-pendencies`
- `GET /api/integrations/tutor-guidance/<animal_id>`
- `GET /api/integrations/handoff/<animal_id>`

### Parâmetros opcionais

- `date=YYYY-MM-DD` em `today-agenda`
- `consulta_id=<id>` em `tutor-guidance/<animal_id>` e `handoff/<animal_id>`
- `clinica_id=<id>` em endpoints administrativos ou contextos onde o token permita esse recorte

## Tools MCP disponíveis

- `listar_meus_pets`
- `listar_agendamentos`
- `interpretar_mensagem_livre_atendimento`
- `assistente_operacional_veterinario`
- `buscar_produtos_loja`
- `obter_produto_loja`
- `criar_pedido_loja`
- `obter_resumo_clinico_animal`
- `listar_agenda_do_dia`
- `buscar_paciente`
- `obter_timeline_clinica`
- `preparar_consulta`
- `listar_pendencias_clinicas`
- `listar_vacinas_pendentes`
- `listar_exames_pendentes`
- `listar_retornos_pendentes`
- `gerar_orientacao_tutor`
- `gerar_mensagem_whatsapp_tutor`
- `gerar_handoff_clinico`
- `listar_alertas_admin`
- `resolver_alerta_admin`
- `cadastrar_tutor_e_pets`
- `registrar_consulta_clinica`
- `registrar_bloco_exames`
- `abrir_importador_laudo_volante`
- `importar_laudo_volante`
- `agendar_consulta`
- `agendar_retorno`

## Escrita assistida via MCP

As tools de escrita exigem confirmação explícita no payload:

- `confirmar_gravacao: "sim"`

Regras adicionais:

- cadastro de tutor/pets e registros clínicos exigem conta com perfil veterinário;
- ações de escrita respeitam o escopo da clínica do usuário autenticado;
- o ChatGPT não deve inventar dados: ele apenas grava o que for informado ou derivado de campos existentes.

### O que cada tool grava hoje

- `cadastrar_tutor_e_pets`: cria ou reutiliza tutor, cria pets e abre consulta inicial em andamento para cada novo animal.
- `registrar_consulta_clinica`: atualiza ou cria uma consulta clínica com queixa principal, histórico, exame físico, conduta e exames solicitados.
- `registrar_bloco_exames`: cria um bloco estruturado de exames solicitados para o animal.
- `agendar_consulta`: cria agendamento clínico vinculado ao animal e à clínica.
- `agendar_retorno`: agenda retorno a partir de uma consulta já existente.
- `criar_pedido_loja`: cria pedido/carrinho real para o usuário autenticado e retorna link de checkout.
- `resolver_alerta_admin`: marca alerta administrativo como lido ou resolvido, restrito a admins.

## Widgets operacionais no ChatGPT

- `agenda-cockpit-v1`: cockpit da agenda diária com resumo de pendências por paciente.
- `timeline-clinica-v1`: timeline consolidada para atendimento e preparação de consulta.
- `admin-command-center-v1`: central de alertas administrativos acionáveis.
- `laudo-volante-v2`: revisão e gravação assistida de laudos.

As ferramentas de timeline, preparação e central admin retornam `structuredContent` e `_meta.ui` para abrir o widget apropriado no ChatGPT.

## Interpretação de mensagens livres

Para uso mais próximo da rotina real do WhatsApp e de anotações curtas no ChatGPT, a integração também expõe:

- `interpretar_mensagem_livre_atendimento`

Essa tool:

- recebe texto livre ou blocos de conversa;
- extrai dados candidatos como nome, telefone, links de localização e datas;
- devolve um rascunho operacional;
- sugere a próxima action/tool adequada;
- informa quais campos ainda precisam ser confirmados antes de cadastro, consulta ou agendamento.

Ela não grava nada no banco. Serve como camada de preparo antes das tools de escrita.

## Assistente operacional

A tool `assistente_operacional_veterinario` é a primeira camada de orquestração conversacional.

Ela:

- recebe texto natural do veterinário;
- infere a intenção principal, como cadastro, agendamento ou registro de consulta;
- monta argumentos internos compatíveis com as tools operacionais;
- informa o que ainda falta;
- executa a ação quando houver dados suficientes, escopo OAuth compatível e `confirmar_gravacao: "sim"`.

Exemplos de uso:

- `Cadastrar tutor Ligia. Telefone: 16999990000. Endereço: Rua das Flores, 10. Pet: Mel. Espécie: cão.`
- `Agendar consulta para pet Rex em 2026-04-20 às 09:30. Motivo: retorno respiratório.`
- `Registrar consulta do paciente Thor. Queixa: coceira intensa. Diagnóstico: dermatite alérgica. Conduta: banho terapêutico.`

## Exemplos de perguntas que o ChatGPT já consegue responder

- "Resuma o histórico clínico do Thor"
- "Quais pacientes tenho hoje?"
- "O que vocês têm à venda?"
- "Quero comprar ração para cachorro grande"
- "Crie meu pedido com esse produto"
- "Procure o paciente Thor da tutora Lígia"
- "Abra a timeline clínica do Bolt"
- "Prepare a consulta da Luna das 14h"
- "Quais retornos estão pendentes?"
- "Mostre vacinas atrasadas da clínica"
- "Gere uma orientação para o tutor da Luna"
- "Gere uma mensagem de WhatsApp para o tutor da Luna"
- "Quais alertas administrativos estão abertos?"
- "Faça um handoff clínico do paciente Bolt"
- "Cadastre o tutor João com a cadela Mel e deixe uma observação clínica inicial"
- "Registre a consulta clínica do Thor com suspeita de dermatite"
- "Solicite hemograma e bioquímica para a Nina"
- "Agende um retorno do paciente Max para sexta às 14h"

## Regras de segurança

- Veterinários veem apenas dados da clínica à qual estão associados.
- Colaboradores veem apenas dados da própria clínica.
- Tutores veem apenas animais vinculados à própria conta.
- Quando um animal não está dentro do escopo acessível, a integração retorna erro de não encontrado no contexto da integração.

## Importação de laudos com anexos do ChatGPT

A tool `importar_laudo_volante` aceita três caminhos para o laudo, nesta ordem de preferência:

1. `laudo_arquivo`: referência de arquivo autorizada pelo ChatGPT com `download_url`, `file_id`, `mime_type` e `file_name`. O PetOrlândia baixa o arquivo e salva uma cópia em `laudos_exames`.
2. `laudo_texto`: texto integral ou resumo fiel extraído do laudo. Este é o fallback recomendado quando o ChatGPT não conseguir propagar o anexo.
3. `laudo_url`: URL pública `http/https` do arquivo. Caminhos locais do sandbox do ChatGPT, como `/mnt/data/...`, são ignorados e não são persistidos no prontuário.

O painel `abrir_importador_laudo_volante` também expõe seleção/upload de arquivo quando o runtime do ChatGPT disponibilizar `window.openai.selectFiles`, `window.openai.uploadFile` e `window.openai.getFileDownloadUrl`.

## Limitações desta versão

- A geração de orientação ao tutor e de handoff é determinística, baseada apenas em dados já salvos no prontuário.
- O diagnóstico ainda é persistido no campo de conduta, prefixado de forma estruturada, porque o domínio atual não possui um campo dedicado.
- Ainda não há escrita por endpoints REST específicos para essas operações; a superfície operacional de escrita está concentrada no MCP.
- A integração prioriza leitura clínica estruturada e geração de rascunhos seguros.
