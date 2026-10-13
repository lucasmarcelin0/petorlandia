# Casa a casa

App de campo em `/sfa/entomologia/casa-a-casa`, aberto pela aba "Casa a Casa" do
painel do território, pelo cartão "Combate à dengue" da página inicial e pela
barra lateral do SFA. Tela própria, leve, pensada primeiro para o celular.

## O que faz

- **Mapa em branco**: só os quarteirões da malha de campo (`territory.json`),
  com o número de cada um. Ao aproximar aparecem as casas (endereços numerados
  do atlas, CNEFE com as correções da equipe) e, bem perto, o número de cada casa.
  Não depende de imagem de fundo; "ruas ao fundo" é opcional e precisa de internet.
- **Escritório**: escolhe o dia e o agente e clica nos quarteirões para pôr ou
  tirar do plano. O painel "Ao vivo" mostra totais do dia, quarteirões em aberto,
  placar da equipe e os últimos registros.
- **Rua**: toca no número da casa e marca o resultado. A lista do quarteirão
  segue a ordem da volta (ângulo em torno do centro) e "Salvar e próxima" abre a
  casa seguinte ainda sem registro. Dá para acrescentar imóvel que não está na lista.
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
| Situação: trabalhado, fechado, desocupado, temporada, parcial, recusa | IM TRAB, IM FECH, IM DESOC, IM TEMP, IM PARC, IM RECUSA |
| Recipientes existentes, com água, com larva | REC. EXIST., REC. AGUA, REC. LARVA |
| Imóvel com larva, tubitos coletados | IM. LARVA |
| Controle mecânico, alternativo, focal | IM MECANICO, IM ALTERNATIVO, IM FOCAL |

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
  Planejar e registrar: só conta logada (administrador ou equipe), para cada
  marcação ter autor. O agente é sempre a conta que enviou.
- Tabelas `entomologia_quarteirao_trabalho` (plano por quarteirão e dia) e
  `entomologia_visita_domiciliar` (visitas, imutáveis; corrigir é registrar
  outra). Migration `d9a4c1e7b352`. Nenhum dado de morador é guardado: só
  endereço, resultado e agente.
- Código: `services/entomologia_casa_a_casa.py`,
  `blueprints/entomologia_fieldwork_routes.py`, `static/js/casa_a_casa.js`
  (tela) e `static/js/casa_a_casa_model.js` (regras, testadas em Node).
