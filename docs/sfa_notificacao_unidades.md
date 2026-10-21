# Notificação SINAN pelas unidades de saúde

Área em `/sfa/notificacao` para quem preenche a ficha de investigação de dengue
e chikungunya nas unidades. Usa a mesma ficha digital de `/sfa/pre-t0`
(`services/sfa_pre_t0.py`), agora com autor, unidade e a opção de completar depois.

## Acesso

| Quem | O que acessa |
|---|---|
| Administrador | Tudo: cadastra unidades, indica responsáveis, registra por qualquer unidade ativa, vê e completa qualquer ficha |
| Responsável por unidade | Nova ficha em nome da unidade, fichas da própria unidade, panorama. Não vê pacientes nem as demais telas do SFA |
| Token interno do SFA | Nada aqui: toda rota exige conta, porque a ficha fica atribuída a uma pessoa |
| Demais contas | Nenhum acesso (404) |

Ser responsável é um papel **adicional** (`sfa_unidade_responsavel`): não altera
`User.role`. Cada unidade pode ter vários responsáveis (a tela aceita vários
e-mails de uma vez) e uma conta pode responder por mais de uma unidade. Desativar a
unidade suspende o acesso dos responsáveis; as fichas continuam guardadas.

O administrador cuida disso em **Unidades e responsáveis**
(`/sfa/notificacao/unidades`). A pessoa indicada precisa já ter conta no site.

## Fichas da unidade

- A ficha nasce com a unidade fixa (campo 6) e a conta autora. Cria o caso no
  SFA como "aguardando T0", igual à ficha de `/sfa/pre-t0`.
- Quem responde pela mesma unidade **vê** as fichas dela. **Completar depois**
  é do autor (enquanto responde pela unidade) e do administrador.
- Ao completar, o número da ficha e a unidade não mudam. Cada gravação guarda,
  junto da ficha (`formulario_pre_t0.revisoes`), quem alterou, quando, quais
  campos e o conteúdo anterior.
- O cadastro do caso acompanha a correção só onde ainda guardava o que a ficha
  tinha informado; o que a equipe do SFA ajustou à mão não é sobrescrito.

## Campos obrigatórios

Valem para a ficha inteira (`/sfa/pre-t0`, área das unidades e simulações), no
envio e ao completar depois. Ficam em `FIELD_SPECS` (`services/sfa_pre_t0.py`);
a tela marca cada um com "Obrigatório" e não avança a etapa sem eles.

| Campo | Regra |
|---|---|
| Agravo (2), data da notificação (3), primeiros sintomas (7), nome (8) | Sempre (já eram) |
| Data de nascimento (9) | Sempre. Digitar a idade (10) preenche a data estimada |
| Sexo (11), raça/cor (13), hospitalização (50) | Sempre; há a opção "Ignorado" |
| Gestante (12) | Exceto sexo masculino (a tela esconde e registra 6 - Não se aplica) |
| Nome da mãe (16) | Sempre; se a pessoa não souber, escreve-se IGNORADO |
| Residência: logradouro (21), número (22), telefone (28), zona (29) | Sempre; número aceita S/N e, sem telefone, vale o de um contato ou SEM TELEFONE. Os demais campos da residência (município, bairro, CEP...) seguem opcionais |
| Ocupação (32) | Sempre, com sugestões (estudante, do lar, aposentado(a), desempregado(a), não se aplica) |
| Sinais clínicos (33) e doenças pré-existentes (34) | Todos os itens respondidos; a tela já traz cada um como "Não", com Sim e Ignorado para trocar |
| Resultado do NS1 (42) | Só quando a data da coleta (41) foi informada |
| Caso autóctone (56), sinais de alarme (68), dengue grave (70) | Sempre; 68 e 70 têm "Não" e "Ignorado" |

O número da notificação continua opcional.

## O que ainda falta

`services.sfa_notificacao.pendencias` devolve os campos que a ficha ainda
espera, em três grupos. Ficha sem pendência não mostra aviso nenhum.

| Grupo | Entra quando |
|---|---|
| Notificação e investigação | Em branco: nascimento (9), sexo (11), gestante (12, exceto sexo M), raça/cor (13), escolaridade (14), nome da mãe (16), município de residência (18), bairro (20), logradouro (21), número (22), telefone (28), zona (29), data da investigação (31), ocupação (32), hospitalização (50). Item sem resposta em sinais clínicos (33) ou doenças pré-existentes (34). Com hospitalização = Sim: data da internação (51) e hospital (54) |
| Exames | Coleta registrada sem resultado (39–46 e chikungunya 35–38), ou resultado informado sem a data da coleta. "Não realizado" não espera nada |
| Encerramento do caso | Em branco: caso autóctone (56), classificação (62), critério (63), evolução (65), data de encerramento (67), sinais de alarme (68), dengue grave (70). Óbito pede a data (66); chikungunya pede apresentação clínica (64); classificado com sinais de alarme ou dengue grave e resposta Sim no bloco pede a data (69/71). Caso descartado dispensa evolução |

## Panorama das unidades

Contagem de notificações por unidade na semana epidemiológica atual, nas últimas
4 semanas e no ano, pela data de notificação. Mostra somente números.

- Fontes: a planilha municipal (a sincronização passou a guardar agravo e
  unidade notificante em `sfa_sinan_log`) e as fichas registradas aqui. A ficha
  digital e a linha da planilha com o mesmo número são um registro só.
- O texto da planilha é ligado à unidade pelo nome, pelo CNES ou por um dos
  **outros nomes** cadastrados na unidade. O que não casa fica em "Unidade não
  identificada"; o administrador vê quais nomes ficaram de fora.
- Registros de teste (`TESTE-`, `[TESTE SFA]`, `SFA-TESTE`) não contam.
- Linhas importadas antes desta mudança recebem agravo e unidade na próxima
  sincronização da planilha.

## Banco

Migration `c7d2e4f6a8b1`: tabelas `sfa_unidade_saude` e `sfa_unidade_responsavel`;
colunas `agravo`, `unidade_notificante`, `unidade_id` e `preenchido_por_id` em
`sfa_sinan_log`. Cadastra as seis unidades que o campo 6 da ficha já sugeria.
