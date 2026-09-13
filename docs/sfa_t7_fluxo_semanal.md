# SFA: calendário por doença e organização semanal

Implementação local de 13/09/2026. Esta entrega não executa migração no servidor, não publica o site e não altera a planilha de origem.

## Calendário e histórico

- O início dos sintomas é **D0**. T7 = D0 + 7 dias; T30 = D0 + 30 dias. T0 é a entrevista inicial, com data própria. Exemplo: sintomas em 10/09 e entrevista em 13/09 → T7 em 17/09 e T30 em 10/10.
- O T0 oferece a data do SINAN para conferência. Uma data ausente, futura, inválida ou divergente entra em revisão. A entrevista nunca substitui o início dos sintomas.
- Uma revisão documentada na tela de trabalho tem precedência sobre as fontes originais. A revisão identifica responsável e fonte; seu histórico é auditado. Não reescreve respostas anteriores.
- Os formulários de seguimento exigem T0 e início válido. Antes do dia previsto, informam a data de abertura. Respostas tardias guardam o dia real da doença e o alvo original; não são retrodatadas.
- O payload de cada nova coleta inclui `_calendario`: início, fonte, dia da doença, data da coleta, alvo e intervalo de referência. No T0 o intervalo começa no início da doença; nos seguimentos, na última resposta anterior. Não somar despesas ou incapacidade de períodos sobrepostos.
- T10 permanece em tabela, campos e exportação próprios. Um episódio com T10 histórico não recebe uma segunda coleta equivalente em T7. Os instrumentos `collective-v2` e `legacy-2026-08-24` ficam disponíveis com seus hashes; o novo instrumento é `collective-v3-disease-clock`.
- O CSV analítico distingue T0, T7, T10 histórico e T30, suas versões e os metadados de calendário. Registros antigos sem esses metadados permanecem vazios nesses campos.

## Quem faz o quê

| Papel | Rotina | Registro esperado |
|---|---|---|
| Agente no dia a dia | Abrir o episódio; conferir o dia da doença; realizar contato e registrar o resultado | Etapa, canal, resultado, responsável, motivo e próximo contato combinado |
| Organização do trabalho | Conferir datas e território; investigar sinais coletivos; atribuir ações e prazos | Fonte da revisão, vínculo episódio–evento, objetivo da ação, responsável e prazo |
| Supervisão/decisão | Avaliar se o evento exige ação e verificar o resultado do trabalho | Avaliação independente, justificativa, evidência, verificador e data |

A tela **Organização do trabalho** (`/sfa/trabalho`) reúne pendências de qualidade, contatos, eventos e ações. A ficha individual tem um atalho para ela.

Uma matrícula do estudo representa um episódio. Vários episódios podem estar vinculados a um evento, e um evento pode ter várias ações. O vínculo exige evidência de local, período e exposição; semelhança de respostas não confirma um surto. A classificação clínica do episódio é registrada com sua fonte e não é deduzida do grupo administrativo A/B.

Recusa suspende a fila automática de contato. Um reagendamento guarda a data combinada. Atraso é uma pendência: **perda de seguimento exige decisão registrada**, não decorre apenas da passagem do tempo.

As ações avançam de aberta para em andamento/executada, e só então para verificada. Verificação exige evidência e identificação de quem verificou. Reabertura exige motivo e preserva a auditoria. Horas e custos são opcionais; ausência não equivale a zero. Concluir T30 encerra o acompanhamento individual, mas não conclui ações de campo.

## Pacientes e larvas: o relacionamento disponível

A tela **Pacientes e larvas** (`/sfa/vigilancia-semanal`) agrega cada fonte antes de cruzá-las. A chave é **setor operacional validado + semana iniciada no domingo**, evitando multiplicar pacientes pelo número de visitas.

| Fonte | Data de referência | Unidade contada |
|---|---|---|
| Episódios SFA | Início dos sintomas | Episódio cadastrado, vinculado a residência conferida |
| Levantamento entomológico | Data do trabalho de campo | Linha do levantamento; pode representar várias inspeções e conter revisitas |

O filtro compara visitas na mesma semana dos sintomas ou de uma a quatro semanas antes. A defasagem é exploratória: não declara qual intervalo é causal ou biologicamente ideal. Semanas futuras não são criadas como zeros; a semana em curso é identificada.

O vínculo territorial usa o código completo do setor do levantamento e exige fonte da conferência. Bairro não basta. Um setor operacional não é convertido automaticamente em setor do Censo 2022. A tela atual cruza **residência**; o provável local de infecção pode ser registrado como outro tipo de local, mas fica fora desse cruzamento. Esta versão mantém um local principal por episódio; uma estrutura com múltiplos locais por pessoa/episódio deve preceder análises de mobilidade.

