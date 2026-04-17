# Integração Clínica com ChatGPT

Esta documentação descreve a primeira versão operacional da integração clínica do PetOrlândia com o ChatGPT via OAuth/OIDC e MCP.

## Objetivo

Permitir que veterinários usem o ChatGPT como interface operacional segura para:

- consultar resumo clínico do animal;
- listar agenda do dia;
- ver pendências clínicas;
- gerar orientação ao tutor;
- gerar handoff clínico.
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
- `obter_resumo_clinico_animal`
- `listar_agenda_do_dia`
- `listar_pendencias_clinicas`
- `listar_vacinas_pendentes`
- `listar_exames_pendentes`
- `listar_retornos_pendentes`
- `gerar_orientacao_tutor`
- `gerar_handoff_clinico`
- `cadastrar_tutor_e_pets`
- `registrar_consulta_clinica`
- `registrar_bloco_exames`
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

## Exemplos de perguntas que o ChatGPT já consegue responder

- "Resuma o histórico clínico do Thor"
- "Quais pacientes tenho hoje?"
- "Quais retornos estão pendentes?"
- "Mostre vacinas atrasadas da clínica"
- "Gere uma orientação para o tutor da Luna"
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

## Limitações desta versão

- A geração de orientação ao tutor e de handoff é determinística, baseada apenas em dados já salvos no prontuário.
- O diagnóstico ainda é persistido no campo de conduta, prefixado de forma estruturada, porque o domínio atual não possui um campo dedicado.
- Ainda não há escrita por endpoints REST específicos para essas operações; a superfície operacional de escrita está concentrada no MCP.
- A integração prioriza leitura clínica estruturada e geração de rascunhos seguros.
