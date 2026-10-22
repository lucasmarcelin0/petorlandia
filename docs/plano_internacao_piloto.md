# Internação veterinária: plano do piloto e sequência de PRs

## Objetivo

Permitir que uma clínica acompanhe pacientes internados, prescreva, consulte os horários e registre as administrações com funcionário e horário automáticos, mantenha o prontuário entre plantões e imprima os documentos. Acesso pela página inicial e pela consulta do animal.

Este documento propõe a implementação; não indica que o módulo já foi entregue. A primeira versão considera uso online em computador e celular/tablet, contas individuais e os recursos atuais do PetOrlândia. Validar a rotina com um veterinário e um plantonista antes de fechar o escopo.

## Base existente e pontos de integração

Inspeção inicial em 22/10/2026, a partir da `main` com o PR #2021 já integrado. O #2021 trata de validações da ficha SINAN; o módulo veterinário usa os pontos abaixo.

| Fonte existente | Uso no plano |
| --- | --- |
| [services/workspaces.py](../services/workspaces.py) e [dashboard_work_areas.html](../templates/components/dashboard_work_areas.html) | Acrescentar acesso profissional à internação na página inicial |
| [consulta_qr.html](../templates/consulta_qr.html) | Ação “Internar animal” ou “Abrir internação”, junto à identificação do paciente |
| [models/consulta.py](../models/consulta.py) | Reaproveitar referências a animal, clínica, consulta, prescrições e os conceitos de horário previsto/realizado e autoria |
| [services/tratamento.py](../services/tratamento.py) | Referência da agenda e do acompanhamento atuais, preservando seu funcionamento |
| [blueprints/consulta.py](../blueprints/consulta.py) | Integração com receitas, impressão e acompanhamento existentes |
| [prescricao_form.html](../templates/partials/prescricao_form.html) | Reutilizar busca e linguagem visual da prescrição, com campos hospitalares estruturados |
| [historico_prescricoes.html](../templates/partials/historico_prescricoes.html) | Reaproveitar a apresentação do histórico e acessos aos documentos |
| [termo_internacao.html](../templates/termos/termo_internacao.html) | Reaproveitar o termo e o padrão visual de impressão |
| [time_utils.py](../time_utils.py) | Usar os utilitários atuais de UTC e apresentação em America/Sao_Paulo |
| [multi_clinic_guide.md](multi_clinic_guide.md) | Preservar o escopo por clínica, inclusive com animais compartilhados |

### Cuidados ao reaproveitar o acompanhamento atual

- `TratamentoAcompanhamento`, `ItemTratamento` e `AdministracaoRegistro` já existem. O fluxo atual atende também o tutor; o prontuário hospitalar deve ter permissões próprias para a equipe. Links e tokens do tutor não concedem acesso ao registro interno.
- A checagem atual permite voltar a “pendente” e limpar dados da realização. A internação precisa de retificação auditável, preservando o registro original.
- A agenda atual interpreta frequência/duração em texto e aplica limites de geração. Na internação, o veterinário confirma frequência estruturada e primeiro horário; texto livre não deve decidir sozinho os horários. O mapa não pode truncar silenciosamente uma internação longa.
- Ativar o acompanhamento atual pode notificar o tutor. Admitir um paciente não deve disparar esse fluxo sem uma decisão explícita de produto.

## Experiência do primeiro piloto

1. **Admissão:** selecionar animal existente ou partir da consulta; registrar motivo, responsável, entrada, local/leito, peso e data de aferição, alergias e alertas. Encontrar a internação ativa em vez de duplicá-la.
2. **Painel:** animais internados, próximas medicações, atrasos e filtros por paciente/local/responsável. Disponibilizar também a lista de medicações de todos os pacientes por horário.
3. **Prescrição:** medicamento/apresentação, quantidade final a administrar e unidade explícitas, dose prescrita quando informada, via, frequência, início, duração/término e instruções. Prévia dos horários antes de publicar. Reaproveitamento de receita anterior sempre como rascunho revisado.
4. **Plantão:** mapa das próximas 24 horas, consulta de outros períodos e ações “Registrar administração”, “Não administrada” e “Registrar administração anterior”. Mostrar identificação do animal, quantidade, unidade e via durante a confirmação.
5. **Prontuário:** evoluções, parâmetros básicos acordados com a clínica, intercorrências, cuidados e passagem de plantão com autor, data/hora e pendências.
6. **Impressão e alta:** prescrição vigente, mapa de administração e prontuário por período; encerramento com resumo, responsável e orientações. Reutilizar a emissão de receita existente para uma receita de alta revisada.