São apresentados episódios, classificação conhecida, registros de campo, trabalhados, positivos, fechados, recusados, subtotal de larvas A. aegypti e preenchimento de larvas. “—” significa ausência de informação. Zero de episódios significa nenhum episódio vinculado nesta base, não ausência de doença na população. As contagens do levantamento não são imóveis únicos, IIP ou índice de Breteau.

## Como receber os dados toda semana

1. **Receber e identificar o lote.** Para cada fonte, guardar período coberto, data de extração/recebimento, origem, responsável e se o envio é completo, parcial ou uma correção.
2. **Conferir antes de interpretar.** Verificar início dos sintomas, classificações, duplicidades, chave do episódio, código territorial e valores ausentes. Corrigir o vínculo territorial com evidência.
3. **Atualizar e reconciliar.** A sincronização SINAN passa a reconhecer mudanças na mesma chave, auditar antes/depois e preservar campos locais divergentes. Respostas e revisões documentadas não são sobrescritas. Resultado vazio ou inconclusivo fica pendente de revisão.
4. **Ler as séries juntas.** Comparar sintomas e trabalho de campo com cobertura e preenchimento ao lado. Uma queda após semanas sem envio não é evidência de melhora. Uma elevação depois de ampliar as inspeções pode decorrer da busca mais intensa.
5. **Decidir e acompanhar.** Registrar a hipótese, o evento investigado e a ação escolhida. Na reunião seguinte, conferir execução, resultado e necessidade de reabertura.

O recebimento automático de novos arquivos entomológicos **ainda não foi conectado**. A tela usa o snapshot versionado já existente, produzido pelo importador descrito em `docs/entomologia.md`. Não anexar exportações cumulativas semanais umas às outras: isso duplicaria visitas. Enquanto a fonte não fornecer identificador estável de visita/linha e política de correções, produzir um snapshot cumulativo conferido por atualização e manter a versão anterior. Reiniciar os processos da aplicação após trocar o snapshot, pois o carregamento atual usa cache em memória.

Para a próxima integração, solicitar pelo menos:

- **Pacientes:** identificador estável da notificação/episódio; início dos sintomas; notificação; classificação final, critério e data da classificação; exame, amostra e data de coleta; território e tipo de local. Registrar correções sem apagar a fonte anterior.
- **Campo:** identificador da visita/linha e do imóvel quando possível; data; área/setor/quadra; revisita; tentativas e resultados de acesso; tipo de recipiente; inspeção e positividade; espécie e contagem de larvas; ação efetuada; responsável. Campo não preenchido, não examinado e zero devem ser distintos.
- **Lote:** identificador, versão, hash do arquivo, cobertura prevista/recebida e situação da validação. Isso permitirá distinguir semana sem casos de semana sem informação.

## Indicadores para a reunião semanal

- Início válido / episódios elegíveis; residência validada / episódios com início válido.
- T7 respondido no D7 / episódios que chegaram ao D7, com T0, consentimento vigente e sem T10 histórico. Mostrar respostas tardias separadamente.
- Ações vencidas ainda não verificadas / ações com prazo já atingido.
- Ações verificadas / ações executadas, sempre com evidência de verificação.
- Linhas com contagem de larvas preenchida / linhas recebidas, junto da cobertura territorial do lote.

Essas definições orientam a rotina; nem todos esses indicadores têm um cartão calculado nesta versão. Não transformar uma correlação preliminar em escore automático de risco. Antes de modelar associações, definir desfecho e defasagens com a equipe, separar suspeitos/confirmados/descartados, avaliar sazonalidade, clima, esforço de inspeção e mudanças na notificação. São dados agregados: associação territorial não comprova exposição individual.

## Entrada em produção

1. Preservar uma cópia do banco e dos instrumentos em uso. Conferir overrides de schema; o novo arquivo é `config/sfa_t7_form.json` (`SFA_T7_FORM_SCHEMA_FILE`, quando utilizado).
2. Em homologação, aplicar a migração `d3a7c4e1f300`, cuja antecessora é `c2f6b3d0e200`. Ela cria T7 e as tabelas do trabalho; não copia T10 para T7. Validar o caminho de migração no banco usado em produção.
3. Após atualizar banco e aplicação, executar **Rodar Rotina** para recalcular as pendências existentes pelo início dos sintomas. Conferir as pendências antes de disparar contatos. A rotina não envia mensagens.
4. Conferir T0 → T7 → T30, resposta tardia, histórico T10, consentimento por representante, revisão de data e uma ação até sua verificação.
5. O downgrade se recusa a remover as novas tabelas quando já contêm dados. Planejar reversão com exportação/preservação; não descartar respostas ou histórico do trabalho.

Validação desta entrega: testes Python do SFA/entomologia, testes JavaScript dos formulários e do modelo entomológico, migração em SQLite isolado e inspeção das telas no navegador com dados fictícios. Nenhuma notificação real foi enviada.
