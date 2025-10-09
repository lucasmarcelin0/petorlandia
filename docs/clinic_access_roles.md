# Papéis com visão multi-clínica vs. clínica ativa

Esta nota consolida quais papéis possuem, por desenho, visibilidade entre
múltiplas clínicas e quais devem permanecer restritos à clínica ativa (obtida
por `current_user_clinic_id()`).

## Papéis com visão multi-clínica (intencional)

- **Administradores (`User.role == 'admin'`)** – possuem acesso irrestrito às
  clínicas cadastradas. O helper `clinicas_do_usuario()` retorna todas as
  clínicas para administradores e ordena a lista priorizando uma clínica padrão
  quando disponível.【F:helpers.py†L441-L462】
- **Veterinários com associação multi-clínica** – a entidade `Veterinario`
  mantém a clínica principal (`clinica_id`) e uma lista de clínicas associadas
  via a tabela de junção `veterinario_clinica`. Isso legitima cenários em que o
  profissional atenda em mais de uma clínica, devendo ser acompanhada por
  logging/auditoria quando atuar fora da clínica ativa.【F:models.py†L715-L740】
- **Equipe administrativa transversal** – usuários adicionados como staff em
  múltiplas clínicas aparecem através do relacionamento `ClinicStaff` (um
  registro por clínica) e podem alternar o contexto usando as telas multi-clínica.
  Nessas situações, as permissões específicas (`can_manage_*`) e a auditoria
  recém-implementada devem guiar o controle de acesso.【F:models.py†L654-L679】

## Papéis restritos à clínica ativa

- **Proprietários de clínica** – definidos pelo campo `Clinica.owner_id` (não
  mostrado acima, mas utilizado em diversas rotas), devem operar somente na
  clínica à qual estão vinculados. O helper `_user_can_manage_clinic()` mantém
  essa lógica e agora registra auditoria quando o proprietário opera fora da
  clínica ativa.【F:app.py†L3216-L3228】
- **Staff com escopo limitado** – membros cadastrados em `ClinicStaff` não
  possuem multi-clínica automática; cada vínculo representa uma clínica distinta
  e a mudança de contexto deve ser feita conscientemente. Recomenda-se que a
  clínica ativa reflita o vínculo em foco antes de manipular dados.【F:models.py†L654-L666】
- **Usuários finais (adotante/doador)** – papéis padrão definidos em
  `UserRole` (`adotante`, `doador`) não possuem contexto de clínica, portanto
  permanecem restritos à clínica associada ao animal/serviço acessado.【F:models.py†L59-L75】

## Recomendações operacionais

1. **Auditoria proativa** – os registros emitidos por `audit_clinic_access`
   devem ser monitorados para detectar acessos fora da clínica ativa e suportar
   investigações de segurança.【F:app.py†L427-L470】
2. **Treinamento de usuários multi-clínica** – administradores e veterinários
   devem receber orientações claras sobre como alternar a clínica ativa e sobre
   os impactos de atuar em outra clínica (por exemplo, estoque, agenda).
3. **Políticas de revisão** – recomenda-se revisão periódica das permissões do
   staff (`ClinicStaff.can_manage_*`) e da lista de clínicas associadas a cada
   veterinário, garantindo alinhamento com a auditoria.
