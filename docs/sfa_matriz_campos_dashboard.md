# Matriz de campos para dashboards oficiais da SFA

Esta matriz classifica os campos dos formularios T0, T10 e T30 para orientar quais informacoes devem entrar no dashboard oficial da pesquisa, quais devem permanecer como analiticas e quais podem ficar apenas em arquivo/auditoria.

## Criterios

- **Oficial**: campo recomendado para dashboard principal, indicadores recorrentes e exportacao analitica prioritaria.
- **Analitico**: campo util para investigacoes secundarias, cruzamentos e hipoteses, mas nao essencial no painel principal.
- **Arquivo**: campo importante para rastreabilidade, consentimento, identificacao ou texto livre, mas nao recomendado como indicador principal.
- **Redundancia**: risco de sobrepor informacao com outro campo ou gerar pouco ganho analitico.

## Campos derivados recomendados

| Campo derivado | Fonte | Uso recomendado | Decisao |
|---|---|---|---|
| idade | data_nascimento | Perfil epidemiologico por faixa etaria | Oficial |
| faixa_etaria | data_nascimento | Dashboards por perfil e recuperacao | Oficial |
| tempo_sintoma_notificacao | data_inicio_sintomas + data_notificacao | Atraso ate notificacao | Oficial |
| tempo_sintoma_t0 | data_inicio_sintomas + T0 respondido em | Adesao/tempo ate entrevista inicial | Oficial |
| tempo_t0_t10 | T0 respondido em + T10 respondido em | Seguimento | Analitico |
| tempo_t0_t30 | T0 respondido em + T30 respondido em | Seguimento | Analitico |
| custo_total_t10 | custos T10 | Impacto economico intermediario | Oficial |
| custo_total_t30 | custos T30 + perda_renda_estimada | Impacto economico final | Oficial |
| recuperacao_alta | estado_saude_final | Recuperacao total/quase total | Oficial |
| recuperacao_lenta | estado_saude_final + retorno_atividades_normais | Desfecho funcional ruim | Oficial |

## T0 - Identificacao e contexto

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| cpf | CPF | Vinculo/identificacao interna | Alta | Arquivo |
| ficha_sinan | Numero da Ficha SINAN | Vinculo com SINAN e auditoria | Baixa | Arquivo |
| nome | Nome completo | Identificacao operacional | Alta | Arquivo |
| data_nascimento | Data de nascimento | Gerar idade/faixa etaria | Baixa | Oficial, via derivado |
| endereco | Endereco completo | Georreferencia futura e contato | Media | Analitico/Arquivo |
| bairro | Cadastro/SINAN | Perfil territorial | Baixa | Oficial |
| tipo_residencia | Tipo de moradia | Perfil socioambiental | Baixa | Oficial |

## T0 - Perfil de saude

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| diagnostico_dengue_previo | Ja teve diagnostico de dengue antes? | Estratificacao clinica secundaria | Baixa | Analitico |
| condicoes_previas | Comorbidades | Risco de evolucao pior | Baixa | Oficial |
| sexo_biologico | Sexo biologico | Perfil epidemiologico e recuperacao | Baixa | Oficial |
| vacinas_12_meses | Vacinas recentes | Hipoteses secundarias | Media | Analitico |
| ocupacao_principal | Ocupacao principal | Exposicao, impacto economico e retorno | Baixa | Oficial |
| fuma_ou_bebe | Fuma/alcool regularmente | Perfil de risco secundario | Media | Analitico |

## T0 - Sintomas atuais

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| data_inicio_sintomas | Data de inicio dos sintomas | Eixo temporal principal | Baixa | Oficial |
| teve_febre | Teve febre? | Caracterizacao clinica inicial | Media | Oficial |
| padrao_febre | Padrao da febre | Refinamento clinico | Media | Analitico |
| sintomas_principais | Sintomas principais | Matriz sintomas x grupo/desfecho | Baixa | Oficial |
| sinais_alerta | Sinais de alerta | Gravidade inicial | Baixa | Oficial |
| outros_sintomas | Outros sintomas | Complemento clinico | Media | Analitico |
| dor_mais_intensa | Local da dor mais intensa | Perfil clinico | Media | Analitico |

