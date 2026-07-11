# PetOrlândia — playbook de execução do super app

Este documento transforma o diagnóstico em uma sequência operacional. A meta
é validar um ciclo completo em Orlândia antes de ampliar cidades ou verticais.

## Métrica norte

**Pets ativamente cuidados por mês:** pets com ao menos uma ação concluída no
mês (consulta, vacina, atualização clínica, serviço ou compra).

Indicadores de proteção: ativação em 7 dias, retenção D30/D90, recompra,
margem líquida por pedido, cancelamento, prazo de entrega, clínicas ativas
semanalmente e trial → assinatura paga.

## Primeiras 48 horas

1. Retirar exports brutos de pesquisa/base do Git e do histórico público;
   preservar somente agregados anonimizados.
2. Configurar backup diário/PITR, testar restauração e registrar RPO/RTO.
3. Rotacionar credenciais expostas e manter integrações sem segredo em estado
   desativado (nunca fail-open).
4. Confirmar responsável por privacidade, suporte, pagamentos e incidentes.

## Próximos 14 dias

- Entrevistar, observando tarefas reais: 10 tutores, 5 clínicas, 5 lojas, 3
  entregadores e 2 responsáveis municipais.
- Registrar cinco funis: cadastro → primeiro pet; pet → agendamento; clínica →
  primeiro atendimento; lojista → primeiro produto/venda; entrega → aceite →
  conclusão → repasse.
- Publicar loja, serviços, perfis e preços sem exigir login; pedir login somente
  para agir ou comprar.
- Tornar cadastro progressivo: contato e senha primeiro; endereço, CRMV, foto e
  pagamento somente quando necessários.
- Escolher uma solução de mensagens com consentimento e SLA. Se não houver
  integração ativa, remover “WhatsApp automático” de todo material comercial.

## Piloto de 30–60 dias em Orlândia

### Oferta mínima

- 3 clínicas usando agenda/prontuário semanalmente;
- 5 lojas com Mercado Pago conectado e catálogo ativo;
- 5–10 SKUs de ração de alta recorrência;
- rede local de entrega com prazo e responsável definidos;
- 40–50 famílias qualificadas no piloto de recompra.

### Critérios de avanço

- ativação de clínica em até 7 dias;
- primeira compra de pelo menos 20% das famílias qualificadas;
- recompra de pelo menos 50% no ciclo esperado;
- entrega no prazo acima de 90%;
- cancelamento abaixo de 5%;
- margem positiva após frete, pagamento, suporte e repasse.

## Conversas com fornecedores

Começar com piloto não exclusivo de poucos SKUs. Formalizar MOQ, validade,
ruptura, devolução, preço protegido, amostras, prazo, faturamento, estoque,
entrega, dados do cliente e verba cooperada. Não assumir estoque próprio antes
de provar recompra e margem.

## Conversas com prefeituras

Transformar Orlândia em caso de referência: cobertura vacinal/castração,
produtividade, satisfação, governança de consentimento e indicadores de
atendimento. Separar claramente serviço público de comunicação comercial
opt-in. Só replicar quando houver playbook e responsável local.

## Marketing após prova de uso

- 3 casos de clínicas;
- 10 depoimentos autorizados de tutores;
- 1 caso municipal;
- vídeos curtos por persona mostrando um resultado;
- SEO local por cidade/serviço;
- indicação recompensada após ativação ou compra válida;
- mídia paga somente depois de retenção e margem comprovadas.

## O que fica congelado por 90 dias

Novas verticais, expansão nacional, estoque próprio relevante, aplicativo nativo
e novos recursos de IA sem uso recorrente. A PWA e o MCP bastam para validar o
mercado neste estágio.
