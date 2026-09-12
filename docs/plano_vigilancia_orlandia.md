# Planejamento da vigilância de Orlândia com os dados disponíveis

Estudo e proposta operacional • 10/09/2026 • referência de campo até 08/09/2026.

A recomendação é organizar o trabalho em frentes separadas: investigar suspeitas de dengue, verificar focos registrados, recuperar o acesso aos imóveis e corrigir lacunas de informação. Cada território deve mostrar **o sinal observado, a ação a conferir e a qualidade da evidência**. Uma pontuação única de risco esconderia diferenças importantes entre essas decisões.

A aba **Planejamento**, na página de entomologia, implementa as três listas que os arquivos permitem calcular hoje. A investigação de suspeitas permanece explicitamente sem dados, aguardando uma fonte municipal com cobertura conhecida. As listas são candidatas à revisão, não ordens de serviço nem previsão de transmissão.

## 1. O que a base permite afirmar

Fonte de campo: `Dados.zip`, arquivo `Visita a Imóvel.csv`, importado em `services/data/entomologia/snapshot.json`. O processo de importação e a origem da malha estão documentados em [entomologia.md](entomologia.md). Os valores abaixo são somas das linhas da fonte; podem incluir revisitas.

| Evidência | Resultado | Consequência para a decisão |
|---|---:|---|
| Registros de 05/01 a 08/09/2026 | 2.371 | Fotografia do arquivo, sem atualização automática |
| Imóveis trabalhados, somados nas visitas | 16.507 | Não representa 16.507 residências únicas |
| Imóveis com larvas, valores informados | 215 | Não é uma taxa de infestação |
| Resultado de larvas ausente | 1.949 registros (82,2%) | Ausência de preenchimento não pode virar zero |
| Ocorrências de imóveis fechados / recusas | 13.571 / 1.207 | Avaliar acesso, motivos e retornos já feitos |
| Códigos territoriais no arquivo | 72 | Não equivalem a 72 bairros |
| Registros sem código correspondente na malha 2022 | 43, em 5 códigos | Permanecem nas listas; localização precisa de validação |
| Censo 2022: população / domicílios totais | 38.319 / 15.334 | Contexto territorial de 2022, sem atualização demográfica para 2026 |
| Domicílios particulares ocupados, Censo 2022 | 13.566 | Não é o cadastro operacional de imóveis visitáveis |

Há uma repetição de linha após a retirada dos identificadores dos agentes. Ela foi mantida porque não há identificador confiável que permita distinguir duplicação de uma nova visita. Não se somam indiscriminadamente categorias de situação do imóvel para criar um denominador: a exclusividade dessas categorias ainda precisa ser confirmada com quem registra os dados.

As tabelas locais `sfa_paciente` e `sfa_sinan_log` estavam vazias na inspeção. A leitura da planilha configurada não pôde ser realizada porque não há credenciais Google utilizáveis neste ambiente. Isso não descreve a situação epidemiológica municipal. O código de importação do SFA, por si só, também não comprova que a planilha contenha todas as notificações de Orlândia. Os grupos de pesquisa e os resultados laboratoriais não substituem a classificação epidemiológica final.

## 2. Onde começar a revisão

Janela recente: **12/08 a 08/09/2026**, comparada com **15/07 a 11/08/2026**, ambas com 28 dias. A duração é uma opção de exploração, não um limiar epidemiológico validado. O painel também permite 7 e 14 dias, escolha da data de referência e detalhamento por setor e quarteirão.

| Medida | Recente | Anterior |
|---|---:|---:|
| Registros | 238 | 250 |
| Setores com registros | 38 | 36 |
| Imóveis trabalhados | 1.591 | 1.529 |
| Imóveis com larvas, soma informada | 14 | 15 |
| Ocorrências de fechados | 1.161 | 1.004 |
| Recusas | 121 | 163 |
| Registros com resultado de larvas | 68 (28,6%) | 69 (27,6%) |

Esses números não demonstram queda de infestação ou aumento de transmissão. Os locais visitados, a intensidade da busca e a informação disponível diferem. Os meses de janeiro e setembro também são parciais no arquivo e não devem ser comparados como meses completos.

Na tabela seguinte, o identificador completo é o prefixo **35343020500** seguido do final de quatro dígitos mostrado. São setores do cadastro recebido; nomes de bairros ainda não foram atribuídos.