## T0 - Exposicoes recentes

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| contato_agua_suja | Contato com agua suja/lama/enchente | Hipoteses ambientais | Media | Analitico |
| contato_carrapato_mata | Picada de carrapato/area de mata | Hipoteses diferenciais | Media | Analitico |
| outras_pessoas_com_sintomas | Casos similares em casa/vizinhanca | Sinal de cluster domiciliar/territorial | Baixa | Oficial |
| contato_animais | Contato com animais | Hipoteses zoonoticas | Media | Analitico |
| consumo_recente | Consumo alimentar/agua | Hipoteses diferenciais | Alta | Analitico, revisar |
| atividades_recentes | Atividades ambientais/rurais | Hipoteses ambientais | Media | Analitico |

## T0 - Impacto inicial

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| dias_incap | Dias completamente incapacitado no inicio | Impacto funcional inicial | Baixa | Oficial |
| internacao | Internacao/hospitalizacao | Gravidade inicial | Baixa | Oficial |
| custo_total | Gasto inicial total | Impacto economico inicial | Media | Oficial, mas padronizar com custos T10/T30 |
| ausencia_familiar | Familiar faltou trabalho para cuidar | Impacto indireto familiar | Media | Analitico |
| observacoes_finais | Texto livre | Contexto qualitativo | Alta | Arquivo |
| aceite_tcle | Aceite do consentimento | Etica/auditoria | Baixa | Arquivo, obrigatorio |

## T10 - Identificacao

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| cpf | CPF | Vinculo | Alta | Arquivo |
| nome | Nome completo | Confirmacao operacional | Alta | Arquivo |
| data_entrevista_t10 | Data da entrevista | Tempo de seguimento | Baixa | Oficial |

## T10 - Evolucao clinica

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| classificacao_melhora | Como classifica a melhora? | Evolucao intermediaria | Baixa | Oficial |
| sintomas_persistentes | Sintomas persistentes | Persistencia sintomatica | Baixa | Oficial |
| sintomas_persistentes_outro | Outro sintoma persistente | Qualitativo/complemento | Alta | Arquivo |
| dor_articulacoes_impacto | Dor articular impede atividades? | Impacto funcional especifico | Baixa | Oficial |
| retornou_servico_saude | Retornou ao servico de saude? | Uso de servico | Baixa | Oficial |
| quantas_vezes_retornou | Numero de retornos | Intensidade de uso de servico | Media | Analitico |
| motivo_retorno_servico | Motivo do retorno | Motivo de demanda assistencial | Media | Analitico |
| motivo_retorno_servico_outro | Outro motivo | Complemento | Alta | Arquivo |
| internacao_t10 | Internacao no periodo | Gravidade intermediaria | Baixa | Oficial |
| dias_internado_t10 | Dias internado | Gravidade e custo | Media | Analitico |
| local_internacao_t10 | Local da internacao | Uso publico/privado | Media | Analitico |
| diagnostico_definitivo | Diagnostico definitivo recebido? | Resolucao diagnostica | Media | Analitico |
| diagnostico_informado | Qual diagnostico? | Texto/confirmacao | Alta | Arquivo/Analitico |

## T10 - Impacto acumulado e custos

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| dias_incap_novos | Total de dias incapacitado desde o inicio | Impacto funcional intermediario | Baixa | Oficial |
| ausencia_familiar | Familiar ainda precisa se ausentar? | Impacto indireto | Media | Analitico |
| custo_remedios | Medicamentos | Componente de custo | Baixa | Oficial |
| custo_consultas | Consultas/exames | Componente de custo | Baixa | Oficial |
| custo_transporte | Transporte | Componente de custo | Baixa | Oficial |
| custo_outros | Outros gastos | Componente de custo | Media | Oficial |
| renda_familiar_afetada | Renda familiar afetada? | Impacto socioeconomico | Baixa | Oficial |
| retorno_atividades_previsao | Previsao de retorno 100% | Prognostico funcional | Media | Analitico |
| observacoes_finais | Texto livre | Contexto qualitativo | Alta | Arquivo |

## T30 - Estado final e sequelas

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| cpf | CPF | Vinculo | Alta | Arquivo |
| nome | Nome completo | Confirmacao operacional | Alta | Arquivo |
| estado_saude_final | Estado de saude comparado a antes da doenca | Desfecho clinico principal | Baixa | Oficial |
| sequelas_atuais | Sequelas atuais | Desfecho clinico secundario | Baixa | Oficial |
| sequelas_atuais_outro | Outra sequela | Complemento | Alta | Arquivo |
| dor_articulacoes_final | Dor articular final | Sequela funcional especifica | Media | Oficial |

