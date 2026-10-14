# Casa a casa

App de campo em `/sfa/entomologia/casa-a-casa`, aberto pela aba "Casa a Casa" do
painel do território, pelo cartão "Combate à dengue" da página inicial e pela
barra lateral do SFA. Tela própria, leve, pensada primeiro para o celular.

## O que faz

- **Mapa em branco**: só os quarteirões da malha de campo (`territory.json`),
  com o número de cada um. Ao aproximar aparecem as casas (endereços numerados
  do atlas, CNEFE com as correções da equipe) e, bem perto, o número de cada casa.
  A partir de uma aproximação média, o **nome de cada rua** é escrito ao longo do
  eixo dela (eixos do OpenStreetMap que já fazem parte do atlas, com o nome no
  mesmo formato da lista de casas: "Rua 26"). Vai junto na base guardada no
  aparelho, então aparece também sem internet.
  Não depende de imagem de fundo; "ruas ao fundo" é opcional e precisa de internet.
- **Escritório**: escolhe dia e trabalhador, seleciona vários quarteirões no
  mapa ou pela busca (número, rua, bairro e setor), confere a carga e salva o
  lote. Clicar apenas seleciona; não altera o plano. Os atalhos mostram os próximos
  cinco dias de segunda a sexta; o calendário permite outras datas até 60 dias à frente.
  A tabela de carga compara trabalhadores por dia. O mapa colore o plano da data escolhida
  por responsável. A revisão avisa quando o lote troca responsáveis ou acrescenta datas
  a quarteirões já previstos. Reagendar move a data de um quarteirão que ainda não começou;
  se há visitas ou destino ocupado, o servidor preserva o lote. Cada alteração leva a
  versão mostrada na tela; estado divergente responde 409 e pede nova conferência.
  Ao planejar escolhe também a **atividade**: avaliação de densidade larvária (ADL),
  visita a imóveis ou controle de criadouro, estas duas de rotina ou pendência. A
  atividade vai para o roteiro A4, para cada visita registrada no quarteirão e para o relatório.
  O administrador vê **＋ Novo trabalhador**: informa o e-mail de uma conta do site e
  ela entra na equipe "Combate à dengue" (revogável no painel da equipe).
- **Quarteirão dividido em L**: na agenda, "Dividir em L" reparte o quarteirão do dia
  entre duas pessoas. Cada uma fica com um L, os dois lados em torno de um canto
  (L Nordeste + L Sudoeste, ou L Noroeste + L Sudeste). O quarteirão é girado para
  ficar alinhado ao seu lado mais comprido; a diagonal entre os outros dois cantos
  separa os Ls, e nenhuma casa fica de fora ou nas duas metades. No mapa aparece a
  linha tracejada e o nome de cada pessoa no seu canto; na rua, a lista abre em
  "Meu L", a missão e "Salvar e próxima" contam só o seu L, e "Concluir meu L" fecha só
  a sua parte (o quarteirão conclui quando as duas metades concluem). Cada pessoa
  imprime o roteiro do seu L. "Juntar Ls" desfaz a divisão enquanto nenhuma parte foi concluída.
- **Relatório** (aba do escritório): hoje, ontem, últimos 7 dias ou um dia escolhido.
  Para cada dia, os totais (quarteirões concluídos, imóveis por situação, larva,
  tubitos, recipientes, controles, focal com Natular e com Vectobac, pendências
  recuperadas) e uma linha por quarteirão com atividade, responsáveis (com o L),
  visitados/previstos, recipientes por grupo A–G e se foi concluído. Imprime em A4
  e baixa em planilha (`…/relatorio.csv`).
- **Impressão A4**: prévia por dia, trabalhador ou quarteirão. Cada quarteirão
  tem cabeçalho, mapa vetorial, todos os endereços numerados da base, complementos,
  campos do boletim, linhas para imóveis adicionais, legenda e assinatura. Folhas
  seguintes repetem a identificação; endereços longos reduzem as linhas por folha.
  O mapa repete os nomes das vias de cada lateral, inclusive nas folhas sem casas
  daquela rua, usando os eixos do atlas. Os números da tabela ficam espaçados ao
  redor do desenho e ligados à posição do imóvel, sem sobrepor os círculos.
  Uma lateral sem nome disponível é indicada como não identificada na base.
  A ficha independe do zoom do mapa e funciona em preto e branco. O cadastro é a
  fonte dos imóveis previstos; imóveis ainda ausentes precisam ser acrescentados em campo.
- **Rua**: toca no número da casa e marca o resultado. A lista do quarteirão
  segue a ordem da volta (ângulo em torno do centro) e "Salvar e próxima" abre a
  casa seguinte ainda sem registro. Mostra a posição na rota, oferece filtros de imóveis
  sem registro e retornos, e exige escolher uma situação antes de mostrar os botões de salvar.
  Impede fechar alterações sem aviso, avisa sobre outra visita recebida com a ficha aberta,
  e mantém a ficha aberta se não consegue guardar a visita no aparelho. Dá para acrescentar imóvel que não está na lista:
  ele fica gravado em `entomologia_imovel_campo` e passa a fazer parte do mapa (base,
  roteiros, contagens e relatório) para toda a equipe daí em diante, na posição do
  aparelho quando houver (senão, no centro do quarteirão).
- **Ao vivo**: cada aparelho pergunta ao servidor a cada 8 s o que chegou depois
  do último registro que já tem; mapa, painel e placar se atualizam sozinhos.
- **Jogo**: missão do dia, pontos (10 por imóvel, 15 por pendência recuperada,
  50 por quarteirão concluído), níveis, medalhas e placar. Nenhum ponto depende
  de achar larva.