| Setor — final do código | Evidência em 12/08–08/09 | Revisão sugerida |
|---|---|---|
| **0017** | 3 ocorrências com larvas, 1 com A. aegypti, 166 fechados e 8 recusas; preenchimento 12,5% | Conferir o achado e a ação realizada; revisar os retornos e a incompletude no mesmo território |
| **0003** | 2 ocorrências com larvas, 1 com A. aegypti; 3 registros, todos com resultado | Conferir identificação e resolução dos focos; volume pequeno não permite comparação de risco |
| **0045** | 165 fechados e 25 recusas; preenchimento 11,8% | Revisar pendências e testar estratégia de acesso; a soma zero de larvas não indica ausência de infestação |
| **0018** | 140 fechados e 14 recusas; nenhum dos 5 registros tem resultado de larvas | Combinar recuperação de acesso e esclarecimento do registro |
| **0076** | 27 de 28 registros sem resultado de larvas | Conferir o significado dos vazios e corrigir o processo de preenchimento |

**Critérios transparentes implementados:** focos são ordenados por soma de A. aegypti, soma de imóveis com larvas e recência do achado; acesso por fechados e depois recusas; qualidade por quantidade de registros sem resultado. Os critérios são heurísticas de organização, sem pesos ou escore clínico. Um território pode aparecer em várias listas. A ordem pode ser alterada pela equipe diante de notificações, emergências e informações de campo ainda não disponíveis.

Cada lista apresenta o motivo, os valores e a última data registrada; permite abrir os registros de origem e exportar todos os candidatos em CSV. A tela mostra até 20 linhas. Datas distintas com achado no mesmo setor ou quarteirão não comprovam reinfestação do mesmo imóvel. A fonte não vincula achado, intervenção e verificação de resolução.

## 3. Como organizar a informação para uso diário

| Conjunto | Unidade de registro e campos essenciais | Para que serve |
|---|---|---|
| Território | Código oficial de bairro, setor com versão da malha, quarteirão, área de atuação e vigência; responsável pela validação | Permitir mapas e listas por bairro sem associações ambíguas |
| Imóvel e visita | ID persistente de imóvel; ID e data/hora da visita; tipo de atividade/ciclo; resultado de acesso; se houve inspeção; resultado e espécie; tipo e quantidade de recipientes | Distinguir residência única, tentativa, revisita, atividade e achado |
| Notificação | ID de episódio e fonte; município de residência; início dos sintomas; notificação; classificação atual e data; bairro de residência; local provável de infecção e qualidade da localização | Acompanhar suspeitas e orientar investigação territorial sem contar a mesma notificação várias vezes |
| Ação e retorno | ID da ação; vínculo com imóvel, foco ou notificação; tipo; responsável; abertura, prazo, execução e verificação; motivo de pendência; horas e custo | Transformar sinais em trabalho acompanhado e medir resolução |
| Censo e cadastro municipal | População e domicílios com ano, conceito e limites; cadastro atualizado de imóveis elegíveis | Dimensionar equipes e calcular indicadores com denominadores compatíveis |

Quando um setor atravessa mais de um bairro, não duplicar sua população em todos eles. Priorizar endereço validado ou uma correspondência territorial formal; qualquer estimativa por área deve ser explicitamente identificada e não pressupor distribuição homogênea dos moradores. Preservar uma categoria “localização pendente” e sua contagem.