Usar lista cronológica responsiva, identificação persistente do paciente, áreas de toque confortáveis, navegação por teclado e estados descritos por texto e ícone além da cor. Alergia desconhecida deve permanecer distinta de ausência de alergias. Mostrar falha de conexão claramente e sucesso somente após confirmação do servidor.

## Regras essenciais

### Prescrição e agenda

- Somente veterinário autorizado publica ou altera prescrição. Funcionários habilitados consultam e registram execução conforme permissões da clínica; não depender apenas das abas hoje restritas ao veterinário.
- Oferecer intervalo em horas, horários fixos, dose única e “se necessário”. O prescritor confirma primeiro horário, vigência e prévia da agenda.
- Cada ocorrência programada tem identidade e vínculo com a versão que a originou. Publicação e geração inicial são atômicas; ampliar a agenda de forma determinística, sem duplicatas, cobrindo o período consultado/impresso.
- Um atraso não desloca automaticamente as próximas doses. Reprogramar exige ação explícita com prévia e histórico.
- “Se necessário” tem indicação e limites definidos pelo veterinário; não gera doses obrigatórias fictícias. Validar limites prescritos em transação com bloqueio por item, inclusive em dois registros simultâneos.
- Alteração cria nova versão com início de vigência, preservando as realizações e pendências históricas. Cancelar/substituir apenas ocorrências afetadas; pendências anteriores ainda abertas precisam de tratamento explícito.

### Execução, horário e correções

- Na confirmação imediata, o servidor registra horário e usuário autenticado. Exibir separadamente horário previsto e realizado. Isso registra a confirmação do funcionário, sem pressupor detecção automática da aplicação física.
- Para lançamento posterior, guardar horário de realização informado, hora imutável do lançamento, motivo e autor. Rejeitar horário futuro e validar entrada/encerramento e vigência histórica do item; suspensão posterior não deve impedir o lançamento autorizado de uma execução anterior legítima.
- Validar no servidor, na mesma transação, acesso, internação, prescrição aplicável e ocorrência. Aplicar controle de concorrência e idempotência; reenvio e duas checagens simultâneas não criam duas conclusões válidas.
- Se já registrada, mostrar por quem e quando. Administração antecipada deve destacar o desvio e seguir política de confirmação/justificativa validada com a clínica.
- Não administração exige motivo. Correções acrescentam retificação, sem apagar o original. Preservar histórico de autor e horário mesmo quando houver erro de lançamento.
- Alta encerra a agenda futura e mantém o prontuário. Registro retrospectivo após alta usa fluxo autorizado e auditável.
- Usar UTC para novos instantes persistidos e os utilitários do projeto para apresentação no fuso adotado. Horários fixos seguem o horário local; intervalos seguem a regra confirmada pelo prescritor.

### Acesso e documentos

- Validar clínica e relações entre todos os recursos no servidor, inclusive busca, impressão e exportação. Um animal compartilhado não implica compartilhar o prontuário hospitalar entre clínicas.
- Aplicar a regra de uma internação ativa por animal na clínica, inclusive em admissões simultâneas, salvo necessidade explícita validada antes da implementação.
- Prescrição interna, mapa de administração e receita de alta têm finalidades distintas. Não copiar automaticamente o tratamento hospitalar inteiro para uso em casa.
- Impressos devem conter paciente/tutor, clínica, internação, período, responsável, versão, fuso e emissão; repetir identificação nas páginas e distinguir pendência de administração confirmada. A impressão é um retrato da informação naquele momento.

## Arquitetura proposta

Manter Flask, SQLAlchemy e Alembic, componentes e infraestrutura existentes. Criar um domínio hospitalar com tabelas próprias para episódio, prescrição versionada, ocorrências, execuções/retificações e evoluções/passagem de plantão. Referenciar cadastros e receitas existentes; preservar os dados e o comportamento do acompanhamento domiciliar.

Arquivos novos sugeridos: `models/internacao.py`, `services/internacao.py`, `blueprints/internacao.py`, `templates/internacao/` e testes do domínio. Adaptar exports e registro do blueprint às convenções atuais; usar os mecanismos existentes de autorização, CSRF e migrações. Não é necessário introduzir novos serviços externos.

Separar a regra de agenda/execução da interface e dos documentos. Reutilizar componentes de receita e os utilitários de horário; compartilhar lógica de agenda apenas quando as regras hospitalares forem compatíveis. Atualizar a tela pelo mecanismo existente ou consulta periódica leve; a consistência entre funcionários depende das transações no servidor.

