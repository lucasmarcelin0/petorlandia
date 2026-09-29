# Simulações com voluntários (SFA)

Grupos de pessoas reais testando os formulários do estudo — Ficha SINAN, T0,
T7 e T30 — com casos fictícios. As respostas ficam só nas tabelas
`sfa_simulacao_*`: nada cria `SfaPaciente`, registro SINAN, resposta T0/T7/T30
real ou assinatura de TCLE.

## Como usar

1. Em **SFA › Simulações** (`/sfa/simulacoes`), crie um grupo por turma ou
   equipe (ex.: "Instituto · turma da professora", "Vigilância · equipe").
2. Escolha as etapas (o T0 é obrigatório) e como elas abrem:
   - **Sequencial imediata:** cada etapa abre logo após a anterior;
   - **Calendário do protocolo:** T7 no D7 e T30 no D30 do início dos sintomas
     informado no T0 (ou na ficha, se não houver T0).
3. (Recomendado) Escreva um **caso fictício compartilhado**: um texto geral e,
   se quiser, um por etapa. Ele aparece no topo de cada formulário.
4. Envie o **link de convite** (ou o QR code). Cada pessoa informa perfil e
   experiência com a ficha SINAN, recebe um código (P01, P02…) e um link
   pessoal para voltar depois. O navegador lembra o participante.
5. Ao fim de cada etapa há uma avaliação opcional: facilidade (1–5) e três
   perguntas abertas (o que ficou confuso, o que faltou, sugestões).

Quem perder o link pessoal: na página do grupo, botão **Link pessoal** copia o
link para reenviar. Testes da própria equipe podem ser excluídos por
participante. Um grupo com respostas não é excluído, só **encerrado**.

## Análise (`/sfa/simulacoes/analise`)

Marque um ou mais grupos. A coluna **Consolidado** soma os marcados como se
fossem um grupo único; as demais mostram cada grupo lado a lado ("Só o
consolidado" esconde as colunas por grupo).

- **Participação por etapa:** quantos enviaram cada etapa entre os que a
  tinham no percurso do grupo.
- **Tempo:** do momento em que o formulário foi aberto até o envio, incluindo
  tentativas com erro (instante assinado no próprio formulário). Mediana e
  faixa central (p25–p75), que resistem a quem deixou a página aberta.
- **Erros de validação:** quantos precisaram reenviar e quais campos barraram
  o envio (são as validações reais dos formulários).
- **Concordância:** parcela que deu a resposta mais comum (na múltipla
  escolha, semelhança média de Jaccard entre as combinações marcadas). Só faz
  sentido com um caso fictício compartilhado: abaixo de 70% sugere pergunta
  ambígua.
- **Diferença entre grupos:** maior diferença, em pontos percentuais, na
  proporção de uma mesma opção entre grupos com ao menos 3 respostas.
- **Preenchimento:** entre quem viu a pergunta (as condicionais só aparecem
  para parte das pessoas).
- **Coerência SINAN × T0:** quantos informaram início dos sintomas diferente
  na ficha e no T0.

Exportações: **CSV por participante** (uma linha por pessoa, etapas lado a
lado) e **CSV por pergunta** (formato longo, uma linha por pergunta de cada
etapa, pronto para tabela dinâmica ou R).

## Privacidade

Os formulários pedem para usar dados fictícios, mas os identificadores diretos
nunca são gravados, mesmo se alguém digitar dados reais: nome, nome da mãe,
cartão SUS, telefone, endereço (logradouro, número, complemento, CEP, ponto de
referência, georreferência), nome e assinatura do investigador e o nome de
quem responde por outra pessoa no T0/T30. Fica só a marca `[preenchido]`, que
permite medir o preenchimento. O número da ficha digitado não é cruzado com o
SINAN real.