Para a visão epidemiológica, organizar os episódios por semana de início dos sintomas e manter uma visão separada por data de notificação para o trabalho de investigação. Mostrar suspeitos, confirmados, descartados e situação desconhecida com definições explícitas; um caso reclassificado não pode ser contado duas vezes no mesmo total. Sinalizar atrasos de entrada e revisar períodos recentes. O [CVE-SP divulga seus dados de dengue por município de residência e início dos sintomas](https://www.saude.sp.gov.br/cve-centro-de-vigilancia-epidemiologica-prof.-alexandre-vranjac/areas-de-vigilancia/doencas-de-transmissao-por-vetores-e-zoonoses/arboviroses-urbanas/dengue-dados-estatisticos), referência para compatibilizar as séries.

Participantes do mestrado devem ter marcação de coorte e critérios de inclusão conhecidos. A quantidade de participantes por bairro não estima incidência municipal. Informações individuais devem ficar em uma tela restrita à equipe que executa a investigação; a visão de gestão usa agregados e evita expor domicílios de pacientes em mapas compartilhados.

## 4. Rotina e programas propostos

**No início do dia**, a coordenação verifica atualização, notificações e ocorrências urgentes; confere se os candidatos ainda estão pendentes; escolhe as ações conforme equipe e deslocamentos. **No campo**, o agente registra resultado, causa do impedimento, intervenção e necessidade de retorno. **Ao encerrar**, a equipe registra execução e pendências. **Semanalmente**, a coordenação revê problemas repetidos, cobertura territorial e resultados das ações, incluindo territórios com pouca informação.

O [Ministério da Saúde orienta combinar vigilância entomológica e manejo integrado de vetores](https://www.gov.br/saude/pt-br/assuntos/saude-de-a-a-z/a/aedes-aegypti/vigilancia-entomologica). Seus índices larvários se apoiam em levantamentos definidos, como LIRAa/LIA; por isso, o painel não transforma as somas das visitas em IIP ou Breteau. As propostas abaixo são desenhos locais a avaliar, não intervenções com eficácia já demonstrada nesta base.

| Programa proposto | Trabalho e responsáveis sugeridos | Como medir retorno |
|---|---|---|
| **Imóvel acessível** | ACE e ACS: testar agendamento e horários alternativos, registrar motivos de recusa e não acesso | Imóveis únicos inspecionados entre os que tinham retorno previsto; horas e custo por acesso recuperado; comparar com a rotina anterior e territórios semelhantes |
| **Criadouro resolvido** | Vigilância e serviços urbanos: verificar achados, classificar recipientes, resolver problemas de água, resíduos ou drenagem e conferir o resultado | Problemas com resolução verificada / problemas com verificação prevista; tempo para resolver; repetição de achados após a ação |
| **Resposta às suspeitas** | Vigilância epidemiológica, vetorial e atenção básica: integrar notificações e investigação; definir resposta segundo protocolo e local provável de infecção | Mediana e percentil 90 do tempo até investigação/ação, pendências abertas, localização completa e execução dentro do prazo pactuado |
| **Registro que orienta** | Supervisão e responsáveis pelos sistemas: separar zero, não examinado e não informado; identificar imóvel, visita e ação; devolver inconsistências à origem | Completude por campo e tipo de atividade, duplicações confirmadas, atraso de atualização e correções verificadas |

Não automatizar indicação de inseticida a partir do número de larvas. A escolha e a execução das medidas dependem da avaliação técnica e dos protocolos vigentes. Antes de implantar armadilhas como um novo programa, dimensionar desenho amostral, periodicidade, laboratório, equipe e orçamento; a fonte recebida não contém dados de ovitrampas que permitam avaliar essa estratégia localmente.

## 5. Avaliar resultado, custo e equidade

Começar com um piloto de acesso e resolução de criadouros em territórios selecionados após revisão da equipe. Definir objetivos, capacidade, critérios de seleção e indicadores **antes** da intervenção. Estabelecer metas a partir de uma linha de base verificada, sem adotar percentuais arbitrários como padrões oficiais.

Registrar esforço e custos desde o início. Acompanhar também áreas com poucos registros, para que maior produção de dados não concentre toda a atenção nos mesmos lugares. Se viável, implantar o piloto em etapas e comparar territórios semelhantes no mesmo período. Ao analisar notificações, considerar sazonalidade, mudanças na busca e na notificação, circulação viral e outras intervenções. Sem desenho adequado, apresentar associação temporal e resultados operacionais, sem atribuir causalidade.

A avaliação pode começar por acesso recuperado, pendências resolvidas e tempo de resposta. Redução de adoecimento é o resultado de saúde desejado, mas exige uma série de casos confiável e acompanhamento suficiente. Aumentar visitas ou eliminar mais recipientes, isoladamente, não comprova melhoria de saúde.

## 6. Próximas integrações necessárias

1. Confirmar cobertura e disponibilizar a fonte municipal de notificações, sem confundi-la com a coorte do mestrado.
2. Validar com a equipe o significado dos campos vazios e o vínculo bairro–setor–quarteirão, incluindo a versão territorial.
3. Registrar imóveis únicos e a sequência achado–ação–retorno–verificação, para identificar pendências reais.
4. Incorporar cadastro atual de imóveis elegíveis, equipe, horas e custos para planejar capacidade e avaliar retorno.

Até essas integrações, o painel apoia a revisão territorial dos registros recebidos. Não informa quantos casos suspeitos existem hoje, quais bairros têm maior incidência ou quais imóveis permanecem pendentes. A aplicação está preparada e testada localmente; esta etapa não incluiu deploy.
