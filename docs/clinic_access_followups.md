# Follow-ups de auditoria de clínicas

1. **Aplicar `ensure_clinic_access` nas rotas de staff** – `clinic_staff`,
   `clinic_staff_permissions`, `remove_funcionario` e rotas correlatas devem
   validar a clínica ativa assim que a estratégia de multi-clínicas for
   homologada, mantendo o logging como camada de monitoramento.【F:app.py†L4092-L4326】
2. **Padronizar verificação de clínica em exclusões/agendamentos** – revisar
   `delete_clinic_hour` e `delete_vet_schedule_clinic` para substituir verificações
   ad-hoc por um helper comum que inclua `ensure_clinic_access` sem quebrar casos
   multi-clínica.【F:app.py†L4232-L4309】
3. **Reavaliar orçamentos multi-clínica** – definir regra clara para `novo_orcamento`
   e `orcamentos`, decidindo se devem exigir clínica ativa ou permitir múltiplas
   clínicas com troca explícita de contexto.【F:app.py†L3915-L4029】
4. **Expandir o inventário para Blueprints** – adaptar o script
   `clinic_access_inventory.py` para percorrer módulos adicionais caso novas
   rotas autenticadas sejam movidas para Blueprints, garantindo cobertura.
5. **Automatizar alerta de regressão** – criar teste ou CI que falhe caso novas
   rotas autenticadas sem `ensure_clinic_access` não possuam justificativa neste
   documento.
6. **Mapear APIs públicas sem login** – revisar rotas como
   `/animal/<int:animal_id>/vacinas/imprimir` que aceitam `clinica_id` via query
   string e definir se devem ser autenticadas e/ou auditadas.
