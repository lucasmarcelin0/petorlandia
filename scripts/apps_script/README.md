# Apps Script da planilha de vacinação

`vacinacao_2026.gs` é a cópia versionada do script que roda **dentro** da
planilha de vacinação (menu "🐾 Vacinação 2026"). O Google não versiona esse
código: editar aqui e colar lá é o que impede a correção de se perder na
próxima vez que alguém mexer no editor.

## Como publicar uma alteração

1. Abrir a planilha → **Extensões → Apps Script**.
2. Selecionar todo o conteúdo do arquivo do projeto e substituir pelo conteúdo
   de `vacinacao_2026.gs`.
3. Salvar. Recarregar a planilha para o menu ser recriado.

## Configuração obrigatória (uma vez)

O token dos webhooks **não fica no código**. No editor do Apps Script:

**Configurações do projeto → Propriedades do script → Adicionar propriedade**

| Propriedade | Valor                                    |
|-------------|------------------------------------------|
| `PMO_TOKEN` | o mesmo valor de `PMO_SYNC_WEBHOOK_TOKEN` do app |

Sem isso, "Atualizar status" e "Compilar Controle de doses" avisam que a
propriedade falta, em vez de falhar em silêncio.

## O que esta versão corrige

- **Coluna de carimbo.** A aba `Vacinação 2026` vem do formulário e tem o
  carimbo de data/hora na coluna A; as abas do dia começam direto no nome do
  tutor. O script detecta isso por aba (`detectarOffset_`). Antes, na aba
  mestre tudo era lido uma coluna à esquerda: o link do mapa saía como
  "Raquel Feliciano Rua 4, A, 1299" e a mensagem de WhatsApp levava endereço e
  data trocados.
- **Reordenação preserva nota e cor.** `routeOptimizeByCluster` usava
  `clearContent()`, que apaga valores mas não apaga notas nem cor de fundo —
  depois de reordenar, a nota/cor de status de um tutor ficava no cadastro de
  quem passou a ocupar a linha. Agora valores, notas e cores são reordenados
  juntos.
- **Nenhuma linha é descartada** na otimização (as não classificadas vão para o
  fim) e as colunas auxiliares (`Cluster`, `Bairro Normalizado`, `Link do
  Mapa`, `WhatsApp 1/2`) são reaproveitadas em vez de duplicadas a cada
  execução.
- **`sincronizarPlanilhas` limpa nota e cor** junto com o conteúdo, já que
  recolar a base inteira reposiciona todos os tutores.

## Depois de reordenar ou re-sincronizar

Rodar **"🔄 Atualizar status (PetOrlândia)"**. É essa execução que recompila o
Status PMO nas posições novas — e, desde a correção do backend, ela confere o
nome/telefone de cada linha antes de escrever e apaga status que tenha sobrado
no cadastro de outro tutor.
