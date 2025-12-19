# Checklist de formulários e botões com feedback de salvamento

- [ ] **Formulários `data-sync` (submissão AJAX e fila offline)**
  - **templates/animais/tutor_detail.html** – Formulários `data-sync` do tutor e dos animais usam os eventos `form-sync-success` para atualizar DOM manualmente (ex.: trocas de texto, pré-visualização e cabeçalhos) e dependem apenas das funções auxiliares de botão/status do próprio script, não de `FormFeedback.withSavingState`. 【F:templates/animais/tutor_detail.html†L650-L719】
  - **templates/partials/animal_form.html**, **templates/partials/animal_register_form.html**, **templates/partials/consulta_form.html**, **templates/partials/tutor_form.html**, **templates/partials/historico_consultas.html**, **templates/partials/historico_prescricoes.html**, **templates/partials/historico_exames.html**, **templates/partials/historico_orcamentos.html**, **templates/partials/consulta_form.html (delete)** e **templates/partials/tutor_management_panel.html** – Todos marcados com `data-sync`; carregamento de botão é feito por `handleDataSyncForm` em `static/js/form_feedback.js`, sem `withSavingState` (apenas transições de estado padrão). 【F:static/js/form_feedback.js†L398-L428】
  - **templates/consulta_qr.html** – Processa `form[data-sync]` via JavaScript inline, novamente sem `FormFeedback.withSavingState`. 【F:templates/consulta_qr.html†L322-L326】
  - **templates/entregas/delivery_requests.html** – Ouve eventos de sync para mostrar toasts e resetar botões via utilitários próprios (`getStatusButton`, `resetButton`), somente usando `FormFeedback.setIdle/getButton` se existir, mas não `withSavingState`. 【F:templates/entregas/delivery_requests.html†L51-L120】

- [x] **Formulários `.js-cart-form` (carrinho da loja)** – Submissões AJAX na base do layout são envelopadas com `FormFeedback.withSavingState`, garantindo mensagens e estados de botão padronizados. 【F:templates/layout.html†L423-L475】

- [x] **Formulários `.js-admin-delivery-form` (ações administrativas de entrega)** – Também envolvem `FormFeedback.withSavingState` no listener global do layout. 【F:templates/layout.html†L481-L518】

- [ ] **Botões de salvamento em formulários médicos (prescrição, exames, vacinas)** – Cada fluxo chama `FormFeedback.withSavingState` se disponível, mas ainda realiza manipulações de DOM (ex.: `mostrarFeedback`, renderização de listas) manualmente após o fetch; erros são tratados sem fallback quando `FormFeedback` não está presente.
  - Prescrições: botão principal usa `withSavingState` para o salvamento assíncrono. 【F:templates/partials/prescricao_form.html†L606-L618】
  - Exames: botão de salvar invoca `withSavingState` com timeout customizado. 【F:templates/partials/exames_form.html†L539-L550】
  - Vacinas: botão de salvar também usa `withSavingState` com feedback customizado. 【F:templates/partials/vacinas_form.html†L421-L433】

- [ ] **Interações AJAX em `static/js/form_feedback.js`** – O helper aplica `setLoading`/`setSuccess` a todos os `form[data-sync]`, mas não utiliza `withSavingState`; portanto, qualquer DOM extra deve ser tratado pelos consumidores. 【F:static/js/form_feedback.js†L389-L428】
