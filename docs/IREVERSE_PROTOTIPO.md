# iReverse · protótipo de certificadora de créditos de logística reversa

Mini app em `/surpresa/ireverse.html` (card no cantinho secreto). Etapa 1:
protótipo de regras. É estático, sem banco, sem rotas novas e sem migrations.
Os dados ficam só no navegador (localStorage) e podem ser exportados em JSON.

## Arquivos

- `static/easter_egg/ireverse-core.js`: regras puras (navegador e Node).
- `static/easter_egg/ireverse-app.js`: interface.
- `static/easter_egg/ireverse.html`: página.
- `tests/test_ireverse_core.js` e `tests/test_ireverse_prototipo.py`: cenários e rotas.

## Como a dupla contagem é bloqueada

1. **Chave única para sempre.** A NF-e entra uma vez (DV da chave, modelo 55,
   CNPJ e UF do emitente, ano e mês da chave iguais aos da data). Nota rejeitada
   continua ocupando a chave (Dec. 11.413/2023, art. 15 §1º I).
2. **Destinação comprovada.** Só a recicladora destinatária confirma o
   recebimento com MTR e CDF, e cada MTR ou CDF comprova uma única nota. Só a
   massa recebida vira crédito (art. 15 §1º II).
3. **Balanço de massa no atacadista.** A revenda do ferro-velho declara as notas
   de compra que carrega. A massa dessas notas vira crédito de quem vendeu ao
   ferro-velho (prioridade dos catadores, art. 15 §6º), e o ferro-velho fica
   só com o residual. Uma nota de compra não pode ser repassada acima da sua
   massa (não colidência, art. 29 V). Atacadista só vale vendendo a
   recicladora (art. 15 §8º).
4. **Papéis separados.** O verificador homologa (após consulta à SEFAZ) e não
   emite nem vende. Só a entidade gestora emite (art. 23 e art. 29 §1º). A mesma
   raiz de CNPJ não pode ser verificador e ocupar outro elo.
5. **Lastro integral e janela temporal.** O certificado só sai com saldo
   homologado suficiente, de notas do ano da meta ou do ano anterior
   (art. 15 §4º).
6. **Baixa única.** O certificado usado para comprovar meta registra o sistema
   (SINIR/Sisrev-BR ou estadual) e não pode ser usado de novo.
7. **Livro-razão encadeado.** O estado é reconstruído a partir de eventos com
   hash SHA-256 encadeado. Cadeia adulterada não carrega nem é sobrescrita.

## Decisões em aberto (Etapa 2)

- Papel da iReverse: entidade gestora (vende créditos e contrata verificador
  independente) ou verificador (não vende). Não pode ser os dois (art. 29 §1º).
- A apresentação cita autorização da ANM. Para embalagens, quem habilita é o
  MMA (Portarias 1.102/2024, 1.117/2024 e 1.561/2026), com reporte no
  Sisrev-BR (Portaria 1.778/2026).
- Crédito de reciclagem não é crédito de carbono (Lei 15.042/2024).
- Token iREV como pagamento: risco de ativo virtual/arranjo de pagamento
  (Lei 14.478/2022). Preferir pontos de fidelidade não negociáveis.
- Conferir o texto consolidado do Dec. 11.413/2023 (há alterações posteriores
  em 2025) e as regras estaduais dos estados de operação.

## Próximas etapas

3. Backend real (banco, autenticação por papel, XML assinado da NF-e, consulta
   de situação na SEFAZ, custódia por 5 anos). 4. Integração com MTR/CDF do
   SINIR, Sisrev-BR e outros verificadores. 5. Rede de coleta e incentivos.
   6. Ancoragem periódica do hash do livro-razão em blockchain pública.
