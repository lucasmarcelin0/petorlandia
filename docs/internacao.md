# Internação veterinária

O módulo organiza o prontuário hospitalar por clínica, com admissão, prescrição,
mapa de medicações, execução, evolução, passagem de plantão, impressão e alta.
O acompanhamento domiciliar do tutor continua com seu fluxo próprio.

## Acessos e rotina

- Na página inicial, abrir **Internação → Pacientes e medicações do plantão**.
- Na consulta do animal, usar **Internar / abrir internação**. Os dados do animal
  e da consulta são reaproveitados; uma internação ativa é aberta diretamente.
- Na admissão, conferir a clínica, selecionar animal e veterinário responsável,
  informar motivo, local/leito, peso aferido na admissão, alergias e observações.
- Publicar os itens da prescrição depois de conferir quantidade com unidade,
  via, período e prévia dos horários. A ação exige veterinário habilitado.
- A equipe registra cada administração no momento da execução. O sistema grava
  o usuário e o horário do servidor, preservando o horário previsto.
- Registrar evoluções e passagem de plantão na ficha, com resumo e pendências.
- Imprimir a prescrição vigente, o mapa ou o prontuário pelo período escolhido.
- O veterinário registra a alta; o histórico permanece acessível no painel pelo
  filtro de altas. A programação pendente é encerrada.

O prontuário interno fica disponível à equipe regular, ao responsável pela clínica
e aos veterinários autorizados. Prescrever, revisar, suspender, retificar e dar
alta exigem perfil veterinário com CRMV, acesso ativo e vínculo local. Tutores,
links compartilhados com o tutor e contas de estágio não recebem esse acesso.
Cada funcionário deve usar sua própria conta para atribuição correta da autoria.

## Prescrição e horários

As frequências são estruturadas: intervalo em horas, horários fixos, dose única
ou uso se necessário. O fim é explícito e exclusivo: não há dose programada no
instante final, nem administração permitida fora da vigência.

O piloto aceita até 31 dias e 1.000 ocorrências por item. Uma agenda que exceda
esses limites gera erro visível, sem truncar horários. O prescritor pode planejar
um novo período por revisão. Não há cálculo automático de dose/infusão.

Uma alteração cria nova versão, com motivo e início de vigência. Execuções e
versões anteriores ficam preservadas. Atrasar uma aplicação não desloca as
seguintes; reprogramação exige revisão explícita do veterinário. Uma revisão com
início futuro mantém a versão anterior vigente até o corte. Suspender um item
também suspende suas revisões futuras vinculadas.

Uso se necessário exige indicação, intervalo mínimo e máximo de doses em 24h
prescritos pelo veterinário. Os limites consideram os registros e as revisões
do mesmo item; uma nova versão não zera o histórico de administração.

## Execução e correções

Conferir paciente, item, quantidade, unidade, via e horário antes de confirmar.
Uma checagem imediata registra o momento da confirmação no sistema. Lançamento
posterior exige horário de execução informado e justificativa; mostra os dois
horários. Antecipação e não administração também exigem motivo.

O sistema protege contra reenvio e checagem concorrente da mesma ocorrência.
Falha de conexão não é sucesso: conferir o estado no servidor antes de repetir.
O módulo opera online e não usa a fila offline genérica de formulários.

O veterinário pode acrescentar uma retificação com motivo, preservando o registro
original. Uma retificação não apaga a autoria anterior. Após alta, lançamento
histórico exige veterinário autorizado, horário anterior à alta e justificativa;
não reabre a internação nem a agenda futura.

## Documentos

**Prescrição** mostra os itens vigentes e os programados, identificando o início
futuro explicitamente. **Mapa** mostra
horários previstos, estados e registros. **Prontuário** inclui evolução e histórico
do período. Retificações vinculadas continuam presentes mesmo quando lançadas
após a alta ou após o período clínico selecionado.

Os documentos usam A4, cabeçalhos com identificação, emissão e horário de Brasília.
Usar a impressão do navegador para imprimir ou salvar PDF. A receita para casa
deve ser revisada pelo veterinário usando o recurso de receitas existente.

## Homologação e validação técnica

Antes de ampliar o uso, conferir o fluxo com veterinário e plantonista, primeiro
em casos simulados e depois em um plantão acompanhado. Validar os formulários e
documentos da clínica, a troca de turno e o procedimento para indisponibilidade
de internet. A combinação de papel e sistema precisa de uma rotina acordada.

Os testes de `tests/test_internacao.py` cobrem agenda, autoria, histórico,
idempotência, vigência, PRN, alta, isolamento, integração HTTP e impressão.
`tests/test_internacao_access.py` cobre a matriz de permissões. As simulações
SQLite de reenvio e estado desatualizado não substituem testes de concorrência
do PostgreSQL em homologação; em produção, as mutações usam travas transacionais,
atualização condicional e restrições no banco.

As novas tabelas usam a migração `a26c1022b001`. Seguir `DEPLOY.md` para publicar;
testes e migrações devem usar banco de teste ou cópia restaurada, nunca o banco
real. Um rollback operacional deve preservar as tabelas e o histórico hospitalar;
o arquivo da migração também deve permanecer no histórico do Alembic. Reverter
funcionalidades não significa remover a revisão já aplicada do banco. O downgrade
da migração remove as novas tabelas e não deve ser usado com registros
reais sem uma estratégia específica de preservação dos dados.
