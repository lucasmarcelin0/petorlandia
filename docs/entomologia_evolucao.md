# Entomologia: clareza, automação e transparência

Proposta e primeira entrega • 28/09/2026 • complementa [entomologia.md](entomologia.md)
e [plano_vigilancia_orlandia.md](plano_vigilancia_orlandia.md).

O painel `/sfa/entomologia` já organizava bem a leitura dos dados, mas tinha três
limites práticos: os números só mudavam quando alguém rodava um script e publicava
o código; o trabalho da equipe não aparecia como progresso; e nada chegava à
população. Esta entrega ataca os três pontos sem remover nenhuma tela, filtro,
exportação ou regra existente.

## O que mudou

### 1. Clareza e gamificação — aba **Equipe**

Nova aba inicial do painel, calculada no navegador a partir da mesma base:

| Bloco | O que mostra |
|---|---|
| Manchete da semana | Quarteirões, setores, preenchimento de larvas e sequência de semanas com envio |
| O que fazer agora | Dados desatualizados, focos recentes **sem ação aberta**, ações vencidas e ações executadas aguardando verificação |
| Progresso rumo às metas | Semana em andamento contra a média das 4 semanas anteriores com registro |
| Conquistas | Avaliadas na última semana completa: Território em movimento, Registro que orienta, Portas abertas, Criadouro fora, Ciclo fechado e Sequência |
| Histórico de 8 semanas | Quais conquistas a equipe obteve em cada semana |
| Ciclo de dois meses | Quarteirões visitados no ciclo sobre os quarteirões já vistos em cada setor |
| Recordes | Melhores semanas da própria equipe |

Escolhas deliberadas:

- **Metas relativas à própria equipe**, não percentuais arbitrários (o plano de
  vigilância pede linha de base verificada antes de metas absolutas).
- **Premia qualidade, acesso e fechamento do ciclo**, não o número de focos, para
  não criar incentivo a registros enviesados.
- **Sem ranking individual**: LOGIN e AGENTE nunca entram na base.
- A semana em andamento mostra progresso; conquistas só valem para semanas completas.

### 2. Automação

- **Atualizar dados sem deploy** (`/sfa/entomologia/atualizar`, também na barra
  lateral): envia o CSV/ZIP “Visita a Imóvel”. O arquivo é lido com o mesmo
  importador validado, LOGIN e AGENTE são descartados, e uma **prévia dia a dia**
  mostra dias novos, dias substituídos e avisos (dias que perderiam registros,
  datas futuras, setores fora da malha). Só depois da confirmação os painéis mudam.
- **Regra de consolidação**: cada envio substitui integralmente os dias que contém.
  Serve tanto para o arquivo do dia quanto para o acumulado do ano, sem somar duas
  vezes. **Desfazer** devolve os dias à versão anterior. Tudo fica auditado
  (`sfa_auditoria`, categoria `ENTOMOLOGIA`) com responsável.
- **Quem pode alterar**: enviar, confirmar, desfazer, publicar e retirar exigem
  conta de **administrador logada** (cada alteração fica atribuída a uma pessoa).
  O token interno do SFA continua abrindo o painel e a tela de atualização, só
  para leitura. Criar ação pelo Planejamento segue a regra já existente de
  Organização do trabalho.
- A fotografia versionada em `services/data/entomologia` continua sendo a base e
  nunca é alterada pelo servidor. Sem banco disponível, o painel usa a fotografia.
- **Planejamento → Ação em um clique**: cada território das listas de revisão tem
  “Criar ação”, com tipo, motivo e objetivo já redigidos a partir dos números. A
  ação entra em Organização do trabalho (ABERTA → EXECUTADA → VERIFICADA) e a lista
  passa a indicar os setores que já têm ação aberta.
- **Roteiro imprimível** da lista de revisão.
- **Camadas do Google Earth**: um projeto exportado em KML/KMZ (menu ⋮ → Exportar
  como arquivo KML) vira camada do mapa interno da aba Entomologia, com nome,
  descrição (texto) e pasta. XML é lido com `defusedxml`; coordenadas e tamanho são
  validados. Camadas nunca vão para a página pública.

