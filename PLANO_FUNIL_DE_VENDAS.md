# Funil de vendas — onde ele vaza hoje e o que fazer

Diagnóstico feito lendo o código do funil que está em produção (`main` = v997),
não a partir de boas práticas genéricas. Cada item aponta o arquivo e a linha
que produzem o comportamento descrito.

## O que já existe (e não precisa ser refeito)

Vale registrar antes de propor qualquer coisa, porque a base é melhor do que a
maioria dos produtos nesta fase:

- Eventos de funil próprios, com anônimo/sessão e UTM, gravados no banco —
  `services/product_analytics.py:93`.
- Painel de funil de aquisição e de loja — `blueprints/admin.py:124` e `:142`.
- Régua de retenção e recuperação já agendada em `scheduler.py`: lembrete de fim
  de avaliação (`app.py:8767`), win-back pós-trial (`app.py:8868`) e carrinho
  abandonado (`app.py:8950`).
- Passos de ativação calculados do uso real, e não de um checklist estático —
  `services/activation.py`.
- Página de preço pública, sem login (`blueprints/site.py:885`), e intenção de
  plano preservada do preço até o checkout (`blueprints/auth.py:296`).

O funil não está quebrado por falta de estrutura. Ele vaza em pontos
específicos, e é neles que está o dinheiro.

---

## P0 — Receita parada

### 1. Dono de clínica que não é veterinário nunca entra na régua de cobrança

**Hoje:** a assinatura só nasce a partir de um perfil de veterinário —
`ensure_veterinarian_membership` recebe `veterinario`, não `user`
(`helpers.py:192`). Na criação da clínica, o perfil profissional só é concedido
se a pessoa marcar "sou veterinário" e informar CRMV
(`blueprints/clinica.py:361-368`).

Consequência: quem cria a clínica como dono, recepção ou administrador tem
clínica ativa, mas **não tem avaliação, não tem cobrança, não recebe lembrete de
fim de trial, não entra no win-back**, e recebe 403 em `/veterinario/assinatura`
(`blueprints/site.py:172-181`). O produto fica gratuito por tempo indeterminado
para uma conta que já demonstrou a intenção mais forte que existe: cadastrar a
própria clínica.

**Conserto:** ancorar a assinatura na **clínica**, não no CRMV. A avaliação
começa quando a clínica é criada; o responsável pela clínica (`owner_id`) é
quem configura o pagamento. O CRMV continua sendo o que é de fato — requisito
para assinar prontuário e publicar perfil —, não porteiro do faturamento.

*Tamanho:* médio (toca modelo de membership e as três réguas). *É o item de
maior impacto direto em receita.*

### 2. O lead mais quente do funil morre no banco

**Hoje:** `WaitlistLead` é gravado (`blueprints/site.py:960-1010`) e só pode ser
lido no Flask-Admin (`admin.py:738`). Não há e-mail de confirmação para o lead,
não há `notify_admins`, não há job de follow-up.

Um `feature='demo_clinica'` é alguém pedindo demonstração — o hand-raiser mais
qualificado do funil inteiro. Compare com o tratamento dado a uma clínica nova,
que já dispara `notify_admins` (`blueprints/clinica.py:373`).

**Conserto (uma tarde):**
1. `notify_admins` no ato para `demo_clinica`, com contato e cidade.
2. Confirmação automática para o lead — "recebemos, entramos em contato em até
   X horas" — que já é a primeira mensagem da conversa comercial.
3. Coluna de status no admin (`novo / contatado / demo marcada / perdido`) para
   que a lista vire fila de trabalho, e não arquivo morto.

### 3. Quem se cadastra sozinho não recebe nada por e-mail — e o e-mail nunca é verificado

**Hoje:** `register` (`blueprints/auth.py:291`) cria a conta, loga e redireciona.
Nenhum `notify_user`, nenhuma confirmação. O acolhimento por e-mail existe só
para quem chega por convite (`_first_access_welcome`, `blueprints/auth.py:164`).

