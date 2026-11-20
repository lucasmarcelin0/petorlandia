# Campanha dos primeiros clientes — clínicas veterinárias
**Base: Orlândia-SP | Disponibilidade: meio período (~3h/dia) | Atualizado em nov/2026**

Este é o passo a passo para conseguir as primeiras clínicas pagantes e deixar a
aquisição rodando quase sozinha. A parte técnica (o que o sistema já faz
automaticamente) está na seção 3; o que depende de você está nas seções 4 a 8.

---

## 1. Oferta e posicionamento

**Para quem:** clínica veterinária pequena (1 a 3 veterinários) do interior,
que hoje controla agenda no papel/WhatsApp e prontuário em caderno ou Word.
Ribeirão Preto e capitais vêm depois — comece onde você é conhecido.

**A dor que você resolve (nessa ordem):**
1. *"Onde está o histórico desse animal?"* — prontuário, vacinas e exames num lugar só.
2. *"Quem está marcado amanhã?"* — agenda da equipe inteira, com lembretes.
3. *"Quanto eu faturei esse mês?"* — financeiro que fecha, sem planilha paralela.

**Frase de uma linha:** "Agenda, prontuário e financeiro da clínica num lugar
só, feito aqui em Orlândia — e a gente configura junto com você."

**A oferta (não mude no meio da campanha):**
| Item | Condição |
|---|---|
| Preço | R$ 60/mês por veterinário (recepção e pacientes ilimitados) |
| Teste | 30 dias completos, sem cartão |
| Implantação | Grátis: importamos a planilha de clientes e deixamos a agenda pronta em 30 min |
| Compromisso | Sem fidelidade, sem taxa de instalação, sem comissão sobre consultas |
| Segurança | Cancelou? Nada é apagado. Exporta tudo quando quiser |
| Indicação | Quem indica ganha 1 mês grátis quando a indicada assina; a indicada ganha +15 dias de teste |

**Argumentos de confiança (todos verdadeiros e verificáveis no sistema):**
- Cada pessoa da equipe vê só o que o dono permitir; o financeiro é só do responsável.
- O financeiro mostra de onde vem cada número: pagamento conta uma vez,
  orçamento recusado/cancelado fica de fora, venda da loja só entra depois de paga.
- Planilha pronta para o contador (botão no Financeiro). Impostos aparecem como
  estimativa — a apuração oficial é do contador. **Nunca prometa que substitui o contador.**
- Exportação completa dos dados da clínica (pacientes, tutores, agenda,
  consultas, orçamentos) pelo dono.

---

## 2. Preparação (faça uma vez, antes da semana 1)

**Configuração do sistema (Heroku → Settings → Config Vars):**
- [ ] `SUPPORT_PHONE` = o seu WhatsApp comercial. Ele aparece nos e-mails de
  ativação, na landing e na tela de boas-vindas. Hoje o padrão é um número fixo
  no código — confirme que é o seu.
- [ ] Sua conta **admin** com um e-mail que você lê no celular: o alerta de
  demonstração, o aviso de clínica nova e o resumo diário vão para o e-mail
  de todas as contas com papel admin (e ficam também no painel admin).
- [ ] E-mail de envio (`MAIL_*`) funcionando. Teste pedindo uma demonstração
  com o seu próprio e-mail em `/parceiros/clinica`: você deve receber o alerta
  e a confirmação.

