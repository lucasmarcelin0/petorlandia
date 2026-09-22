# Piloto individual dos formulários SFA

O piloto usa o próprio SFA, com uma pessoa identificada por rótulo neutro no painel e três links individuais. Não é uma matrícula na coorte municipal. O cadastro e as respostas ficam nas tabelas `sfa_pilot_participant` e `sfa_pilot_response`, sem ficha SINAN, CPF, TCLE de pesquisa ou linhas em `sfa_paciente`/`sfa_resposta_t*`.

## O que está preparado

- Seção **Pilotos de usabilidade** no dashboard `/sfa/`, independente do filtro e dos números da coorte.
- Gestão interna em `/sfa/pilotos`, usando o mesmo acesso administrativo do SFA.
- Ficha interna do piloto com estado de cada etapa, dados autorizados, respostas, locais de trabalho/estudo, sugestões e links para copiar.
- Convite individual com token aleatório, que liga T0, T7 e T30 à mesma pessoa. Nenhum dado de saúde é colocado em parâmetros de URL ou em modelos públicos.
- T0 com dados mínimos que, no estudo municipal, viriam do SINAN: município, bairro/idade opcionais, sintomas relatados, resultados e datas de coleta PCR/NS1 se conhecidos. Campos não informados permanecem em branco; não são convertidos em exame negativo ou não realizado.
- Trabalho e estudo em vários locais: atividade, estabelecimento/instituição, município, bairro, endereço ou referência. Inclui casa, atividade sem local fixo e não trabalhar/estudar. Dias/semana e horas/dia são complementos opcionais para avaliação.
- Perguntas condicionais dos acompanhamentos usam as respostas anteriores desse piloto, e não de pessoas da coorte.
- Sugestões e tempo de preenchimento em cada etapa. O envio de **somente sugestões** não guarda respostas clínicas, não marca a etapa como respondida e não cria entrevista.

## Datas confirmadas com Lucas

**D0 é a data do início dos sintomas. T0 é a data real da primeira entrevista. T7 = D0 + 7 dias; T30 = D0 + 30 dias.**

Criar o piloto não registra T0. Abrir um link ou enviar somente sugestões também não registra T0. A primeira entrevista é registrada na data local de São Paulo quando as respostas T0 são enviadas; o sistema calcula separadamente os dias de doença nessa entrevista. Não há retrodatação para o início dos sintomas.

T7/T30 podem ser lidos antes da data para avaliar as perguntas. O envio de respostas da etapa requer T0 registrado, início conhecido e chegada à data de referência. Antes disso é possível enviar apenas sugestões. Um T0 tardio não desloca os alvos T7/T30. A ficha sinaliza T0 após D7 ou D30, sem fabricar observações anteriores. T30 pode ocorrer sem T7, usando a data do T0 como último contato conhecido. Uma resposta já enviada não é sobrescrita por repetição do envio.

## Como Lucas poderá usar

1. Após a publicação e migração, abrir **Pilotos de usabilidade → Gerenciar pilotos**.
2. Criar um único piloto com rótulo neutro e somente os dados autorizados. Manter PCR em **Não informado** se nenhum resultado foi fornecido. Não preencher uma entrevista que ainda não ocorreu.
3. Copiar o **convite individual** da ficha. Ele contém as três etapas. Lucas encaminha o link ao amigo; o sistema não envia mensagens.
4. Pedir que o amigo confira os dados preenchidos, responda ao T0 no momento real e use o espaço final para apontar dúvidas. Os dados são um ensaio, não diagnóstico ou vigilância assistencial.
5. Conferir o retorno na ficha do piloto e acompanhar as referências T7/T30 ali indicadas.

Os links individuais permitem acesso ao contexto do piloto. Devem ser enviados somente ao participante autorizado. As páginas usam `no-store`, `noindex` e `no-referrer`; gestão e leitura administrativa continuam protegidas. Não há listagem pública de pilotos. O teste não é monitorado para atendimento de saúde.

## Decisões analíticas e diferenças do documento

Fonte operacional: `config/sfa_t0_form.json`, `config/sfa_t7_form.json` e `config/sfa_t30_form.json`, versão `collective-v3-disease-clock`. O piloto copia essas definições em memória; não altera os instrumentos municipais.

O [projeto em revisão](https://docs.google.com/document/d/1ULrp0zsN6kFzF5PPYZ_MV-oGHafvgykCZJmllYiJRXQ/edit), consultado pelos anexos A/B/C, ainda traz T10 e acompanhamentos contados desde T0. A decisão posterior de Lucas acima prevalece no piloto. O texto original do documento não foi editado por esta implementação.

A investigação ampla de possíveis causas pode abranger todos. Para a comparação de sintomas, as decisões informadas são: positivo por PCR positivo **ou** NS1 positivo; comparador negativo com PCR negativo **documentado**. NS1 negativo isolado não qualifica o comparador negativo. Resultados discordantes, inconclusivos e outros ainda precisam de definição. O piloto não classifica automaticamente nem atribui grupo a uma pessoa com base em sintomas ou relato de exame.

O documento apresenta gastos e incapacidade acumulados; os formulários operacionais atuais usam T0 desde o início e T7/T30 desde o contato anterior. O piloto reproduz a redação operacional para testar sua compreensão, sem transformar a proposta de mudança dos acumulados em decisão metodológica. Não agrega os valores nem produz estimativas de efeito. Essa divergência continua para revisão de Lucas e orientadoras. As escalas e outros itens dos anexos que não constam dos instrumentos operacionais não foram silenciosamente incorporados.

## Publicação e limites

Esta entrega requer publicar o código e aplicar a migração `e4b8d5f2a411`, após `d3a7c4e1f300`. A migração apenas cria as duas tabelas do piloto. Não cadastra participantes ou altera pendências municipais. O downgrade se recusa a remover pilotos existentes.

Os links públicos antigos `/sfa/revisao/t0`, `/sfa/revisao/t7` e `/sfa/revisao/t30` foram verificados no navegador: são avaliações genéricas já disponíveis, não o convite individual desta entrega. Os novos links individuais só estarão utilizáveis depois da publicação e de um cadastro explicitamente realizado.

Não houve envio ao amigo, importação de laudo, criação de ficha SINAN, aprovação de TCLE, alteração do documento original ou recálculo em massa das pendências municipais.
