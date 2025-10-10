# Inventário de rotas autenticadas sem `ensure_clinic_access`

Este relatório foi gerado a partir do script `scripts/clinic_access_inventory.py`,
que realiza a varredura de `app.py`, identifica rotas autenticadas (decoradas com
`@login_required`) e inspeciona a AST para verificar se há chamadas explícitas a
`ensure_clinic_access`. O script também grava os resultados em
`docs/clinic_access_inventory.json` para auditorias posteriores.

## Resumo

- Rotas autenticadas analisadas: **176**
- Rotas autenticadas que chamam `ensure_clinic_access`: **10**
- Rotas autenticadas sem `ensure_clinic_access`: **166**

> Execução: `python scripts/clinic_access_inventory.py`

## Rotas com parâmetro `clinica_id`

As rotas abaixo expõem um parâmetro explícito de clínica e, portanto, foram
priorizadas para instrumentação adicional. A coluna "Plano" indica o status
após esta rodada de trabalho.

| Função | Rotas | Plano |
| --- | --- | --- |
| `api_clinic_appointments` | /api/clinic_appointments/<int:clinica_id> | Mantém `ensure_clinic_access` existente + logging centralizado |
| `clinic_detail` | /clinica/<int:clinica_id> | Logging centralizado via `audit_clinic_access`; avaliar inclusão de `ensure_clinic_access` após revisão de multi-clínicas |
| `cancel_clinic_invite` | /clinica/<int:clinica_id>/convites/<int:invite_id>/cancel | Logging centralizado via `audit_clinic_access`; seguir com plano de revisão de permissões |
| `resend_clinic_invite` | /clinica/<int:clinica_id>/convites/<int:invite_id>/resend | Logging centralizado via `audit_clinic_access`; seguir com plano de revisão de permissões |
| `clinic_dashboard` | /clinica/<int:clinica_id>/dashboard | Logging centralizado; avaliar reforço de escopo quando multi-clínicas forem parametrizadas |
| `remove_specialist` | /clinica/<int:clinica_id>/especialista/<int:veterinario_id>/remove | Logging centralizado; revisar se ação deve exigir clínica ativa |
| `clinic_stock` | /clinica/<int:clinica_id>/estoque | Logging centralizado; considerar `ensure_clinic_access` após redefinir conceito de "clínica ativa" para estoques |
| `clinic_staff_permissions` | /clinica/<int:clinica_id>/funcionario/<int:user_id>/permissoes | Logging centralizado; priorizar ajuste de escopo (Follow-up 1) |
| `remove_funcionario` | /clinica/<int:clinica_id>/funcionario/<int:user_id>/remove | Logging centralizado; priorizar ajuste de escopo (Follow-up 1) |
| `clinic_staff` | /clinica/<int:clinica_id>/funcionarios | Logging centralizado; priorizar ajuste de escopo (Follow-up 1) |
| `delete_clinic_hour` | /clinica/<int:clinica_id>/horario/<int:horario_id>/delete | Logging centralizado; priorizar ajuste de escopo (Follow-up 2) |
| `novo_orcamento` | /clinica/<int:clinica_id>/novo_orcamento | Logging centralizado; alinhar requisito de clínica ativa (Follow-up 3) |
| `orcamentos` | /clinica/<int:clinica_id>/orcamentos | Logging centralizado; alinhar requisito de clínica ativa (Follow-up 3) |
| `create_clinic_veterinario` | /clinica/<int:clinica_id>/veterinario | Logging centralizado; revisar onboarding multi-clínicas |
| `remove_veterinario` | /clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/remove | Logging centralizado; revisar onboarding multi-clínicas |
| `delete_vet_schedule_clinic` | /clinica/<int:clinica_id>/veterinario/<int:veterinario_id>/schedule/<int:horario_id>/delete | Logging centralizado; priorizar ajuste de escopo (Follow-up 2) |

## Categorias de rotas sem `ensure_clinic_access`

1. **Fluxos de conta do usuário (perfil, senha, preferências)** – operam em
   escopo global ou pessoal e não dependem de clínica.
2. **Dashboards administrativos globais** – exemplo: `/painel` agrega totais
   de toda a base; escopo propositalmente global e protegido por permissões de
   administrador.
3. **Funcionalidades veterinárias multi-clínica** – acesso via
   `_user_can_manage_clinic` ou `clinicas_do_usuario`; requerem documentação
   adicional (ver seção de papéis) e, agora, contam com logging centralizado
   quando há divergência entre clínica ativa e a clínica manipulada.
4. **APIs auxiliares e webhooks** – rotas internas ou integrações que não
   expõem `clinica_id`; exigem avaliação caso a caso para adoção de
   `ensure_clinic_access`.

## Próximos passos

- Priorizar as tarefas listadas em `docs/clinic_access_followups.md`.
- Estender o inventário para blueprints ou módulos adicionais caso novas
  rotas autenticadas sejam migradas para fora de `app.py`.
- Incorporar verificações automáticas (por exemplo, teste unitário) que
  falhem quando novas rotas autenticadas forem criadas sem `ensure_clinic_access`
  ou sem justificativa explícita nesta documentação.