Dois efeitos:

- Quem sai da sessão não tem **nada** na caixa de entrada puxando de volta. O
  onboarding é a única superfície de retorno, e ela exige que a pessoa lembre
  de voltar sozinha.
- Toda a régua de receita — trial, win-back, carrinho — depende de e-mail
  válido (`services/notifications.py:185`). Um e-mail digitado errado no
  cadastro não é detectado em lugar nenhum: o lead fica inalcançável para
  sempre e some silenciosamente das três réguas.

**Conserto:** e-mail de boas-vindas no cadastro (com o próximo passo concreto do
perfil escolhido, não um "bem-vindo!"), e um link de confirmação cujo único
efeito é marcar `email_verificado`. Não bloqueie o uso por falta de confirmação
— bloquear derruba ativação; o objetivo aqui é saber quais endereços são
entregáveis e mostrar isso no admin.

---

## P1 — A medição está errada, e decisão sobre número errado custa caro

### 4. As taxas do funil somam eventos, não pessoas

**Hoje:** `blueprints/admin.py:110` conta `func.count(ProductEvent.id)`. Então
`landing_viewed` cresce a cada visita — inclusive a segunda e a terceira da
mesma pessoa —, enquanto `signup_completed` acontece uma vez por conta. A
"conversão de cadastro" exibida é sistematicamente menor que a real, e piora
quanto melhor for a retenção da landing.

**Conserto:** contar `count(distinct anonymous_id)` por etapa, e calcular a taxa
sobre a mesma base de pessoas. `ProductEvent` já guarda `anonymous_id` e
`session_id` — não falta dado, falta a agregação certa. Um passo além, quando
valer a pena: coorte por semana de primeira visita, para responder "de quem
chegou em julho, quantos assinaram", que é a pergunta que decide investimento
em canal.

### 5. O trecho do funil onde a venda realmente acontece não é medido

**Hoje:** o funil de aquisição vai de `landing_viewed` → `signup_completed` →
`onboarding_viewed` → `trial_converted` (`blueprints/admin.py:124`). Entre o
onboarding e a conversão há semanas de trabalho e **nenhum evento**: não existe
`clinic_created`, `first_patient_created`, `first_appointment_created`,
`payment_method_added`.

Os passos de ativação já são calculados (`services/activation.py`) — só nunca
viram evento. Quando o trial não converte, hoje não dá para dizer se a pessoa
parou antes de cadastrar a clínica, antes do primeiro paciente ou na tela de
pagamento. São três problemas diferentes com três consertos diferentes.

**Conserto:** emitir os quatro eventos acima nos pontos onde o fato acontece, e
desenhar o funil de ativação com eles. É a mudança de menor custo e maior
retorno informacional da lista.

### 6. Eventos de CTA destroem a própria atribuição

**Hoje:** `track_event` grava `utm_source=(source or attribution["utm_source"])`
(`services/product_analytics.py:137`), e o endpoint de CTA chama
`track_event(name, source='cta', ...)` (`blueprints/site.py:1046`).

Resultado: **todo clique de CTA é gravado com `utm_source='cta'`**, apagando a
campanha que trouxe a pessoa. No painel de origens (`blueprints/admin.py:186`),
`cta` aparece como se fosse canal de aquisição e infla a contagem de anônimos.

**Conserto (dez linhas):** separar as duas dimensões. `source` é superfície do
evento e merece coluna própria (ou entra em `properties`); `utm_source` deve
sempre vir da atribuição da sessão.

### 7. `checkout_abandoned` mede o job de e-mail, não o abandono

**Hoje:** o evento só é emitido dentro do job diário de lembrete
(`app.py:9032`), depois de mandar o e-mail. Carrinho de usuário sem e-mail
utilizável, carrinho fora do lote de 200 (`app.py:8973`) ou carrinho abandonado
e retomado antes das 24h (`ABANDONED_CART_HOURS`, `app.py:8947`) nunca contam.
O número que aparece como "abandonos" no painel é, na verdade, "lembretes
enviados".