## Campos da visita

Os mesmos do arquivo oficial "Visita a Imóvel" que o painel já importa
(`scripts/import_entomologia.METRICS`):

| Campo | No boletim |
|---|---|
| Situação: trabalhado, fechado, desocupado, recusa (temporada e parcial seguem aceitas em registros antigos, mas não aparecem como opção) | IM TRAB, IM FECH, IM DESOC, IM TEMP, IM PARC, IM RECUSA |
| Recipientes existentes, com água, com larva | REC. EXIST., REC. AGUA, REC. LARVA |
| Imóvel com larva, tubitos coletados | IM. LARVA |
| Controle mecânico, alternativo, focal; larvicida do focal (Natular, Vectobac) | IM MECANICO, IM ALTERNATIVO, IM FOCAL |
| Recipientes por tipo (1 a 40, grupos A a G) | ficha de campo do SISAWEB |

**Tipos de recipiente**: na ficha do imóvel, "Anotar tipo de recipiente" abre a
lista da ficha do SISAWEB (A depósito elevado, B não elevado, C móveis, D fixos,
E pneus, F passíveis de remoção, G naturais). Cada tipo anotado tem existentes,
com água e com larva; com ao menos um tipo anotado, os totais do boletim passam
a ser a soma dos tipos. Sem tipo anotado, valem os totais digitados, como antes.
Cada linha de recipiente tem também o **controle feito nela**, um por linha:
mecânico, alternativo ou focal, e no focal o larvicida (Natular ou Vectobac). O mesmo
tipo pode ter várias linhas, cada uma com o seu controle. O controle anotado numa
linha marca o mesmo controle no imóvel. Marcar focal no imóvel também pede o larvicida.
`…/recipientes.csv` soma por dia, quarteirão e tipo, com os recipientes por controle
(mecânico, alternativo, focal Natular, focal Vectobac); `…/visitas.csv` traz larvicida,
atividade e os tipos de cada visita nas últimas colunas.

Recipientes e controles só valem para imóvel trabalhado ou parcial; o servidor
zera o resto e mantém existentes ≥ com água ≥ com larva. Espécie (aegypti,
albopictus) é resultado de laboratório e não é registrada aqui.

`…/boletim.csv` soma por dia e quarteirão nessas colunas (vale a última visita
de cada imóvel no dia); `…/visitas.csv` traz uma linha por visita.

## Cores

| Quarteirão | Quando |
|---|---|
| Amarelo claro | No plano, a fazer |
| Azul claro | Em andamento (plano em aberto com visita) |
| Verde claro | Concluído hoje |
| Pêssego tracejado | Planejado para outro dia |
| Lilás claro | Trabalhado nos últimos 7 dias |
| Cinza claro | Trabalhado há mais tempo (até 60 dias) |
| Branco | Sem trabalho recente |

A casa leva a cor do resultado da última visita; roxo quando há larva. Visita
anterior ao passe atual aparece só com o contorno. Depois de 60 dias
(`JANELA_DIAS`) a visita deixa de colorir: é hora de passar de novo.

**Passe**: começa no dia do plano em aberto do quarteirão e vai até alguém
concluir. O progresso conta as casas visitadas desde então. Visita em quarteirão
sem plano cria a linha do plano sozinha; uma linha por quarteirão e dia.

## Sem internet

- O service worker guarda a página e os arquivos dela; o aparelho guarda
  quarteirões, casas e o último estado (Cache Storage) e a fila de visitas
  (localStorage). Basta abrir uma vez com internet; o menu mostra "Pronto para
  funcionar sem internet".
- Sem sinal, as visitas ficam na fila e já colorem o mapa do próprio aparelho.
  Quando o sinal volta, vão sozinhas. Cada visita tem um identificador gerado no
  aparelho, então reenviar não duplica.
- O plano do escritório é feito com internet. Concluir quarteirão pode ser
  feito sem sinal e segue com a fila.
- Se a sessão terminar, o app avisa e pede para entrar de novo; a fila continua
  guardada.

## Acesso e dados

- Ler: administrador, equipe "Combate à dengue" ou token interno do SFA.
  Os primeiros agentes (lukemarki3 e cvorlandia, no Gmail) entram na equipe pela
  migration `e3b8f5a1c7d9`, se a conta existir; os demais são concedidos no
  painel da equipe, que também revoga.
  Planejar e registrar: só conta logada (administrador ou equipe), para cada
  marcação ter autor. O agente é sempre a conta que enviou.
- Tabelas `entomologia_quarteirao_trabalho` (plano por quarteirão, dia e parte:
  inteiro ou um L), `entomologia_visita_domiciliar` (visitas, imutáveis; corrigir é
  registrar outra) e `entomologia_imovel_campo` (imóveis acrescentados em campo).
  Migrations `d9a4c1e7b352`, `e3b8f5a1c7d9` (recipientes por tipo em `recipientes_json`)
  e `f4c9a2d6b8e1` (parte do L, atividade, larvicida do focal e imóveis de campo). Nenhum dado de morador é guardado: só
  endereço, resultado e agente.
- Código: `services/entomologia_casa_a_casa.py`,
  `blueprints/entomologia_fieldwork_routes.py`, `static/js/casa_a_casa.js`
  (tela), `static/js/casa_a_casa_planejamento.js` (escritório),
  `static/js/casa_a_casa_relatorio.js` (relatório), `static/js/casa_a_casa_impressao.js`
  (A4) e `static/js/casa_a_casa_model.js` (regras, inclusive a geometria do L, testadas em Node).