## T30 - Impacto funcional e economico final

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| dias_incap_novos | Total de dias incapacitado em 30 dias | Desfecho funcional principal | Baixa | Oficial |
| retorno_atividades_normais | Retorno as atividades normais | Desfecho funcional principal | Baixa | Oficial |
| custo_remedios | Medicamentos | Componente de custo final | Baixa | Oficial |
| custo_consultas | Consultas/exames | Componente de custo final | Baixa | Oficial |
| custo_transporte | Transporte | Componente de custo final | Baixa | Oficial |
| perda_renda_estimada | Perda estimada de renda | Impacto economico indireto | Baixa | Oficial |
| custo_outros | Outros gastos | Componente de custo final | Media | Oficial |
| impacto_emocional_familiar | Impacto emocional/familiar duradouro | Desfecho psicossocial | Baixa | Analitico |

## T30 - Encerramento

| Campo | Pergunta | Uso recomendado | Redundancia | Recomendacao |
|---|---|---|---|---|
| conselho_outras_pessoas | Conselho a outras pessoas | Qualitativo | Alta | Arquivo/Analitico qualitativo |
| avaliacao_atendimento_saude | Avaliacao do atendimento recebido | Qualidade percebida do cuidado | Media | Analitico |
| participaria_outro_estudo | Participaria de outro estudo? | Aceitabilidade da pesquisa | Media | Analitico |
| observacoes_finais | Texto livre | Qualitativo | Alta | Arquivo |

## Proposta de dashboard oficial v1

### Perfil epidemiologico

- Total de casos.
- Casos por grupo A/B.
- Casos por bairro.
- Casos por sexo biologico.
- Casos por faixa etaria.
- Casos por ocupacao.

### Tempo e seguimento

- Mes de inicio dos sintomas.
- Data de notificacao.
- Tempo medio entre inicio dos sintomas e notificacao.
- Tempo medio entre inicio dos sintomas e T0.
- Taxa de resposta T0/T10/T30.

### Quadro clinico

- Sintomas principais no T0.
- Sinais de alerta.
- Sintomas persistentes no T10.
- Estado de saude final no T30.
- Sequelas atuais no T30.

### Impacto funcional

- Dias incapacitantes T0, T10 e T30.
- Retorno as atividades normais no T30.
- Dor articular persistente.
- Recuperacao alta vs recuperacao lenta.

### Impacto economico

- Custo total medio T10.
- Custo total medio T30.
- Componentes de custo: medicamentos, consultas/exames, transporte, outros.
- Perda de renda estimada.
- Renda familiar afetada.

### Hipoteses e cruzamentos

- Grupo A vs B por sintomas.
- Grupo A vs B por custo final.
- Grupo A vs B por recuperacao alta.
- Recuperacao por sexo/faixa etaria/ocupacao.
- Custo medio por retorno as atividades.
- Sinais de alerta associados a recuperacao lenta.

## Campos a revisar antes de consolidar o formulario

| Campo | Motivo | Acao sugerida |
|---|---|---|
| cpf | Dado sensivel e pouco util para dashboard | Manter apenas se necessario para vinculo; nunca exibir em dashboard |
| endereco | Texto livre sensivel | Preferir bairro/geocodificacao segura |
| padrao_febre | Pode sobrepor teve_febre e sintomas | Manter como analitico |
| outros_sintomas | Pode dispersar analise | Manter, mas nao priorizar no dashboard |
| consumo_recente | Muitos itens e hipotese ampla | Revisar se ha objetivo epidemiologico claro |
| atividades_recentes | Pode sobrepor exposicoes ambientais | Manter como analitico |
| diagnostico_informado | Texto livre pouco padronizado | Considerar lista fechada |
| campos *_outro | Baixa padronizacao | Arquivo/analise qualitativa |
| observacoes_finais | Texto livre | Arquivo/qualitativo |
| conselho_outras_pessoas | Texto qualitativo | Separar de dashboard quantitativo |

## Recomendacao final

Para a primeira versao oficial, priorizar um dashboard quantitativo com os campos classificados como **Oficial**. Os campos **Analitico** devem continuar no banco e nas exportacoes, mas entrar em paineis secundarios. Os campos **Arquivo** devem permanecer acessiveis no detalhe do paciente e exportacoes controladas, sem compor indicadores principais.