### 3. Dados úteis para a população — página **/aedes**

Página pública, sem login, que só mostra o **último boletim publicado pela equipe**
em “Atualizar dados → Boletim para a população”:

- quarteirões percorridos, imóveis trabalhados, imóveis com remoção de criadouros,
  regiões com foco e percentual de visitas com resultado registrado;
- mapa por setor censitário: foco encontrado, sem foco nas visitas com resultado,
  resultado não informado, sem visita no período; toque mostra a última visita;
- “Usar minha localização” localiza o setor **no próprio aparelho** (nada é enviado);
- ritmo semanal, mensagem e contato da equipe, checklist “10 minutos” (inclui
  bebedouro de animais) e “Quando o agente bater à sua porta”, que ataca a maior
  perda de trabalho da base: imóveis fechados e recusas;
- “Como ler estes números” explica revisitas, vazio ≠ zero e por que não é índice.

Sem boletim publicado, a página mostra apenas as orientações. Há prévia interna
antes de publicar e o botão “Retirar do ar”. O boletim guarda somente agregados por
setor; a malha pública leva apenas geometria, código e situação do setor.

## Como usar no dia a dia

1. Ao fim do dia (ou da semana), exporte “Visita a Imóvel” e envie em **Atualizar dados**.
2. Confira a prévia; se algum dia perder registros, verifique se a exportação tem toda a equipe.
3. Abra a aba **Equipe**: siga “O que fazer agora” e acompanhe as metas.
4. No **Planejamento**, transforme candidatos em ações e imprima o roteiro.
5. Uma vez por semana, confira a prévia do boletim e publique.

## Próximos passos sugeridos

Ordenados pelo retorno esperado com o menor esforço da equipe.

| Frente | Proposta | Por que |
|---|---|---|
| Automação | **QR “Passamos aqui”** no aviso deixado em imóvel fechado, com agendamento do retorno | Fechados somam 13.571 ocorrências na base; é a maior perda de inspeção |
| Automação | **Coleta digital no celular (offline)**: visita, motivo de fechado/recusa, foto do criadouro e posição | Elimina digitação, separa zero de não examinado e alimenta o painel no mesmo dia |
| Automação | **Pasta monitorada no Google Drive** para a exportação diária | Atualização sem nenhum clique |
| Automação | **Rascunho automático do boletim** toda segunda-feira, aprovado com um clique | Transparência contínua sem trabalho extra |
| Clareza | **Lista oficial de quarteirões** (camada do Google Earth) como universo do ciclo | Cobertura exata em vez de “quarteirões já vistos” |
| Clareza | **Modo mural** da aba Equipe para TV da sala | Metas visíveis no início do dia |
| Integração | Cruzar focos com episódios SFA/SINAN por semana e setor validado | A comparação semanal já existe; falta a fonte municipal completa |
| População | **QR code no crachá e nos panfletos** apontando para /aedes | Confiança no agente e menos recusas |
| População | **Aviso de foco pelo morador**, com foto e localização, moderado pela equipe | Vira ação no mesmo fluxo de trabalho |
| População | **Dados abertos**: CSV agregado por setor e semana | Pesquisa, imprensa e conselho de saúde |

## Sobre o projeto do Google Earth

O link compartilhado (`earth.google.com/earth/d/1eruMbx5…`) não pôde ser aberto por
aqui: o Google Earth Web não carrega fora do navegador e o arquivo não está visível
no Google Drive conectado. Para incorporá-lo, exporte o projeto como KML (menu ⋮ do
projeto → Exportar como arquivo KML) e envie em **Atualizar dados → Camada de mapa**.
Se ele contiver os quarteirões oficiais, o próximo passo é usá-los como universo do
ciclo na aba Equipe.

## Implantação

- Migração `f1e7a3c9b2d4` cria `entomologia_importacao` e `entomologia_publicacao`
  (somente tabelas novas; nenhuma coluna existente muda).
- Nova rota pública: `/aedes` (`vigilancia_publica.painel_aedes_publico`).
- Testes: `tests/test_entomologia_atualizacao.py` (inclui os testes JS de
  entomologia, agora executados também pela CI) e `tests/test_entomologia_team_model.js`.
