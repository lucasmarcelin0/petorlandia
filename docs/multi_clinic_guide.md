# Guia de Clínicas Múltiplas

Este guia resume como o PetOrlândia isola dados sensíveis quando um mesmo tutor ou paciente é atendido em mais de uma clínica.

## Escopos aplicados

- **Consultas e históricos**: a tela `consulta_qr.html`/`consulta_direct` agora carrega histórico de consultas, prescrições e blocos de orçamento filtrados pelo `clinica_id` ativo. Mesmo que um animal seja compartilhado (por exemplo, sem clínica fixa), cada profissional só enxerga registros emitidos pela própria clínica.【F:app.py†L3745-L3813】【F:templates/partials/historico_prescricoes.html†L1-L46】
- **Modelos críticos**: `OrcamentoItem` e `BlocoPrescricao` possuem `clinica_id` obrigatório e a API garante que novos registros recebam o valor correto. Qualquer item ou prescrição herdará automaticamente a clínica da consulta/bloco que os originou.【F:models.py†L509-L571】
- **Rotas protegidas**: endpoints de criação/edição de itens, blocos de orçamento e blocos de prescrição validam o acesso com `ensure_clinic_access`, impedindo que um usuário de outra clínica modifique registros alheios.【F:app.py†L13089-L13376】【F:app.py†L7136-L7350】

## Como habilitar o recurso

1. **Configure as clínicas**: associe cada veterinário/colaborador a uma clínica principal (`user.veterinario.clinica_id` ou `user.clinica_id`).
2. **Migre o banco**: execute as migrações Alembic para propagar `clinica_id` nos modelos citados (`flask db upgrade`). Os dados legados serão preenchidos automaticamente com base nas relações existentes.【F:migrations/versions/7de8c7e1dd0d_scope_clinic_blocks.py†L1-L64】
3. **Revise cadastros**: garanta que consultas e animais já cadastrados apontem para a clínica correta antes de liberar o compartilhamento de tutores.

## Boas práticas de operação

- Sempre utilize os endpoints oficiais (`/consulta/<id>/orcamento_item`, `/consulta/<id>/bloco_orcamento`, `/consulta/<id>/bloco_prescricao`) para gerar documentos; eles aplicam as validações de escopo automaticamente.
- Ao oferecer o recurso de “tutor compartilhado”, mantenha o `clinica_id` do animal vazio apenas enquanto a segunda clínica ainda não abriu um prontuário próprio.
- Nos atendimentos em campo/QR Code, confirme se o profissional está autenticado com a clínica correta antes de registrar dados.

Seguindo estas etapas, o suporte pode ativar o modo multi-clínica sem expor históricos ou prescrições entre unidades distintas.
