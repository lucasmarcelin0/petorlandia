# Revisão rápida da base: problemas encontrados e tarefas sugeridas

Este documento consolida 4 tarefas priorizadas a partir de uma revisão estática da base.

## 1) Tarefa de correção de erro de digitação (typo)

**Problema encontrado**
- O teste de página 404 procura pela substring `"nao encontrad"`, que está truncada e sem acentuação adequada, o que reduz clareza e pode mascarar regressões de conteúdo textual.

**Onde**
- `tests/test_accessibility_ui.py` (assert da página 404).

**Tarefa sugerida**
- Ajustar a verificação textual para termos corretos e explícitos (ex.: `"não encontrado"`, `"nao encontrado"`, `"not found"`), mantendo robustez para variações de template.

**Critério de aceite**
- O teste continua validando erro 404, mas com mensagens completas e legíveis.

---

## 2) Tarefa de correção de bug funcional

**Problema encontrado**
- No fluxo de contratação de plano de saúde por formulário, ao submeter com validação OK, o código apenas faz `flash("Plano de saúde contratado!")` e redireciona, com um `TODO` explícito informando que a contratação ainda não é processada.

**Onde**
- `app.py` na view `planosaude_animal` (bloco `if form.validate_on_submit():`).

**Tarefa sugerida**
- Implementar efetivamente a contratação no submit (criação/atualização de `HealthSubscription`, vínculo do plano, persistência transacional e tratamento de erro), evitando falso positivo de sucesso para o usuário.

**Critério de aceite**
- Submissão válida cria/atualiza assinatura real no banco.
- Em falha de persistência, usuário recebe erro e não há mensagem de sucesso indevida.
- Cobertura de teste para sucesso e falha.

---

## 3) Tarefa de ajuste de comentário/discrepância de documentação interna

**Problema encontrado**
- Há comentário inline `#  ←  adicione esta linha` junto ao import de `MailMessage`, típico de instrução temporária de patch/manual, não de documentação de código em estado final.

**Onde**
- `app.py` no bloco de imports.

**Tarefa sugerida**
- Remover ou substituir por comentário técnico permanente (quando necessário), para evitar ruído e ambiguidade sobre mudanças pendentes.

**Critério de aceite**
- Bloco de imports limpo, sem instruções temporárias de edição.

---

## 4) Tarefa para melhorar teste

**Problema encontrado**
- Existe teste placeholder que sempre passa com `assert True` em `TestPrintStyles`, sem validar de fato a existência de regras de impressão.

**Onde**
- `tests/test_accessibility_ui.py` (`test_print_media_query_exists`).

**Tarefa sugerida**
- Transformar o teste em verificação real, por exemplo:
  - abrir CSS principal (e/ou `static/print.css`),
  - garantir presença de `@media print` e regras mínimas de impressão esperadas.

**Critério de aceite**
- Teste falha quando regras de impressão forem removidas acidentalmente.
- Teste deixa de ser placeholder e passa a proteger comportamento real.

---

## Observação de priorização

Sugestão de ordem: **(2) bug funcional** → **(4) melhoria de teste** → **(1) typo** → **(3) comentário**.
