# Plano Estratégico PetOrlândia — 2026

> Elaborado em jul/2026 a partir de auditoria completa do código e das decisões de
> monetização tomadas. Complementa o `PLANO_PRIMEIROS_CLIENTES.md` (execução comercial)
> e o `docs/revisao_proposito_e_melhorias.md` (arquitetura).

## 1. O que o produto é

Um **ERP vertical veterinário + marketplace + govtech** com 7 linhas de receita codificadas:

| Vertical | Monetização |
|---|---|
| ERP clínico (agenda, prontuário, prescrição c/ bulário, exames, NFSe, contabilidade) | Assinatura vet R$ 60/mês (trial 30d) |
| Loja/marketplace (split Mercado Pago via OAuth) | Taxa embutida no preço (ver §3) |
| Casa de Ração (vertical p/ lojas de ração) | Idem loja |
| Vacinas em domicílio | Markup 10% + arredondamento R$5 |
| Planos de saúde pet | Recorrência (subexplorado) |
| Planos banho & tosa | Recorrência (subexplorado) |
| PMO/Prefeitura (antirrábica, castração) | Não monetizado → aquisição de tutores + credencial govtech |

**Diferenciais defensáveis:** bulário estruturado com sugestão de dose, integração ChatGPT
clínica, NFSe integrada, relação com a Prefeitura de Orlândia.

## 2. Decisões de monetização (tomadas em jul/2026)

1. **Preço único com taxa embutida** (modelo supermercado): o tutor vê UM preço.
   `Product.price` = valor que o lojista recebe; vitrine = `Product.preco_publico`
   (= price + 10%, arredondado para cima ao múltiplo de R$ 5). Regra idêntica em
   vacinas e serviços profissionais. Taxa nunca aparece separada.
2. **Frete por modo de entrega**: `'plataforma'` → frete retido pela plataforma
   (repasse ao entregador); `'propria'` → frete integral ao lojista.
3. **Repasses com segurança**: tutor confirma recebimento (`Order.received_at`).
   Desejo declarado: liberar repasses só após confirmação. Caminho atual:
   frete do entregador já fica na conta da plataforma (controle total do timing);
   para o lojista, ativar "liberação programada" no painel Mercado Pago (delay fixo).
   Escrow por evento exigiria plataforma-recebe-tudo + payout PIX (peso regulatório;
   só com volume).

## 3. Funil de aquisição com CAC ~zero

Campanha PMO (antirrábica gratuita) cadastra tutor + pet + telefone →
painel admin de recomendação WhatsApp (/servicos, admin) → V8/V10 paga →
loja → plano de saúde. Cada prefeitura nova replica o funil.

## 4. Horizontes

### 0–30 dias (feito em jul/2026 ✅ / pendente ⬜)
- ✅ Rotacionar credencial Postgres exposta + remover do código
- ✅ Limpeza do repositório (artefatos de debug fora do git)
- ✅ Taxa da loja implementada (antes: fee 0% — loja não monetizava)
- ✅ Confirmação de recebimento pelo tutor
- ⬜ Ativar "liberação programada" no painel Mercado Pago (ação manual)
- ⬜ Executar PLANO_PRIMEIROS_CLIENTES.md (30–50 estabelecimentos mapeados)

### 30–90 dias
- ⬜ 10 lojistas com conta MP conectada ("sem mensalidade, só comissão")
- ⬜ Rotina diária: campanha PMO → recomendação WhatsApp → serviço pago
- ⬜ Métricas de investidor: vets pagantes, GMV loja, pedidos vacina/mês, tutores ativos
- ⬜ Consertar suíte de testes (gate de merge verde de novo)
- ⬜ Começar a fatiar app.py (39k linhas) por domínio — ver revisao_proposito §Fase 2
- ⬜ Ledger de repasses ao entregador (status: aguardando entrega → liberado → pago)

### 90–180 dias (pitch p/ investidores)
Três pilares: (1) tração em cidade pequena = tese de interiorização (mercado que
Petlove/Vetus ignoram); (2) govtech como canal replicável de aquisição;
(3) IA clínica (bulário + dose + ChatGPT) como defensabilidade.
Alvos: SP Ventures, Baita, InovAtiva, anjos do setor vet; editais municipais/SEBRAE
antes de equity.

## 5. Métricas norte

| Métrica | Fonte |
|---|---|
| Veterinários pagantes | `VeterinarianMembership.has_valid_payment()` |
| GMV da loja | `Payment` COMPLETED com `order_id` |
| Margem da plataforma | `marketplace_fee` dos splits |
| Pedidos de vacina/mês | `VaccineServiceRequest` |
| Tutores ativos | `User` com pet + login recente |
| Taxa trial→pago | memberships |