**Conserto:** derivar abandono da diferença entre `checkout_started`
(`blueprints/loja.py:2200`) e `purchase_completed` na mesma janela, e renomear a
métrica do job para `cart_reminder_sent` — que também é útil, mas é outra coisa.

---

## P2 — Atrito que dá para tirar rápido

### 8. A loja perde a intenção no muro de login

**Hoje:** para quem não está logado, o botão do produto é "Entrar para comprar"
com `next` apontando de volta para a página do produto
(`templates/loja/product_detail.html:118-123`). Depois do login, a pessoa
retorna à página e precisa clicar de novo — a quantidade escolhida e a intenção
se perderam. E a única porta oferecida é **entrar**: para um comprador de
primeira viagem, que não tem conta, o CTA aponta para a ação que ele não pode
fazer.

**Conserto:** guardar `pending_cart_item` na sessão, executar a adição logo após
a autenticação e cair direto no carrinho; e oferecer "criar conta" com o mesmo
destaque de "entrar" — inclusive o Google, que já existe
(`blueprints/auth.py:547`) e é o caminho de menor atrito no celular.

### 9. As réguas de recuperação usam um canal só, e um toque só

**Hoje:** `notify_user` envia e-mail + notificação interna
(`services/notifications.py:185`). O carrinho abandonado tem **um único toque**,
travado por `abandoned_reminder_at` (`models/loja.py:467`).

Enquanto isso o produto já tem web push funcionando (`services/push.py:80`),
usado para lembretes de vacina e consulta (`app.py:8537`) — mas **nenhuma** das
três réguas de receita o utiliza. E existe até um caminho de WhatsApp em uso
para a pesquisa de ração (`blueprints/loja.py:561`).

**Conserto:** somar push às três réguas (custo marginal zero, entrega imediata,
já consentido) e transformar o carrinho num toque duplo — 24h e 72h — com corte
por valor de carrinho para não gastar frequência com pedidos irrelevantes.

### 10. O "30 dias grátis, sem cartão" cobra um formulário antes de existir

**Hoje:** a headline promete avaliação sem cartão
(`templates/public_home.html:47-49`) e o CTA leva a
`register?next=/minha-clinica`. Mas a avaliação só nasce depois do cadastro
**e** do formulário de clínica — nome, CNPJ, endereço, telefone, e-mail, CRMV,
frete, prazos (`blueprints/clinica.py:335-344`). São dois formulários entre o
clique e a promessa.

**Conserto:** pedir na criação da clínica apenas nome e cidade, iniciar a
avaliação ali, e mover CNPJ, frete e prazos para onde eles realmente importam —
o momento de publicar o perfil e o de vender. O resto do cadastro já tem lugar
natural: os passos de ativação.

---

## Ordem sugerida

| Sprint | Itens | Por quê nessa ordem |
|--------|-------|---------------------|
| 1 | 5, 4, 6 | Sem medir certo o trecho que converte, os outros consertos viram achismo. Custo baixo, todos em código já existente. |
| 2 | 2, 3, 8 | Recuperam lead que hoje se perde inteiro, e são rápidos. |
| 3 | 1, 10 | Maior impacto em receita, maior toque no modelo — depois que o painel já mostrar o efeito. |
| 4 | 9, 7 | Ajuste fino de frequência e de métrica. |

## Como saber se funcionou

Definir a linha de base **antes** do sprint 1, com as contagens por pessoa (item
4), e acompanhar quatro números:

1. Visitante único da landing → cadastro.
2. Cadastro → clínica criada → primeiro agendamento (o funil de ativação do
   item 5).
3. Trial → assinatura paga, por coorte de entrada.
4. `checkout_started` → `purchase_completed` na loja, medido pela diferença
   (item 7), com o valor médio do carrinho ao lado.

Nenhum deles depende de ferramenta nova: os quatro saem de `ProductEvent` com as
agregações corrigidas.