Para impressão do mapa/prontuário, começar com HTML e CSS A4, com “Imprimir / salvar PDF”; aproveitar a emissão de PDF já disponível para receitas. Validar páginas longas, preto e branco e os documentos realmente usados pela clínica.

## Sequência de PRs propostos

| PR | Escopo e resultado revisável | Validação principal |
| --- | --- | --- |
| 1. Admissão e navegação | Migrações, permissões, episódio de internação, painel e acessos pela home/consulta | Isolamento por clínica, perfis da equipe, admissões simultâneas e migrações |
| 2. Prescrição e mapa | Itens estruturados, versões, prévia, agenda, execução, exceções e retificações | Horários, virada de dia, vigência, concorrência, idempotência, histórico e “se necessário” |
| 3. Prontuário e plantão | Evoluções, parâmetros básicos, intercorrências, cuidados e passagem de plantão | Autoria, consulta de histórico, permissões e jornada responsiva |
| 4. Documentos e alta | Impressão A4/PDF, integração à receita existente, alta e liberação para a clínica piloto | Documentos de várias páginas, encerramento da agenda e jornada completa |

Os PRs de implementação são sequenciais e pequenos o suficiente para revisão; o fluxo completo deve ficar restrito ao piloto até todos os critérios críticos passarem. Este PR de documentação não publica código nem habilita internação em produção.

Faixa de planejamento: **10–15 dias úteis de desenvolvimento**, com uma pessoa full stack familiarizada com o projeto e apoio parcial de design/qualidade, mais **3–5 dias de piloto acompanhado**. Confirmar após mapear migrações, permissões e rotina. A validação inicial deve ser curta; demonstrar a primeira jornada completa na primeira semana.

Seguir [AGENTS.md](../AGENTS.md) nos pedidos futuros de implementação/publicação e usar apenas banco de teste. Atualizar [route_security_checklist.md](route_security_checklist.md) e o contrato de rotas quando aplicável. Não inserir marcador de publicação nem habilitar auto-merge neste PR de plano.

## Critérios que bloqueiam o piloto

- Admissão pelos dois acessos, sem recadastrar o animal ou criar internações ativas duplicadas por concorrência.
- Agenda correta para intervalo, horários fixos e dose única, inclusive virada de dia e períodos longos; uso “se necessário” validado separadamente.
- Dose prevista às 08h e registrada às 08h17 conserva os dois horários e o funcionário; a próxima dose mantém a programação.
- Duas checagens simultâneas e reenvio após falha de rede geram uma única conclusão válida; aplicar o mesmo cuidado aos limites de usos “se necessário”.
- Suspensão/alteração invalida as ocorrências afetadas em telas antigas, preserva versões e mantém acessíveis execuções e retificações.
- Registro retrospectivo distingue o horário informado do lançamento e valida a vigência histórica. Não administração exige motivo.
- Funcionário autorizado registra a execução; perfil sem permissão não prescreve. Outro estabelecimento e links do tutor não acessam o prontuário interno.
- Falha de conexão não aparece como sucesso. O módulo de internação não herda silenciosamente a fila offline genérica de formulários.
- Alta encerra a agenda futura sem apagar o prontuário. Receita de alta passa por revisão do veterinário.
- Impressão de várias páginas mantém identificação, horários, autoria, versão e estados corretos.
- Veterinário e plantonista concluem admissão → prescrição → administração → passagem de plantão → impressão → alta com casos simulados.
- Fluxos existentes de consulta, receita e acompanhamento domiciliar continuam funcionando.

Priorizar testes de domínio, transações e acesso, além de uma jornada integrada e revisão visual de impressão. O CI e a homologação do módulo pertencem aos PRs de implementação; a existência deste plano não representa evidência de testes clínicos ou de software executados.

## Piloto e evolução

Antes de implementar, confirmar os formulários usados hoje, dispositivos/conectividade, responsáveis por cada ação, frequências prescritas, parâmetros acompanhados e impressos necessários. Validar se cuidados recorrentes ou registro de fluidoterapia impedem o primeiro teste; cálculo de dose/infusão exige detalhamento próprio.

Começar com casos simulados e acompanhar um plantão real e uma troca de turno. Acordar como conciliar papel e sistema durante a transição. Liberar por clínica, com possibilidade de suspender novas operações preservando leitura e impressão do histórico.

Após o piloto, priorizar pelo uso observado: modelos revisados, grade de horários, cuidados recorrentes, balanço hídrico, anexos/exames, estoque/faturamento, comunicação com tutor e funcionamento offline. Evitar ampliar essas integrações antes de validar o fluxo principal.