**Presença local:**
- [ ] **Perfil da Empresa no Google** ("PetOrlândia — software para clínicas
  veterinárias", categoria *Empresa de software*), com o link
  `https://www.petorlandia.com.br/parceiros/clinica?utm_source=google&utm_medium=perfil`.
- [ ] **Instagram** `@petorlandia` com a bio: "Sistema para clínicas
  veterinárias | Orlândia-SP | 30 dias grátis" + link da landing com
  `?utm_source=instagram&utm_medium=bio`.
- [ ] **Vídeo de 90 segundos** gravado na tela do celular: agenda → abrir
  paciente → histórico → financeiro do mês. Use dados de demonstração, nunca
  de cliente real.
- [ ] **Uma clínica-vitrine** com dados fictícios para as demos (paciente,
  vacinas, orçamento pago, um orçamento recusado — para mostrar que ele fica
  fora do faturamento).

**Lista de prospecção (planilha simples):**
| Nome | Cidade | Telefone | Instagram | Grupo | Etapa | Próximo passo | Data |
|------|--------|----------|-----------|-------|-------|---------------|------|

Pesquise no Google Maps "clínica veterinária", "veterinário" e "pet shop com
veterinário" em Orlândia, São Joaquim da Barra, Guará, Bebedouro, Jardinópolis,
Sertãozinho e Franca. Meta: 50 estabelecimentos.

Grupos: **A** = você conhece · **B** = Orlândia, não conhece (visita) ·
**C** = cidades vizinhas (WhatsApp/Instagram).

Etapas: `mapeado → contatado → conversa marcada → demo feita → em teste → ativado → pagante`.

---

## 3. O que já funciona sozinho (o "automático")

```
Canal (visita, WhatsApp, Instagram, Google, indicação)
  └─► Landing /parceiros/clinica  (preço, confiança, FAQ, WhatsApp)
        ├─► "Agendar demonstração" ─► VOCÊ recebe alerta na hora (e-mail + painel)
        │                              com link de WhatsApp pronto; o lead recebe confirmação
        └─► "Começar 30 dias grátis" ─► cadastro ─► cria a clínica ─► VOCÊ recebe alerta
              └─► /comecar: checklist de ativação + faixa que acompanha o app
                    ├─ D+1, D+4, D+10: e-mail com o passo que falta (só p/ quem travou)
                    ├─ D-5, D-1, D0: aviso de fim do teste (diz exatamente o que vai acontecer)
                    └─ D+3, D+10 após o fim: retomada para quem não assinou
Todo dia 07:40: RESUMO DE AQUISIÇÃO no seu e-mail — leads, clínicas novas,
avaliações travadas e avaliações acabando, cada um com o link de contato.
```

O sistema avisa e lembra; **quem fecha é você**. A regra de ouro: lead de
demonstração respondido **em até 1 hora** fecha muito mais do que no dia seguinte.

**Links com UTM** (o sistema registra a origem de cada visita/cadastro):
`/parceiros/clinica?utm_source=<canal>&utm_medium=<tipo>&utm_campaign=primeiros-clientes`
— use `whatsapp`, `instagram`, `google`, `visita` (QR code), `indicacao`.

---

## 4. Calendário da campanha (4 semanas)

### Semana 1 — Rede próxima e Orlândia

| Dia | Tarefa (≈3h) | Meta |
|---|---|---|
| Seg | Mapeamento (seção 2) e separação A/B/C | 30–50 na lista |
| Ter | Mensagem pessoal para **todo o grupo A** (script 7.1) | 2 conversas marcadas |
| Qua | Visita presencial a 3–4 clínicas do **grupo B** (script 7.2), com QR da landing | 3 contatos com nome + WhatsApp |
| Qui | Primeiras demos (roteiro, seção 5) | 2 demos |
| Sex | Follow-up de quem não respondeu (script 7.5) + publicar vídeo de 90 s | 1–2 em teste |

### Semana 2 — Região e primeiras implantações

- **Todo dia, 15 min:** ler o resumo de aquisição e fazer os contatos dele.
- Grupo C por WhatsApp (script 7.3): 10 clínicas/dia útil.
- Para cada clínica que entrou em teste: **ligar em até 24 h** e marcar a
  implantação de 30 min (seção 6). Clínica que não importou os clientes na
  primeira semana raramente assina.
- Instagram: 3 vídeos curtos (problema → solução → para quem é), um por dia útil alternado.

### Semana 3 — Prova social

- Peça às clínicas em teste que estão usando de verdade (resumo diário mostra
  quem *não* travou) um depoimento de 2 frases + foto. Publique com autorização.
- Ative a indicação: cada clínica ativa recebe o link de `/indicacao` (script 7.6).
- Contato com professores de faculdade de veterinária da região: o espaço do
  estudante é gratuito e forma os próximos clientes.

### Semana 4 — Conversão

- Avaliações chegando ao fim aparecem no resumo diário: ligue para cada uma
  **antes** do D-5 (script 7.7). O e-mail automático não substitui a ligação.
- Quem terminou sem assinar recebe a retomada automática; para os que usaram
  bastante, ofereça uma conversa de 15 min para entender o que faltou.

---

## 5. Roteiro da demonstração (15 minutos)

Mostre **quatro telas**, sempre com a clínica-vitrine:

1. **Agenda** (3 min) — "Hoje você confirma consulta por ligação ou WhatsApp?"
   Mostre a agenda da equipe e os lembretes.
2. **Prontuário** (4 min) — "Onde fica o histórico do animal hoje?" Abra um
   paciente: vacinas, exames, prescrições, orçamentos.
3. **Financeiro** (4 min) — "Você sabe quanto faturou este mês sem calcular?"
   Abra o Financeiro, clique em **"Como chegamos a estes números"** e mostre o
   orçamento recusado fora do faturamento. Mostre a planilha do contador.
4. **Segurança** (2 min) — permissões da equipe e a exportação de dados.

Feche com: *"Isso faria diferença na sua rotina?"* → *"São 30 dias grátis, sem
cartão. Quer que eu crie a conta agora com você e já importe sua lista de clientes?"*

**Faça o cadastro junto, na hora.** Cadastro deixado "para depois" esfria.

---

## 6. Primeiro contato com a plataforma (o que a clínica vive)

| Momento | O que o sistema faz | O que você faz |
|---|---|---|
| Cadastro (1 min) | Nome, e-mail e senha | — |
| Criação da clínica | Nome + CRMV; ativa o teste de 30 dias; avisa você | WhatsApp de boas-vindas no mesmo dia (link no resumo) |
| `/comecar` | Checklist: horários → 1º paciente → 1º agendamento | — |
| Dias seguintes | Faixa de ativação em todas as telas; e-mails D+1/D+4/D+10 se travar | Implantação de 30 min: importar planilha, horários, 1º agendamento |
| Uso diário | Agenda, prontuário, financeiro | Pergunta na 2ª semana: "o que está te atrapalhando?" |
| D-5 a D0 | E-mails de fim de teste | Ligação de decisão (script 7.7) |
| Assinou | Assinatura recorrente via Mercado Pago | Pede indicação e depoimento |

**Implantação de 30 minutos (checklist):**
- [ ] Logo, telefone e endereço da clínica
- [ ] Horários de atendimento
- [ ] Equipe cadastrada com as permissões certas (recepção ≠ veterinário)
- [ ] Planilha de clientes importada (`Importar planilha` na clínica)
- [ ] Serviços e preços mais comuns cadastrados (aceleram o orçamento)
- [ ] Um agendamento real de amanhã criado junto
- [ ] Mostrar o Financeiro e o botão da planilha para o contador

---

## 7. Scripts (copie e use)

**7.1 Rede próxima (WhatsApp)**
> "Oi [nome]! Tudo bem? Tô desenvolvendo um sistema para clínicas veterinárias
> aqui de Orlândia e queria muito a sua opinião. São 15 minutinhos. Você tem
> um tempo essa semana ou na próxima?"

**7.2 Visita presencial (recepção)**
> "Oi, sou o [nome], aqui de Orlândia mesmo. Desenvolvi um sistema de agenda,
> prontuário e financeiro para clínicas veterinárias e queria conversar 10
> minutinhos com o veterinário responsável. Não é venda agora — quero a
> opinião de quem trabalha na área."
Saia com: nome do responsável, WhatsApp e uma data. Deixe o cartão com QR.

**7.3 Cidades vizinhas (WhatsApp da clínica)**
> "Oi! Vi a [clínica] no Google. Somos de Orlândia e fizemos um sistema de
> agenda, prontuário e financeiro para clínicas veterinárias — 30 dias grátis e
> a gente configura junto. Posso te mostrar em 15 minutos por vídeo?"

**7.4 Resposta a pedido de demonstração (em até 1 hora — o link vem pronto no alerta)**
> "Oi! Aqui é o [nome], da PetOrlândia. Recebi seu pedido de demonstração 😊
> Você prefere hoje às [hora] ou amanhã às [hora]? São 15 minutos por vídeo,
> ou passo aí se for na região."

**7.5 Follow-up (dia 3 e dia 7 sem resposta; depois disso, pare)**
> "Oi [nome], só passando para ver se consegue aqueles 15 minutos essa semana!"

**7.6 Pedido de indicação (clínica ativa)**
> "Que bom que a agenda está rodando! Se você conhece outro veterinário que
> sofre com papel e WhatsApp, esse é o seu link: [link de /indicacao]. Ele ganha
> 15 dias a mais de teste e você ganha um mês grátis quando ele assinar."

**7.7 Ligação antes do fim do teste (D-5)**
> "Oi [nome]! Seu teste termina em [n] dias. O que achou até aqui? Tem algo que
> te impediria de continuar?" → resolva a objeção → "Quer que eu te mostre onde
> configurar a assinatura? Leva 2 minutos."

**Objeções comuns**
| Objeção | Resposta |
|---|---|
| "Meus dados ficam seguros?" | Cada pessoa vê só o que você liberar; o financeiro é só seu; e você exporta tudo quando quiser. |
| "Já uso outro sistema." | "O que você mais gosta nele e o que mais te irrita?" — mostre só o que resolve a irritação. Ofereça importar a planilha. |
| "Meu contador cuida disso." | Ótimo — o sistema gera a planilha que ele precisa e você para de mandar papel. Ele continua fazendo a apuração. |
| "Está caro." | São R$ 2 por dia. Uma consulta remarcada por lembrete já paga o mês. |
| "Não tenho tempo para configurar." | Eu configuro com você em 30 minutos, sem custo. |

---

## 8. Métricas e rotina

**Rotina diária (20 min, de manhã):**
1. Abrir o **resumo de aquisição** (e-mail das 07:40 ou painel admin).
2. Responder todo pedido de demonstração (script 7.4).
3. Boas-vindas a cada clínica nova; ligação para cada avaliação travada.
4. Atualizar a etapa de cada contato na planilha.

**Rotina semanal (sexta, 30 min):** contar as etapas e comparar com a meta.

| Métrica | Fonte | Semana 1 | Semana 2 | Semana 4 |
|---|---|---|---|---|
| Estabelecimentos mapeados | planilha | 30–50 | — | — |
| Contatos feitos | planilha | 15 | 40 | 80 |
| Demos | planilha | 2 | 5 | 10 |
| Clínicas em teste | resumo diário | 1–2 | 3–5 | 6–8 |
| Ativadas (paciente + agendamento) | resumo diário | 1 | 2–3 | 5 |
| Pagantes | resumo diário ("assinaturas pagas em dia") | 0 | 1 | 2–4 |

**Taxas que importam:** contato → demo (meta 25%) · demo → teste (50%) ·
teste → ativada (70%) · ativada → pagante (50%). Se uma taxa ficar abaixo da
meta duas semanas seguidas, mude o passo anterior a ela, não o canal inteiro.

---

## 9. Loja/marketplace (paralelo, sem tirar foco das clínicas)

Pet shops entram como vendedores sem mensalidade, só comissão embutida no preço:
> "Oi! Tô montando uma loja online de produtos pet aqui em Orlândia e região.
> Vocês venderiam os produtos de vocês pela plataforma? Sem custo fixo, só
> comissão quando vender."

## 10. Expansão (depois das 5 primeiras clínicas ativas)

São Joaquim da Barra (~35 km) → Guará → Bebedouro → Jardinópolis → Sertãozinho
→ Franca → Ribeirão Preto. Use as clínicas de Orlândia como referência e os
depoimentos como prova. A campanha PMO (antirrábica) continua sendo o canal
de aquisição de tutores — e tutores organizados chegam às clínicas.
